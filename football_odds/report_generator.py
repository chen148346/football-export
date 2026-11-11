"""
足球比赛数据文档分析系统 V2.6.3 - 报告生成模块
生成 Word 格式比赛分析报告，包含两个页面的所有非odds数据
报告分为两部分：比赛赛况 + 对战球队信息

[V2.5.5] 变更说明：
- 修复章节编号重复（三个"七"改为七、八、九）
- reports.file_path 改为兼容模式（优先绝对路径，找不到则按文件名查找）
- _convert_to_pdf 标记为废弃死代码

历史变更：
- V2.4.16: 报告统一使用Word格式，不再转换为PDF
- V2.0: 增加完场快照本地缓存检查（优先从数据库读取，避免重复抓取）
"""
import os
import json
import re
import subprocess
import shutil
from datetime import datetime
from docx import Document
from docx.shared import Pt, Cm, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.section import WD_ORIENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

from config import REPORT_DIR, STATE_CODES
from db import get_snapshot, get_match, create_report, get_fulltime_snapshot_cached


# ==================== 样式辅助函数 ====================

def _set_cell_shading(cell, color):
    """设置单元格背景色"""
    shading = OxmlElement('w:shd')
    shading.set(qn('w:fill'), color)
    cell._tc.get_or_add_tcPr().append(shading)


def _set_cell_text(cell, text, bold=False, size=9, align='left', color=None):
    """设置单元格文本"""
    cell.text = ''
    p = cell.paragraphs[0]
    if align == 'center':
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    elif align == 'right':
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    else:
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.space_before = Pt(1)
    p.paragraph_format.space_after = Pt(1)
    run = p.add_run(str(text) if text is not None else '')
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.name = '宋体'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
    if color:
        run.font.color.rgb = RGBColor(*color)


def _add_heading(doc, text, level=1):
    """添加标题"""
    h = doc.add_heading(text, level=level)
    for run in h.runs:
        run.font.name = '微软雅黑'
        run._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')
        if level == 1:
            run.font.size = Pt(16)
            run.font.color.rgb = RGBColor(0, 51, 102)
        elif level == 2:
            run.font.size = Pt(13)
            run.font.color.rgb = RGBColor(0, 80, 160)
        else:
            run.font.size = Pt(11)
            run.font.color.rgb = RGBColor(51, 51, 51)
    return h


def _add_para(doc, text, bold=False, size=10, color=None, align='left'):
    """添加段落"""
    p = doc.add_paragraph()
    if align == 'center':
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    elif align == 'right':
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    else:
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(2)
    run = p.add_run(text)
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.name = '宋体'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
    if color:
        run.font.color.rgb = RGBColor(*color)
    return p


def _make_table(doc, headers, rows, col_widths=None, header_color='4472C4'):
    """创建表格"""
    if not rows:
        _add_para(doc, '暂无数据', size=9, color=(128, 128, 128))
        return None

    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = 'Table Grid'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    # 表头
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        _set_cell_text(cell, h, bold=True, size=9, align='center', color=(255, 255, 255))
        _set_cell_shading(cell, header_color)

    # 数据行
    for r_idx, row in enumerate(rows):
        for c_idx, val in enumerate(row):
            cell = table.rows[r_idx + 1].cells[c_idx]
            align = 'center' if c_idx == 0 or (isinstance(val, (int, float)) and not isinstance(val, bool)) else 'left'
            _set_cell_text(cell, val, size=9, align=align)
            if r_idx % 2 == 1:
                _set_cell_shading(cell, 'F2F2F2')

    # 列宽
    if col_widths:
        for i, w in enumerate(col_widths):
            for row in table.rows:
                row.cells[i].width = Cm(w)

    return table


def _clean_html(text):
    """清理HTML标签"""
    if not text:
        return ''
    text = re.sub(r'<br\s*/?>', ' ', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&')
    text = text.replace('&lt;', '<').replace('&gt;', '>')
    return text.strip()


def _safe_int(val, default=0):
    """安全转整数"""
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _fmt_time(match_time):
    """格式化比赛时间 YYYYMMDDHHMMSS → YYYY-MM-DD HH:MM"""
    if not match_time or len(match_time) < 12:
        return match_time or ''
    return f"{match_time[:4]}-{match_time[4:6]}-{match_time[6:8]} {match_time[8:10]}:{match_time[10:12]}"


# ==================== 第一部分：比赛赛况 ====================

def _gen_match_info(doc, match, snapshot):
    """比赛基本信息"""
    _add_heading(doc, '一、比赛基本信息', level=2)

    state_text = snapshot.get('state_text', '')
    home_score = snapshot.get('home_score', 0)
    away_score = snapshot.get('away_score', 0)
    home_half = snapshot.get('home_half_score', 0)
    away_half = snapshot.get('away_half_score', 0)
    elapsed = snapshot.get('elapsed_min', 0)

    # 比分行
    score_text = f"{match.get('home_team', '')}  {home_score} - {away_score}  {match.get('away_team', '')}"
    _add_para(doc, score_text, bold=True, size=14, align='center', color=(200, 0, 0))

    half_text = f"半场比分: {home_half} - {away_half}"
    if state_text:
        status_display = state_text
        if state_text in ('上半场', '下半场', '加时') and elapsed:
            status_display = f"{elapsed}分钟"
        half_text += f"    比赛状态: {status_display}"
    _add_para(doc, half_text, bold=True, size=10, align='center')

    # 基本信息表
    rows = [
        ['联赛', f"{match.get('sclass_name', '')} {match.get('round_info', '')}", '天气', match.get('weather', '暂无')],
        ['比赛时间', _fmt_time(match.get('match_time', '')), '比赛ID', str(match.get('id', ''))],
        ['主队排名', str(match.get('home_rank', '') or '暂无'), '客队排名', str(match.get('away_rank', '') or '暂无')],
    ]
    _make_table(doc, ['项目', '内容', '项目', '内容'], rows,
                col_widths=[2.5, 6, 2.5, 6])
    doc.add_paragraph()


def _gen_important_events(doc, sj_json):
    """重要事件"""
    _add_heading(doc, '二、重要事件', level=2)
    events = (sj_json or {}).get('events', {})
    event_list = events.get('eventList', []) if events else []

    if not event_list:
        _add_para(doc, '暂无重要事件数据', size=9, color=(128, 128, 128))
        return

    headers = ['时间', '事件', '主队', '客队', '比分', '描述']
    rows = []
    for ev in event_list:
        minute = ev.get('time', '')
        kind = ev.get('kind', '')
        process = ev.get('process', '')

        # 推断事件类型
        goal_in = ev.get('goalIn', {})
        yellow = ev.get('yellowCard', {})
        red = ev.get('redCard', {})
        change = ev.get('changePlayer', {})
        var = ev.get('videoReferee', {})
        match_proc = ev.get('matchProcess', {})

        if isinstance(goal_in, dict) and goal_in:
            kind_cn = '进球'
        elif isinstance(yellow, dict) and yellow:
            kind_cn = '黄牌'
        elif isinstance(red, dict) and red:
            kind_cn = '红牌'
        elif isinstance(change, dict) and change:
            kind_cn = '换人'
        elif isinstance(var, dict) and var:
            kind_cn = 'VAR'
        elif process == 'HalfTime':
            kind_cn = '中场'
        elif process == 'FullTime':
            kind_cn = '完场'
        else:
            kind_cn = '事件'

        # 主队/客队标识
        home_val = kind_cn if kind == 'HOME' else ''
        away_val = kind_cn if kind == 'AWAY' else ''

        # 比分
        if isinstance(goal_in, dict) and goal_in:
            score = f"{goal_in.get('homeScore', '')}-{goal_in.get('guestScore', '')}"
        elif isinstance(match_proc, dict) and match_proc:
            score = f"{match_proc.get('homeScore', '')}-{match_proc.get('guestScore', '')}"
        else:
            score = ''

        # 描述
        desc_parts = []
        if isinstance(goal_in, dict) and goal_in:
            player = goal_in.get('player', '')
            if isinstance(player, dict):
                player = player.get('name', '')
            if player:
                desc_parts.append(str(player))
            assist = goal_in.get('playerAssist', '')
            if isinstance(assist, dict):
                assist = assist.get('name', '')
            if assist:
                desc_parts.append(f"助攻:{assist}")
        if isinstance(yellow, dict) and yellow:
            player = yellow.get('player', '')
            if isinstance(player, dict):
                player = player.get('name', '')
            if player:
                desc_parts.append(str(player))
        if isinstance(red, dict) and red:
            player = red.get('player', '')
            if isinstance(player, dict):
                player = player.get('name', '')
            if player:
                desc_parts.append(str(player))
        if isinstance(change, dict) and change:
            on_p = change.get('onPlayer', {})
            off_p = change.get('offPlayer', {})
            if isinstance(on_p, dict):
                on_p = on_p.get('name', '')
            if isinstance(off_p, dict):
                off_p = off_p.get('name', '')
            if on_p:
                desc_parts.append(f"换上:{on_p}")
            if off_p:
                desc_parts.append(f"换下:{off_p}")
        if isinstance(var, dict) and var:
            player = var.get('player', '')
            if isinstance(player, dict):
                player = player.get('name', '')
            ev_type = var.get('eventType', '')
            if player:
                desc_parts.append(str(player))
            if ev_type:
                desc_parts.append(str(ev_type))
        if process and process not in ('Regular', 'HalfTime', 'FullTime'):
            desc_parts.append(str(process))
        desc = ' '.join(str(p) for p in desc_parts)

        rows.append([minute, kind_cn, home_val, away_val, score, desc])

    _make_table(doc, headers, rows, col_widths=[1.5, 2, 3, 3, 1.5, 6])
    doc.add_paragraph()


def _gen_detailed_events(doc, sj_json):
    """详细事件（按时间正序排列）"""
    _add_heading(doc, '三、详细事件', level=2)
    event_txt = (sj_json or {}).get('eventTxt', {})
    txt_list = event_txt.get('EventTxtLives', []) if event_txt else []

    if not txt_list:
        _add_para(doc, '暂无详细事件数据', size=9, color=(128, 128, 128))
        return

    # 按时间正序排列（原始数据是倒序的，需要反转）
    sorted_events = list(reversed(txt_list))

    headers = ['时间', '阶段', '事件描述']
    rows = []
    for ev in sorted_events:
        happen_time = ev.get('happenTime', '')
        injure_time = ev.get('InjureTime', '')
        if injure_time and _safe_int(injure_time) > 0:
            time_str = f"{happen_time}'+{injure_time}"
        else:
            time_str = f"{happen_time}'"

        match_state = ev.get('matchState', '')
        state_map = {1: '上半场', 2: '中场', 3: '下半场', 4: '加时', -1: '完场'}
        stage = state_map.get(match_state, str(match_state))

        context = _clean_html(ev.get('Context', ''))
        kind = ev.get('kind', '')
        kind_map = {
            'Start': '开赛', 'End': '结束', 'Goal': '进球', 'ownGoal': '乌龙球',
            'Yellow': '黄牌', 'Red': '红牌', 'Substitution': '换人',
            'penaltyKick': '点球', 'ShootOutGoal': '点球进球', 'ShootOutMiss': '点球未进',
            'ShootOutEnd': '点球结束', 'HalfTime': '中场',
        }
        kind_cn = kind_map.get(kind, kind)
        desc = f"[{kind_cn}] {context}" if context else kind_cn

        rows.append([time_str, stage, desc])

    _make_table(doc, headers, rows, col_widths=[2, 2, 13])
    doc.add_paragraph()


def _gen_tech_stats(doc, sj_json, snapshot):
    """技术统计（标题动态）"""
    state_code = snapshot.get('state_code')
    elapsed = snapshot.get('elapsed_min')
    snapshot_type = snapshot.get('snapshot_type', '')

    # 根据快照类型和状态码生成动态标题
    if snapshot_type == 'fulltime' or state_code == -1:
        title = '四、全场技术统计'
    elif snapshot_type == 'halftime' or state_code == 2:
        title = '四、上半场技术统计'
    elif snapshot_type == 'min60':
        title = f'四、{elapsed or 60}分钟技术统计'
    elif state_code in (1, 3, 4) and elapsed:
        title = f'四、{elapsed}分钟技术统计'
    else:
        title = '四、技术统计'

    _add_heading(doc, title, level=2)

    tech_stat = (sj_json or {}).get('techStat', {})
    item_list = tech_stat.get('itemList', []) if tech_stat else []

    if not item_list:
        _add_para(doc, '暂无技术统计数据', size=9, color=(128, 128, 128))
        return

    headers = ['统计项', '主队', '客队']
    rows = []
    for item in item_list:
        name = item.get('name', '')
        home_val = item.get('home', {})
        away_val = item.get('away', {})
        home = home_val.get('text', home_val.get('value', '')) if isinstance(home_val, dict) else home_val
        away = away_val.get('text', away_val.get('value', '')) if isinstance(away_val, dict) else away_val
        rows.append([name, home, away])
    _make_table(doc, headers, rows, col_widths=[6, 5, 5])

    # 上半场技术统计
    first_half = tech_stat.get('firstHalfList', [])
    if first_half:
        _add_heading(doc, '上半场技术统计', level=3)
        rows_fh = []
        for item in first_half:
            home_val = item.get('home', {})
            away_val = item.get('away', {})
            home = home_val.get('text', home_val.get('value', '')) if isinstance(home_val, dict) else home_val
            away = away_val.get('text', away_val.get('value', '')) if isinstance(away_val, dict) else away_val
            rows_fh.append([item.get('name', ''), home, away])
        _make_table(doc, headers, rows_fh, col_widths=[6, 5, 5])

    # 下半场技术统计
    second_half = tech_stat.get('secondHalfList', [])
    if second_half:
        _add_heading(doc, '下半场技术统计', level=3)
        rows_sh = []
        for item in second_half:
            home_val = item.get('home', {})
            away_val = item.get('away', {})
            home = home_val.get('text', home_val.get('value', '')) if isinstance(home_val, dict) else home_val
            away = away_val.get('text', away_val.get('value', '')) if isinstance(away_val, dict) else away_val
            rows_sh.append([item.get('name', ''), home, away])
        _make_table(doc, headers, rows_sh, col_widths=[6, 5, 5])

    doc.add_paragraph()


def _gen_lineup(doc, sj_json, match):
    """首发阵容"""
    _add_heading(doc, '五、首发阵容', level=2)
    lineup = (sj_json or {}).get('lineup', {})

    home_start = lineup.get('homePlayerList', [])
    away_start = lineup.get('guestPlayerList', [])
    home_bench = lineup.get('homeBakPlayerList', [])
    away_bench = lineup.get('guestBakPlayerList', [])
    home_formation = lineup.get('homeFormation', '')
    away_formation = lineup.get('guestFormation', '')

    if not home_start and not away_start:
        _add_para(doc, '暂无首发阵容数据', size=9, color=(128, 128, 128))
        return

    home_team = match.get('home_team', '主队')
    away_team = match.get('away_team', '客队')

    if home_formation or away_formation:
        _add_para(doc, f"{home_team} 阵型: {home_formation}    {away_team} 阵型: {away_formation}",
                  bold=True, size=10)

    headers = [f'号码', f'{home_team} 球员', '位置', f'号码', f'{away_team} 球员', '位置']
    max_len = max(len(home_start), len(away_start))
    rows = []
    for i in range(max_len):
        h = home_start[i] if i < len(home_start) else {}
        a = away_start[i] if i < len(away_start) else {}
        rows.append([
            h.get('number', ''), h.get('name', ''), h.get('pos', ''),
            a.get('number', ''), a.get('name', ''), a.get('pos', ''),
        ])
    _make_table(doc, headers, rows, col_widths=[1.5, 5, 2, 1.5, 5, 2])

    # 替补
    if home_bench or away_bench:
        _add_para(doc, '替补球员:', bold=True, size=10)
        headers_b = ['号码', f'{home_team} 替补', '号码', f'{away_team} 替补']
        max_b = max(len(home_bench), len(away_bench))
        rows_b = []
        for i in range(max_b):
            h = home_bench[i] if i < len(home_bench) else {}
            a = away_bench[i] if i < len(away_bench) else {}
            rows_b.append([h.get('number', ''), h.get('name', ''),
                           a.get('number', ''), a.get('name', '')])
        _make_table(doc, headers_b, rows_b, col_widths=[1.5, 6, 1.5, 6])

    doc.add_paragraph()


def _gen_player_tech(doc, sj_json, match):
    """球员技术统计"""
    _add_heading(doc, '六、球员技术统计', level=2)
    player_tech = (sj_json or {}).get('playerTech', {})

    home_data = player_tech.get('homeTeamDatas', {}) if player_tech else {}
    away_data = player_tech.get('guestTeamDatas', {}) if player_tech else {}
    titles = player_tech.get('titles', []) if player_tech else []

    home_players = home_data.get('playerTechInfo', []) if isinstance(home_data, dict) else []
    away_players = away_data.get('playerTechInfo', []) if isinstance(away_data, dict) else []

    if not home_players and not away_players:
        _add_para(doc, '暂无球员技术统计数据', size=9, color=(128, 128, 128))
        return

    home_team = match.get('home_team', '主队')
    away_team = match.get('away_team', '客队')

    # 获取统计项名称
    stat_names = [t.get('infoTitle', '') for t in titles] if titles else []

    def _make_player_table(players, team_name):
        if not players:
            return
        _add_para(doc, f'{team_name} 球员技术统计:', bold=True, size=10)
        headers = ['号码', '球员'] + stat_names[:10]  # 限制列数避免过宽
        rows = []
        for p in players:
            row = [p.get('playerNum', ''), p.get('playerName', '')]
            tech_map = {}
            for info in p.get('techInfos', []):
                tech_map[info.get('infoKind', '')] = info.get('infoValue', '')
            # 按 titles 顺序取值
            for t in titles[:10]:
                row.append(tech_map.get(t.get('infoKind', ''), ''))
            rows.append(row)
        _make_table(doc, headers, rows)
        doc.add_paragraph()

    _make_player_table(home_players, home_team)
    _make_player_table(away_players, away_team)


def _gen_league_points(doc, an_json, match):
    """联赛积分排名"""
    _add_heading(doc, '七、联赛积分排名', level=2)
    cp = (an_json or {}).get('currentPoints', {})

    home_pts = cp.get('homePoints', {}) if cp else {}
    away_pts = cp.get('awayPoints', {}) if cp else {}

    if not home_pts and not away_pts:
        _add_para(doc, '暂无联赛积分排名数据', size=9, color=(128, 128, 128))
        return

    home_team = match.get('home_team', '主队')
    away_team = match.get('away_team', '客队')

    def _make_points_table(pts_data, team_name):
        if not pts_data or not isinstance(pts_data, dict):
            return
        team_name_actual = pts_data.get('teamName', team_name)
        points_list = pts_data.get('points', [])
        if not points_list:
            return
        _add_para(doc, f'{team_name_actual} 积分排名:', bold=True, size=10)
        headers = ['类型', '场次', '胜', '平', '负', '进球', '失球', '净胜', '积分', '排名', '胜率']
        rows = []
        for p in points_list:
            # 胜率格式化为百分比，保留2位小数
            win_scale = p.get('winScale', 0)
            try:
                win_scale_val = float(win_scale)
                win_scale_str = f"{win_scale_val:.2f}%"
            except (ValueError, TypeError):
                win_scale_str = str(win_scale)
            rows.append([
                p.get('name', ''), p.get('total', ''), p.get('win', ''),
                p.get('draw', ''), p.get('loss', ''), p.get('getGoal', ''),
                p.get('lossGoal', ''), p.get('netGoal', ''), p.get('point', ''),
                p.get('rank', ''), win_scale_str,
            ])
        _make_table(doc, headers, rows,
                    col_widths=[2, 1.5, 1.2, 1.2, 1.2, 1.2, 1.2, 1.2, 1.2, 1.2, 1.5])
        doc.add_paragraph()

    _make_points_table(home_pts, home_team)
    _make_points_table(away_pts, away_team)


def _gen_league_ranking(doc, an_json, match):
    """联赛排名统计"""
    _add_heading(doc, '八、联赛排名统计', level=2)
    cls = (an_json or {}).get('curLeagueStat', {})

    item_list = cls.get('itemList', []) if cls else []

    if not item_list:
        _add_para(doc, '暂无联赛排名统计数据', size=9, color=(128, 128, 128))
        return

    home_team = match.get('home_team', '主队')
    away_team = match.get('away_team', '客队')

    headers = ['统计项', home_team, away_team]
    rows = []
    for item in item_list:
        name = item.get('title', item.get('itemName', ''))
        home = item.get('homeValue', item.get('home', ''))
        guest = item.get('awayValue', item.get('guest', ''))
        # 如果值是dict，提取value
        if isinstance(home, dict):
            home = home.get('value', home.get('text', ''))
        if isinstance(guest, dict):
            guest = guest.get('value', guest.get('text', ''))
        rows.append([name, home, guest])
    _make_table(doc, headers, rows, col_widths=[6, 5, 5])
    doc.add_paragraph()


# ==================== 第二部分：对战球队信息 ====================

def _gen_h2h(doc, an_json, match):
    """交锋历史"""
    _add_heading(doc, '一、交锋历史', level=2)
    vs = (an_json or {}).get('vsMatches', {})

    matches = vs.get('matches', []) if vs else []
    if not matches:
        _add_para(doc, '暂无交锋历史数据', size=9, color=(128, 128, 128))
        return

    home_team = match.get('home_team', '主队')
    away_team = match.get('away_team', '客队')

    # 统计交锋结果
    home_win = draw = away_win = 0
    for m in matches:
        ht = m.get('homeTeam', {})
        at = m.get('awayTeam', {})
        hs = _safe_int(ht.get('score', 0))
        as_ = _safe_int(at.get('score', 0))
        # 判断哪方是当前主队（通过队名匹配）
        if home_team in (ht.get('name', ''), ht.get('nameShort', '')):
            if hs > as_:
                home_win += 1
            elif hs < as_:
                away_win += 1
            else:
                draw += 1
        elif home_team in (at.get('name', ''), at.get('nameShort', '')):
            if as_ > hs:
                home_win += 1
            elif as_ < hs:
                away_win += 1
            else:
                draw += 1
        else:
            if hs > as_:
                home_win += 1
            elif hs < as_:
                away_win += 1
            else:
                draw += 1

    _add_para(doc, f"近 {len(matches)} 场交锋: {home_team} 胜 {home_win} 场, "
                   f"平 {draw} 场, {away_team} 胜 {away_win} 场",
              bold=True, size=10)

    headers = ['日期', '赛事', '主队', '比分', '客队', '半场']
    rows = []
    for m in matches[:20]:
        mt = m.get('matchTime', '')
        date = datetime.fromtimestamp(int(mt)).strftime('%Y-%m-%d') if mt and str(mt).isdigit() else ''
        sclass = m.get('leagueName', '')
        ht = m.get('homeTeam', {})
        at = m.get('awayTeam', {})
        home = ht.get('name', '')
        away = at.get('name', '')
        score = f"{ht.get('score', '')}-{at.get('score', '')}"
        half = f"{ht.get('halfScore', '')}-{at.get('halfScore', '')}"
        rows.append([date, sclass, home, score, away, half])

    _make_table(doc, headers, rows, col_widths=[2.5, 3, 3.5, 2, 3.5, 2])
    doc.add_paragraph()


def _gen_recent_form(doc, an_json, match):
    """近期战绩"""
    _add_heading(doc, '二、近期战绩', level=2)
    nm = (an_json or {}).get('nearMatches', {})

    home_data = nm.get('homeMatches', {}) if nm else {}
    away_data = nm.get('awayMatches', {}) if nm else {}

    home_matches = home_data.get('matches', []) if isinstance(home_data, dict) else []
    away_matches = away_data.get('matches', []) if isinstance(away_data, dict) else []

    if not home_matches and not away_matches:
        _add_para(doc, '暂无近期战绩数据', size=9, color=(128, 128, 128))
        return

    home_team = match.get('home_team', '主队')
    away_team = match.get('away_team', '客队')

    def _make_form_table(matches, team_name):
        if not matches:
            return
        _add_para(doc, f'{team_name} 近期战绩:', bold=True, size=10)
        headers = ['日期', '赛事', '主队', '比分', '客队', '半场']
        rows = []
        for m in matches[:15]:
            mt = m.get('matchTime', '')
            date = datetime.fromtimestamp(int(mt)).strftime('%Y-%m-%d') if mt and str(mt).isdigit() else ''
            sclass = m.get('leagueName', '')
            ht = m.get('homeTeam', {})
            at = m.get('awayTeam', {})
            home = ht.get('name', '')
            away = at.get('name', '')
            score = f"{ht.get('score', '')}-{at.get('score', '')}"
            half = f"{ht.get('halfScore', '')}-{at.get('halfScore', '')}"
            rows.append([date, sclass, home, score, away, half])
        _make_table(doc, headers, rows, col_widths=[2.5, 3, 3.5, 2, 3.5, 2])
        doc.add_paragraph()

    _make_form_table(home_matches, home_team)
    _make_form_table(away_matches, away_team)


def _gen_goal_distribution(doc, sj_json, match):
    """近30场进失球时间分布"""
    _add_heading(doc, '三、近30场进失球时间分布', level=2)
    jsq = (sj_json or {}).get('jsq', {})

    jsq_list = jsq.get('jsqList', []) if jsq else []
    if not jsq_list:
        _add_para(doc, '暂无进失球时间分布数据', size=9, color=(128, 128, 128))
        return

    # 取 Count_30（近30场）
    count_30 = None
    for c in jsq_list:
        if c.get('countType') == 'Count_30':
            count_30 = c
            break
    if not count_30:
        count_30 = jsq_list[0]  # 默认取第一个

    home_info = count_30.get('jsqInfoHome', [])
    away_info = count_30.get('jsqInfoGuest', [])

    if not home_info and not away_info:
        _add_para(doc, '暂无进失球时间分布数据', size=9, color=(128, 128, 128))
        return

    home_team = match.get('home_team', '主队')
    away_team = match.get('away_team', '客队')

    # 时间段
    periods = ['1-15分钟', '16-30分钟', '31-45分钟', '46-60分钟', '61-75分钟', '76-90分钟']

    headers = ['时间段'] + [f'{home_team} 进球', f'{home_team} 失球',
                            f'{away_team} 进球', f'{away_team} 失球']
    rows = []
    for i, period in enumerate(periods):
        h = home_info[i] if i < len(home_info) else {}
        a = away_info[i] if i < len(away_info) else {}
        # JQ/SQ 已经是百分比字符串，如 "22%"
        rows.append([
            period,
            h.get('JQ', ''),
            h.get('SQ', ''),
            a.get('JQ', ''),
            a.get('SQ', ''),
        ])
    _make_table(doc, headers, rows, col_widths=[3, 3, 3, 3, 3])
    doc.add_paragraph()


def _gen_half_full(doc, sj_json, match):
    """近两赛季半场/全场统计"""
    _add_heading(doc, '四、近两赛季半场/全场统计', level=2)
    allhalf = (sj_json or {}).get('allhalf', {})

    half_list = allhalf.get('list', []) if allhalf else []
    if not half_list:
        _add_para(doc, '暂无半场/全场统计数据', size=9, color=(128, 128, 128))
        return

    home_team = match.get('home_team', '主队')
    away_team = match.get('away_team', '客队')

    # type 映射: HA33 = 半胜/全胜, HA13 = 半平/全胜, HA03 = 半负/全胜, etc.
    type_map = {
        'HA33': '半胜/全胜', 'HA13': '半平/全胜', 'HA03': '半负/全胜',
        'HA31': '半胜/全平', 'HA11': '半平/全平', 'HA01': '半负/全平',
        'HA30': '半胜/全负', 'HA10': '半平/全负', 'HA00': '半负/全负',
    }

    headers = ['半场/全场', f'{home_team} 半场', f'{home_team} 全场',
               f'{away_team} 半场', f'{away_team} 全场']
    rows = []
    for item in half_list:
        type_code = item.get('type', '')
        type_name = type_map.get(type_code, type_code)
        rows.append([
            type_name,
            item.get('halfHome', ''), item.get('allHome', ''),
            item.get('halfGuest', ''), item.get('allGuest', ''),
        ])
    _make_table(doc, headers, rows, col_widths=[3, 3, 3, 3, 3])
    doc.add_paragraph()


def _gen_future_matches(doc, an_json, match):
    """未来3场比赛"""
    _add_heading(doc, '五、未来3场比赛', level=2)
    fm = (an_json or {}).get('future3Matches', {})

    home_data = fm.get('homeMatches', {}) if fm else {}
    away_data = fm.get('awayMatches', {}) if fm else {}

    home_future = home_data.get('matches', []) if isinstance(home_data, dict) else []
    away_future = away_data.get('matches', []) if isinstance(away_data, dict) else []

    if not home_future and not away_future:
        _add_para(doc, '暂无未来比赛数据', size=9, color=(128, 128, 128))
        return

    home_team = match.get('home_team', '主队')
    away_team = match.get('away_team', '客队')

    def _make_future_table(matches, team_name):
        if not matches:
            return
        _add_para(doc, f'{team_name} 未来3场:', bold=True, size=10)
        headers = ['日期', '赛事', '主队', '客队']
        rows = []
        for m in matches[:3]:
            mt = m.get('matchTime', '')
            date = datetime.fromtimestamp(int(mt)).strftime('%Y-%m-%d') if mt and str(mt).isdigit() else ''
            sclass = m.get('leagueName', '')
            # homeTeam/awayTeam 在 future3Matches 中是字符串，不是 dict
            ht_name = m.get('homeTeam', '') if isinstance(m.get('homeTeam'), str) else m.get('homeTeam', {}).get('name', '')
            at_name = m.get('awayTeam', '') if isinstance(m.get('awayTeam'), str) else m.get('awayTeam', {}).get('name', '')
            rows.append([date, sclass, ht_name, at_name])
        _make_table(doc, headers, rows, col_widths=[3, 4, 4.5, 4.5])
        doc.add_paragraph()

    _make_future_table(home_future, home_team)
    _make_future_table(away_future, away_team)


def _gen_injury(doc, an_json, match):
    """伤病信息"""
    _add_heading(doc, '六、伤病信息', level=2)
    injury = (an_json or {}).get('injury', {})

    home_injury = injury.get('homeInjury', []) if injury else []
    away_injury = injury.get('awayInjury', []) if injury else []

    if not home_injury and not away_injury:
        _add_para(doc, '暂无伤病信息数据', size=9, color=(128, 128, 128))
        return

    home_team = match.get('home_team', '主队')
    away_team = match.get('away_team', '客队')

    def _make_injury_table(players, team_name):
        if not players:
            return
        _add_para(doc, f'{team_name} 伤病:', bold=True, size=10)
        headers = ['球员', '位置', '伤病原因', '状态']
        rows = []
        for p in players:
            # name 和 position 可能是 dict，包含 cn 字段
            name = p.get('name', p.get('playerName', ''))
            if isinstance(name, dict):
                name = name.get('cn', name.get('name', ''))
            pos = p.get('position', '')
            if isinstance(pos, dict):
                pos = pos.get('cn', pos.get('name', ''))
            reason = p.get('reason', p.get('injuryReson', ''))
            status = p.get('status', '')
            rows.append([name, pos, reason, status])
        _make_table(doc, headers, rows, col_widths=[4, 3, 6, 3])
        doc.add_paragraph()

    _make_injury_table(home_injury, home_team)
    _make_injury_table(away_injury, away_team)


def _gen_pre_analysis(doc, an_json, match):
    """赛前外部舆论分析"""
    _add_heading(doc, '八、赛前外部舆论分析', level=2)
    media = (an_json or {}).get('mediaForecast', {})

    forecasts = media.get('mediaForecastList', []) if media else []
    if not forecasts:
        _add_para(doc, '暂无赛前外部舆论分析数据', size=9, color=(128, 128, 128))
        return

    headers = ['媒体', '预测结果', '分析内容']
    rows = []
    for f in forecasts:
        rows.append([
            f.get('mediaName', ''),
            f.get('forecastResult', ''),
            f.get('forecastContent', ''),
        ])
    _make_table(doc, headers, rows, col_widths=[3, 3, 11])
    doc.add_paragraph()


def _gen_referee(doc, an_json, match):
    """裁判信息"""
    _add_heading(doc, '九、裁判信息', level=2)
    referee = (an_json or {}).get('referee', {})

    if not referee:
        _add_para(doc, '暂无裁判信息数据', size=9, color=(128, 128, 128))
        return

    # referee 数据结构:
    # { referee: {name: {cn}}, homeStatistics: {teamName, win, draw, loss, matchCount, avgYellow},
    #   awayStatistics: {...}, matchScale: {near: 10}, avgYellow: {near: 10, avgNumber: 3.9} }
    ref_info = referee.get('referee', {}) if isinstance(referee, dict) else {}
    match_scale = referee.get('matchScale', {})
    avg_yellow = referee.get('avgYellow', {})
    home_stat = referee.get('homeStatistics', {})
    away_stat = referee.get('awayStatistics', {})

    # 提取裁判姓名
    ref_name = ref_info.get('name', '') if isinstance(ref_info, dict) else ''
    if isinstance(ref_name, dict):
        ref_name = ref_name.get('cn', ref_name.get('name', ''))

    # 执法场次
    ms_near = match_scale.get('near', '') if isinstance(match_scale, dict) else ''

    # 场均黄牌
    ay_avg = avg_yellow.get('avgNumber', '') if isinstance(avg_yellow, dict) else ''

    rows = [
        ['裁判姓名', ref_name, '执法场次', str(ms_near) if ms_near else ''],
        ['场均黄牌', str(ay_avg) if ay_avg else '', '', ''],
    ]

    # 主队/客队执法统计
    if home_stat or away_stat:
        home_str = ''
        away_str = ''
        if home_stat:
            home_str = f"胜{home_stat.get('win', 0)} 平{home_stat.get('draw', 0)} 负{home_stat.get('loss', 0)}"
        if away_stat:
            away_str = f"胜{away_stat.get('win', 0)} 平{away_stat.get('draw', 0)} 负{away_stat.get('loss', 0)}"
        rows.append(['主队执法', home_str, '客队执法', away_str])

    _make_table(doc, ['项目', '内容', '项目', '内容'], rows,
                col_widths=[2.5, 6, 2.5, 6])
    doc.add_paragraph()


def _gen_transfer(doc, an_json, match):
    """转会信息"""
    _add_heading(doc, '十、转会信息', level=2)
    transfer = (an_json or {}).get('transfer', {})

    home_transfer = transfer.get('homeTransfer', []) if transfer else []
    away_transfer = transfer.get('awayTransfer', []) if transfer else []

    if not home_transfer and not away_transfer:
        _add_para(doc, '暂无转会信息数据', size=9, color=(128, 128, 128))
        return

    home_team = match.get('home_team', '主队')
    away_team = match.get('away_team', '客队')

    def _make_transfer_table(transfers, team_name):
        if not transfers:
            return
        _add_para(doc, f'{team_name} 转会信息:', bold=True, size=10)
        headers = ['球员', '转入/转出', '对方俱乐部', '转会费']
        rows = []
        for t in transfers:
            rows.append([
                t.get('playerName', ''),
                t.get('transferType', ''),
                t.get('clubName', ''),
                t.get('transferFee', ''),
            ])
        _make_table(doc, headers, rows, col_widths=[4, 2.5, 5, 4])
        doc.add_paragraph()

    _make_transfer_table(home_transfer, home_team)
    _make_transfer_table(away_transfer, away_team)


def _gen_match_feature(doc, an_json, match):
    """比赛特征 - 按主队/客队区分"""
    _add_heading(doc, '十一、比赛特征', level=2)
    mf = (an_json or {}).get('matchFeature', {})

    features = mf.get('features', []) if mf else []
    if not features:
        _add_para(doc, '暂无比赛特征数据', size=9, color=(128, 128, 128))
        return

    home_team = match.get('home_team', '主队')
    away_team = match.get('away_team', '客队')

    # features 数据结构:
    # [0] 表头: {"title":"本赛季", "win":"胜", "draw":"平", "loss":"负"}
    # [1] {"title":"主队对阵前10名", "win":"4", "draw":"5", "loss":"7"}
    # [2] {"title":"主队对阵后10名", "win":"10", "draw":"6", "loss":"5"}
    # [3] {"title":"客队对阵前10名", "win":"14", "draw":"2", "loss":"2"}
    # [4] {"title":"客队对阵后10名", "win":"5", "draw":"9", "loss":"5"}

    # 按主队/客队分类
    home_features = {}  # {"对阵前10名": "4胜5平7负", ...}
    away_features = {}

    for f in features:
        title = f.get('title', '')
        if not title:
            continue
        win = f.get('win', '')
        draw = f.get('draw', '')
        loss = f.get('loss', '')
        # 跳过表头行
        if str(win) in ('胜', '') and str(draw) in ('平', '') and str(loss) in ('负', ''):
            continue

        record = f"胜{win} 平{draw} 负{loss}" if (win or draw or loss) else ''

        # 根据 title 中的"主队"/"客队"分类
        if '主队' in title:
            # 提取"对阵前10名"等子标题
            sub_title = title.replace('主队', '').strip()
            home_features[sub_title] = record
        elif '客队' in title:
            sub_title = title.replace('客队', '').strip()
            away_features[sub_title] = record

    # 合并所有子标题
    all_sub_titles = list(dict.fromkeys(
        list(home_features.keys()) + list(away_features.keys())
    ))

    if not all_sub_titles:
        _add_para(doc, '暂无比赛特征数据', size=9, color=(128, 128, 128))
        doc.add_paragraph()
        return

    headers = ['特征项', home_team, away_team]
    rows = []
    for sub_title in all_sub_titles:
        rows.append([
            sub_title,
            home_features.get(sub_title, ''),
            away_features.get(sub_title, ''),
        ])
    _make_table(doc, headers, rows, col_widths=[5, 5.5, 5.5])
    doc.add_paragraph()


def _gen_team_tech(doc, an_json, match):
    """球队技术统计"""
    _add_heading(doc, '十二、球队技术统计', level=2)
    mts = (an_json or {}).get('matchTechStatistic', {})

    item_list = mts.get('itemList', []) if mts else []
    if not item_list:
        _add_para(doc, '暂无球队技术统计数据', size=9, color=(128, 128, 128))
        return

    home_team = match.get('home_team', '主队')
    away_team = match.get('away_team', '客队')

    headers = ['统计项', home_team, away_team]
    rows = []
    for item in item_list:
        rows.append([item.get('itemName', ''), item.get('home', ''), item.get('guest', '')])
    _make_table(doc, headers, rows, col_widths=[6, 5, 5])
    doc.add_paragraph()


# ==================== 主报告生成函数 ====================

def _build_report_filename(match, snapshot, report_type):
    """构建报告文件名
    格式: 联赛类型_赛事ID_主队v客队_比赛状态（时间）_yyyymmddhhmm
    """
    league = match.get('sclass_name', '未知联赛')
    match_id = match.get('id', '')
    home = match.get('home_team', '主队')
    away = match.get('away_team', '客队')

    state_text = snapshot.get('state_text', '')
    elapsed = snapshot.get('elapsed_min', 0)

    # 根据报告类型和状态生成状态文本
    if report_type == 'fulltime':
        status = '完场'
    elif report_type == 'halftime':
        status = '中场'
    elif report_type == 'min60':
        status = f"{elapsed or 60}分钟"
    elif state_text in ('上半场', '下半场', '加时') and elapsed:
        status = f"{elapsed}分钟"
    elif state_text:
        status = state_text
    else:
        status = report_type

    now = datetime.now().strftime('%Y%m%d%H%M')
    filename = f"{league}_{match_id}_{home}v{away}_{status}_{now}.docx"
    # 清理文件名中的非法字符
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    return filename


def generate_report(match_id, snapshot_id, report_type='manual'):
    """生成比赛分析报告

    Args:
        match_id: 比赛ID
        snapshot_id: 快照ID
        report_type: 报告类型 (halftime/fulltime/manual)

    Returns:
        (report_id, filepath)
    """
    match = get_match(match_id)
    if not match:
        raise ValueError(f"比赛 {match_id} 不存在")

    snapshot = get_snapshot(snapshot_id)
    if not snapshot:
        raise ValueError(f"快照 {snapshot_id} 不存在")

    sj_json = json.loads(snapshot['shijian_json']) if snapshot.get('shijian_json') else {}
    an_json = json.loads(snapshot['analysis_json']) if snapshot.get('analysis_json') else {}

    # 创建文档
    doc = Document()

    # 设置页边距
    for section in doc.sections:
        section.top_margin = Cm(2)
        section.bottom_margin = Cm(2)
        section.left_margin = Cm(2)
        section.right_margin = Cm(2)

    # 设置默认字体
    style = doc.styles['Normal']
    style.font.name = '宋体'
    style.font.size = Pt(10)
    style._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')

    # ===== 封面标题 =====
    home_team = match.get('home_team', '')
    away_team = match.get('away_team', '')
    league = match.get('sclass_name', '')
    title = f"{league} {home_team} vs {away_team}"
    _add_heading(doc, title, level=1)
    _add_para(doc, f"比赛分析报告", bold=True, size=12, align='center', color=(100, 100, 100))
    _add_para(doc, f"报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
              size=9, align='center', color=(128, 128, 128))
    doc.add_paragraph()

    # ===== 第一部分：比赛赛况 =====
    _add_heading(doc, '第一部分  比赛赛况', level=1)

    _gen_match_info(doc, match, snapshot)
    _gen_important_events(doc, sj_json)
    _gen_detailed_events(doc, sj_json)
    _gen_tech_stats(doc, sj_json, snapshot)
    _gen_lineup(doc, sj_json, match)
    _gen_player_tech(doc, sj_json, match)
    _gen_league_points(doc, an_json, match)
    _gen_league_ranking(doc, an_json, match)

    # ===== 第二部分：对战球队信息 =====
    _add_heading(doc, '第二部分  对战球队信息', level=1)

    _gen_h2h(doc, an_json, match)
    _gen_recent_form(doc, an_json, match)
    _gen_goal_distribution(doc, sj_json, match)
    _gen_half_full(doc, sj_json, match)
    _gen_future_matches(doc, an_json, match)
    _gen_injury(doc, an_json, match)
    _gen_referee(doc, an_json, match)
    _gen_transfer(doc, an_json, match)
    _gen_match_feature(doc, an_json, match)
    _gen_team_tech(doc, an_json, match)

    # V2.4.16: 报告统一使用Word格式，不再转换为PDF
    # 生成文件名（保持.docx扩展名）
    filename = _build_report_filename(match, snapshot, report_type)
    # 确保扩展名为.docx
    if not filename.endswith('.docx'):
        if filename.endswith('.pdf'):
            filename = filename[:-4] + '.docx'
        else:
            filename = filename + '.docx'
    docx_filepath = os.path.join(REPORT_DIR, filename)
    doc.save(docx_filepath)

    # V2.4.16: 不再执行PDF转换，直接使用Word文件
    # 记录到数据库
    report_data = {
        'match_id': match_id,
        'snapshot_id': snapshot_id,
        'report_type': report_type,
        'file_path': docx_filepath,
        'file_name': filename,
    }
    report_id = create_report(report_data)

    return report_id, docx_filepath


# ==================== V2.5.1: 纯读报告生成函数 ====================

def generate_report_from_snapshot(match_id, snapshot_id):
    """
    V2.5.1: 纯读版报告生成函数（架构师定稿）
    ============================================================
    核心原则（纯读操作边界）：
        1. 严禁触发网页状态刷新（不调用refresh_match_status）
        2. 严禁创建新快照（不调用fetch_match_detail）
        3. 严禁写入数据库（不调用create_report，仅生成.docx文件）
        4. 所有数据从matches表和snapshots表读取

    数据源：
        - 比赛基本信息：从matches表读取
        - 详细数据（事件、技术统计、阵容等）：从snapshots表的
          shijian_json和analysis_json字段解析读取
        - 比赛分钟数：直接使用snapshots表的elapsed_min字段

    参数:
        match_id: 比赛ID
        snapshot_id: 快照ID

    返回:
        filepath: 生成的Word文件路径（不返回report_id，因为不写数据库）
    """
    # 1. 纯读：从数据库获取match和snapshot
    match = get_match(match_id)
    if not match:
        raise ValueError(f"比赛 {match_id} 不存在")

    snapshot = get_snapshot(snapshot_id)
    if not snapshot:
        raise ValueError(f"快照 {snapshot_id} 不存在")

    # 2. 解析快照中存储的JSON数据（纯读，不抓取网页）
    sj_json = json.loads(snapshot['shijian_json']) if snapshot.get('shijian_json') else {}
    an_json = json.loads(snapshot['analysis_json']) if snapshot.get('analysis_json') else {}

    # 3. 创建文档
    doc = Document()

    # 设置页边距
    for section in doc.sections:
        section.top_margin = Cm(2)
        section.bottom_margin = Cm(2)
        section.left_margin = Cm(2)
        section.right_margin = Cm(2)

    # 设置默认字体
    style = doc.styles['Normal']
    style.font.name = '宋体'
    style.font.size = Pt(10)
    style._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')

    # 4. 封面标题
    home_team = match.get('home_team', '')
    away_team = match.get('away_team', '')
    league = match.get('sclass_name', '')
    title = f"{league} {home_team} vs {away_team}"
    _add_heading(doc, title, level=1)
    _add_para(doc, f"比赛分析报告", bold=True, size=12, align='center', color=(100, 100, 100))
    _add_para(doc, f"报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
              size=9, align='center', color=(128, 128, 128))
    doc.add_paragraph()

    # 5. 第一部分：比赛赛况（复用现有生成函数，数据源为快照JSON）
    _add_heading(doc, '第一部分  比赛赛况', level=1)

    _gen_match_info(doc, match, snapshot)
    _gen_important_events(doc, sj_json)
    _gen_detailed_events(doc, sj_json)
    _gen_tech_stats(doc, sj_json, snapshot)
    _gen_lineup(doc, sj_json, match)
    _gen_player_tech(doc, sj_json, match)
    _gen_league_points(doc, an_json, match)
    _gen_league_ranking(doc, an_json, match)

    # 6. 第二部分：对战球队信息
    _add_heading(doc, '第二部分  对战球队信息', level=1)

    _gen_h2h(doc, an_json, match)
    _gen_recent_form(doc, an_json, match)
    _gen_goal_distribution(doc, sj_json, match)
    _gen_half_full(doc, sj_json, match)
    _gen_future_matches(doc, an_json, match)
    _gen_injury(doc, an_json, match)
    _gen_referee(doc, an_json, match)
    _gen_transfer(doc, an_json, match)
    _gen_match_feature(doc, an_json, match)
    _gen_team_tech(doc, an_json, match)

    # 7. 生成文件名（复用现有命名规范，时间戳用当前时间）
    filename = _build_report_filename(match, snapshot, snapshot.get('snapshot_type', 'manual'))
    if not filename.endswith('.docx'):
        if filename.endswith('.pdf'):
            filename = filename[:-4] + '.docx'
        else:
            filename = filename + '.docx'
    docx_filepath = os.path.join(REPORT_DIR, filename)
    doc.save(docx_filepath)

    # V2.5.1: 纯读模式，不写入数据库（不调用create_report）
    return docx_filepath


def _convert_to_pdf(docx_path, pdf_path):
    """
    V2.0 新增：使用 LibreOffice 将 Word 转换为 PDF
    需要系统安装 libreoffice (sudo apt install libreoffice)
    V2.4.9: 支持config.py的LIBREOFFICE_PATH配置和环境变量
    V2.4.16: 已废弃，报告统一使用Word格式，不再转换为PDF
             保留此函数以备将来可能需要PDF转换

    返回: PDF文件路径，转换失败返回 None
    """
    # V2.4.9: 优先使用config.py的LIBREOFFICE_PATH配置
    from config import LIBREOFFICE_PATH
    soffice_cmd = None
    if LIBREOFFICE_PATH and os.path.exists(LIBREOFFICE_PATH):
        soffice_cmd = LIBREOFFICE_PATH
    elif shutil.which('libreoffice'):
        soffice_cmd = 'libreoffice'
    elif shutil.which('soffice'):
        soffice_cmd = 'soffice'

    if not soffice_cmd:
        print("[警告] LibreOffice 未安装或未配置路径，无法转换为PDF，将使用Word格式")
        print("[提示] 请设置环境变量LIBREOFFICE_PATH，或在config.py中配置LIBREOFFICE_PATH")
        return None

    try:
        output_dir = os.path.dirname(pdf_path)
        cmd = [
            soffice_cmd, '--headless', '--convert-to', 'pdf',
            '--outdir', output_dir, docx_path
        ]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60
        )

        if result.returncode == 0:
            # LibreOffice 生成的PDF文件名与Word文件名相同（扩展名不同）
            generated_pdf = docx_path.replace('.docx', '.pdf')
            if os.path.exists(generated_pdf):
                # 如果生成的PDF路径与目标路径不同，重命名
                if generated_pdf != pdf_path:
                    shutil.move(generated_pdf, pdf_path)
                return pdf_path
        print(f"[警告] PDF转换失败: {result.stderr}")
        return None
    except Exception as e:
        print(f"[警告] PDF转换异常: {e}")
        return None


if __name__ == '__main__':
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from db import init_db, create_snapshot, update_match
    from scraper import fetch_match_detail

    init_db()

    test_id = 2789499
    print(f"抓取比赛 {test_id} 数据...")
    detail = fetch_match_detail(test_id)

    match_data = {
        'id': test_id,
        'sclass_name': '英超',
        'match_time': '20260524230000',
        'home_team': '布莱顿',
        'away_team': '曼彻斯特联',
        'weather': detail.get('weather', ''),
        'round_info': detail.get('round_info', ''),
    }
    update_match(match_data)

    snapshot_id = create_snapshot({
        'match_id': test_id,
        'snapshot_type': 'fulltime',
        'state_code': -1,
        'state_text': '完场',
        'home_score': 0,
        'away_score': 3,
        'home_half_score': 0,
        'away_half_score': 2,
        'elapsed_min': 90,
        'shijian_json': json.dumps(detail['shijian_json'], ensure_ascii=False) if detail['shijian_json'] else None,
        'analysis_json': json.dumps(detail['analysis_json'], ensure_ascii=False) if detail['analysis_json'] else None,
    })

    print(f"快照已创建: {snapshot_id}")
    report_id, filepath = generate_report(test_id, snapshot_id, 'fulltime')
    print(f"报告已生成: {filepath}")
