#!/usr/bin/env python3
"""
足球比赛数据文档分析系统 V2.6.3 - Excel批量导出模块
7个Sheet：match_overview, tech_stats, events, player_stats, near_matches, vs_matches, goal_distribution
所有数据保留完整 odds 字段（football_odds 系统不过滤，_filter_odds 为透传函数）

⚠️ 代码冻结声明（V2.4.10起）
本文件已进入冻结状态，将交由新开发者进行独立重构（面向ML的数据清洗）。
任何对本文件的修改必须经过架构师审批，请勿擅自修改，以免与新开发者的重构产生冲突。
新模块将独立为 ml_data_pipeline，不依赖现有Flask系统。
[V2.5.5] 冻结期间发现严重bug可紧急修复（加注释+通知架构师），维护责任由当前接手开发者承担。
"""
import os
import json
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# [football_odds] 本系统保留全部 odds 数据，导出不过滤；定义透传函数保持下方调用点不变
def _filter_odds(data):
    return data
from config import REPORT_DIR

EXCEL_EXPORT_DIR = os.path.join(REPORT_DIR, 'excel_export')
os.makedirs(EXCEL_EXPORT_DIR, exist_ok=True)

HEADER_FONT = Font(name='微软雅黑', bold=True, color='FFFFFF', size=11)
HEADER_FILL = PatternFill(start_color='3a5462', end_color='3a5462', fill_type='solid')
HOME_FILL = PatternFill(start_color='e8f0fe', end_color='e8f0fe', fill_type='solid')
AWAY_FILL = PatternFill(start_color='fef0e8', end_color='fef0e8', fill_type='solid')
NORMAL_FONT = Font(name='微软雅黑', size=10)
THIN_BORDER = Border(
    left=Side(style='thin', color='cccccc'),
    right=Side(style='thin', color='cccccc'),
    top=Side(style='thin', color='cccccc'),
    bottom=Side(style='thin', color='cccccc')
)


def _write_header(ws, headers):
    """写入表头"""
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.border = THIN_BORDER
    ws.row_dimensions[1].height = 25


def _write_row(ws, row_idx, data_list, fill=None):
    """写入数据行"""
    for col, val in enumerate(data_list, 1):
        cell = ws.cell(row=row_idx, column=col, value=val)
        cell.font = NORMAL_FONT
        cell.border = THIN_BORDER
        cell.alignment = Alignment(horizontal='left', vertical='center')
        if fill:
            cell.fill = fill


def _auto_width(ws, headers):
    """自动列宽"""
    for col, h in enumerate(headers, 1):
        max_len = len(str(h))
        for row in ws.iter_rows(min_row=2, max_row=min(ws.max_row, 50), min_col=col, max_col=col):
            for cell in row:
                if cell.value:
                    max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[get_column_letter(col)].width = min(max_len + 4, 40)


def _safe_json_loads(json_str):
    """安全解析JSON"""
    if not json_str:
        return {}
    if isinstance(json_str, dict):
        return json_str
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return {}


def _gen_match_overview(ws, snapshots_data, mode):
    """Sheet1: 比赛总览"""
    headers = [
        'match_id', 'sclass_name', 'match_time', 'match_date', 'home_team', 'away_team',
        'home_rank', 'away_rank', 'home_score', 'away_score',
        'home_half_score', 'away_half_score', 'state_code', 'state_text',
        'elapsed_min', 'snapshot_source', 'weather', 'round_info'
    ]
    # 训练模式增加标签列
    if mode == 'training':
        headers += ['label_home_win', 'label_draw', 'label_away_win',
                    'label_total_goals', 'label_home_goals', 'label_away_goals']
    _write_header(ws, headers)

    for idx, snap in enumerate(snapshots_data, 2):
        home_score = snap.get('home_score', 0) or 0
        away_score = snap.get('away_score', 0) or 0
        home_half = snap.get('home_half_score', 0) or 0
        away_half = snap.get('away_half_score', 0) or 0
        row_data = [
            snap.get('match_id'), snap.get('sclass_name', ''), snap.get('match_time', ''),
            snap.get('match_date', ''), snap.get('home_team', ''), snap.get('away_team', ''),
            snap.get('home_rank', 0), snap.get('away_rank', 0),
            home_score, away_score, home_half, away_half,
            snap.get('state_code'), snap.get('state_text', ''),
            snap.get('elapsed_min', 0), snap.get('snapshot_type', 'fulltime'),
            snap.get('weather', ''), snap.get('round_info', '')
        ]
        if mode == 'training':
            # 标签计算
            label_home_win = 1 if home_score > away_score else 0
            label_draw = 1 if home_score == away_score else 0
            label_away_win = 1 if home_score < away_score else 0
            row_data += [label_home_win, label_draw, label_away_win,
                         home_score + away_score, home_score, away_score]
        _write_row(ws, idx, row_data)
    _auto_width(ws, headers)


def _gen_tech_stats(ws, snapshots_data, mode):
    """Sheet2: 技术统计（动态列）"""
    # 收集所有统计项名称
    all_stat_names = set()
    parsed_snaps = []
    for snap in snapshots_data:
        sj = _safe_json_loads(snap.get('shijian_json'))
        sj = _filter_odds(sj)
        tech_stat = sj.get('techStat', {}) if isinstance(sj, dict) else {}
        first_half = tech_stat.get('firstHalfList', []) if isinstance(tech_stat, dict) else []
        for item in first_half:
            if isinstance(item, dict) and item.get('name'):
                all_stat_names.add(item['name'])
        parsed_snaps.append((snap, sj))

    sorted_stats = sorted(all_stat_names)
    headers = ['match_id', 'home_team', 'away_team'] + [f'home_{n}' for n in sorted_stats] + [f'away_{n}' for n in sorted_stats]
    _write_header(ws, headers)

    for idx, (snap, sj) in enumerate(parsed_snaps, 2):
        tech_stat = sj.get('techStat', {}) if isinstance(sj, dict) else {}
        first_half = tech_stat.get('firstHalfList', []) if isinstance(tech_stat, dict) else []
        home_stats = {}
        away_stats = {}
        for item in first_half:
            if isinstance(item, dict) and item.get('name'):
                home_stats[item['name']] = item.get('homeValue', '')
                away_stats[item['name']] = item.get('awayValue', '')
        row_data = [snap.get('match_id'), snap.get('home_team', ''), snap.get('away_team', '')]
        row_data += [home_stats.get(n, '') for n in sorted_stats]
        row_data += [away_stats.get(n, '') for n in sorted_stats]
        _write_row(ws, idx, row_data)
    _auto_width(ws, headers)


def _gen_events(ws, snapshots_data, mode):
    """Sheet3: 重要事件"""
    headers = ['match_id', 'home_team', 'away_team', 'time', 'event_type', 'home_value', 'away_value', 'score', 'description']
    _write_header(ws, headers)
    row_idx = 2
    for snap in snapshots_data:
        sj = _safe_json_loads(snap.get('shijian_json'))
        sj = _filter_odds(sj)
        events = sj.get('events', {}) if isinstance(sj, dict) else {}
        event_list = events.get('eventList', []) if isinstance(events, dict) else []
        for ev in event_list:
            if not isinstance(ev, dict):
                continue
            row_data = [
                snap.get('match_id'), snap.get('home_team', ''), snap.get('away_team', ''),
                ev.get('time', ''), ev.get('type', ''), ev.get('homeValue', ''),
                ev.get('awayValue', ''), ev.get('score', ''), ev.get('description', '')
            ]
            _write_row(ws, row_idx, row_data)
            row_idx += 1
    _auto_width(ws, headers)


def _gen_player_stats(ws, snapshots_data, mode):
    """Sheet4: 球员统计"""
    headers = ['match_id', 'team', 'player_name', 'goals', 'assists', 'yellow_cards', 'red_cards', 'rating']
    _write_header(ws, headers)
    row_idx = 2
    for snap in snapshots_data:
        sj = _safe_json_loads(snap.get('shijian_json'))
        sj = _filter_odds(sj)
        player_tech = sj.get('playerTech', {}) if isinstance(sj, dict) else {}
        for team_key in ['home', 'away']:
            team_data = player_tech.get(team_key, []) if isinstance(player_tech, dict) else []
            for p in team_data:
                if not isinstance(p, dict):
                    continue
                row_data = [
                    snap.get('match_id'), team_key, p.get('name', ''),
                    p.get('goals', 0), p.get('assists', 0),
                    p.get('yellowCards', 0), p.get('redCards', 0), p.get('rating', '')
                ]
                _write_row(ws, row_idx, row_data)
                row_idx += 1
    _auto_width(ws, headers)


def _gen_near_matches(ws, snapshots_data, mode):
    """Sheet5: 近期战绩"""
    headers = ['match_id', 'team_name', 'near_match_id', 'league_name', 'match_time',
               'home_team', 'away_team', 'home_score', 'away_score', 'result', 'match_type']
    _write_header(ws, headers)
    row_idx = 2
    for snap in snapshots_data:
        an = _safe_json_loads(snap.get('analysis_json'))
        an = _filter_odds(an)
        nm = an.get('nearMatches', {}) if isinstance(an, dict) else {}
        for team_key in ['homeMatches', 'awayMatches']:
            team_data = nm.get(team_key, {}) if isinstance(nm, dict) else {}
            team_name = team_data.get('teamName', '') if isinstance(team_data, dict) else ''
            matches = team_data.get('matches', []) if isinstance(team_data, dict) else []
            for m in matches:
                if not isinstance(m, dict):
                    continue
                home = m.get('homeTeam', {}) if isinstance(m.get('homeTeam'), dict) else {}
                away = m.get('awayTeam', {}) if isinstance(m.get('awayTeam'), dict) else {}
                hs = home.get('score', '') if isinstance(home, dict) else ''
                as_ = away.get('score', '') if isinstance(away, dict) else ''
                result = ''
                if hs != '' and as_ != '':
                    try:
                        if int(hs) > int(as_): result = '胜'
                        elif int(hs) < int(as_): result = '负'
                        else: result = '平'
                    except (ValueError, TypeError):
                        pass
                row_data = [
                    snap.get('match_id'), team_name, m.get('id'), m.get('leagueName', ''),
                    m.get('matchTime', ''), home.get('name', ''), away.get('name', ''),
                    hs, as_, result, team_key
                ]
                _write_row(ws, row_idx, row_data)
                row_idx += 1
    _auto_width(ws, headers)


def _gen_vs_matches(ws, snapshots_data, mode):
    """Sheet6: 交锋历史"""
    headers = ['match_id', 'home_team', 'away_team', 'vs_match_id', 'league_name', 'match_time',
               'vs_home_team', 'vs_away_team', 'vs_home_score', 'vs_away_score']
    _write_header(ws, headers)
    row_idx = 2
    for snap in snapshots_data:
        an = _safe_json_loads(snap.get('analysis_json'))
        an = _filter_odds(an)
        vs = an.get('vsMatches', {}) if isinstance(an, dict) else {}
        matches = vs.get('matches', []) if isinstance(vs, dict) else []
        for m in matches:
            if not isinstance(m, dict):
                continue
            home = m.get('homeTeam', {}) if isinstance(m.get('homeTeam'), dict) else {}
            away = m.get('awayTeam', {}) if isinstance(m.get('awayTeam'), dict) else {}
            row_data = [
                snap.get('match_id'), snap.get('home_team', ''), snap.get('away_team', ''),
                m.get('id'), m.get('leagueName', ''), m.get('matchTime', ''),
                home.get('name', ''), away.get('name', ''),
                home.get('score', ''), away.get('score', '')
            ]
            _write_row(ws, row_idx, row_data)
            row_idx += 1
    _auto_width(ws, headers)


def _gen_goal_distribution(ws, snapshots_data, mode):
    """Sheet7: 进失球分布"""
    headers = ['match_id', 'home_team', 'away_team',
               'home_goal_0_15', 'home_goal_16_30', 'home_goal_31_45',
               'home_goal_46_60', 'home_goal_61_75', 'home_goal_76_90',
               'away_goal_0_15', 'away_goal_16_30', 'away_goal_31_45',
               'away_goal_46_60', 'away_goal_61_75', 'away_goal_76_90',
               'home_concede_0_15', 'home_concede_16_30', 'home_concede_31_45',
               'home_concede_46_60', 'home_concede_61_75', 'home_concede_76_90',
               'away_concede_0_15', 'away_concede_16_30', 'away_concede_31_45',
               'away_concede_46_60', 'away_concede_61_75', 'away_concede_76_90']
    _write_header(ws, headers)
    for idx, snap in enumerate(snapshots_data, 2):
        sj = _safe_json_loads(snap.get('shijian_json'))
        sj = _filter_odds(sj)
        jsq = sj.get('jsq', {}) if isinstance(sj, dict) else {}
        row_data = [snap.get('match_id'), snap.get('home_team', ''), snap.get('away_team', '')]
        # jsq结构：6个时间段的进球/失球率
        for period in range(6):
            row_data.append(jsq.get(f'homeGoal{period}', ''))
        for period in range(6):
            row_data.append(jsq.get(f'awayGoal{period}', ''))
        for period in range(6):
            row_data.append(jsq.get(f'homeConcede{period}', ''))
        for period in range(6):
            row_data.append(jsq.get(f'awayConcede{period}', ''))
        _write_row(ws, idx, row_data)
    _auto_width(ws, headers)


def _gen_data_dictionary(filepath):
    """生成数据字典"""
    wb = Workbook()
    sheets_info = {
        'match_overview': ('比赛总览', [
            ('match_id', '比赛ID'), ('sclass_name', '联赛名称'), ('match_time', '比赛时间(YYYYMMDDHHMMSS)'),
            ('match_date', '比赛日期(YYYY-MM-DD)'), ('home_team', '主队'), ('away_team', '客队'),
            ('home_rank', '主队排名'), ('away_rank', '客队排名'),
            ('home_score', '主队得分'), ('away_score', '客队得分'),
            ('home_half_score', '主队半场得分'), ('away_half_score', '客队半场得分'),
            ('state_code', '状态码'), ('state_text', '状态文本'),
            ('elapsed_min', '已进行分钟'), ('snapshot_source', '快照来源'),
            ('weather', '天气'), ('round_info', '轮次信息'),
            ('label_home_win', '标签:主队胜(0/1)'), ('label_draw', '标签:平局(0/1)'),
            ('label_away_win', '标签:客队胜(0/1)'), ('label_total_goals', '标签:总进球'),
            ('label_home_goals', '标签:主队进球'), ('label_away_goals', '标签:客队进球')
        ]),
        'tech_stats': ('技术统计', [('动态列', '主队/客队各统计项')]),
        'events': ('重要事件', [('time', '时间'), ('event_type', '事件类型'), ('score', '比分')]),
        'player_stats': ('球员统计', [('player_name', '球员名'), ('goals', '进球'), ('rating', '评分')]),
        'near_matches': ('近期战绩', [('team_name', '球队名'), ('result', '胜/平/负')]),
        'vs_matches': ('交锋历史', [('vs_match_id', '交锋比赛ID')]),
        'goal_distribution': ('进失球分布', [('6个时间段', '0-15,16-30,31-45,46-60,61-75,76-90')])
    }

    for sheet_name, (title, fields) in sheets_info.items():
        ws = wb.create_sheet(sheet_name) if sheet_name != 'match_overview' else wb.active
        ws.title = sheet_name
        ws.cell(row=1, column=1, value=f'{title} - 字段说明').font = Font(bold=True, size=14)
        ws.cell(row=3, column=1, value='字段名').font = HEADER_FONT
        ws.cell(row=3, column=1).fill = HEADER_FILL
        ws.cell(row=3, column=2, value='说明').font = HEADER_FONT
        ws.cell(row=3, column=2).fill = HEADER_FILL
        for idx, (fname, desc) in enumerate(fields, 4):
            ws.cell(row=idx, column=1, value=fname).font = NORMAL_FONT
            ws.cell(row=idx, column=2, value=desc).font = NORMAL_FONT
        ws.column_dimensions['A'].width = 25
        ws.column_dimensions['B'].width = 40

    wb.save(filepath)


def export_excel(snapshots_data, mode='training', include_dictionary=True, filename_prefix='',
                 sclass_names=None, date_start=None, date_end=None):
    """
    导出Excel文件
    V2.4.9: 文件名包含联赛和日期信息
    """
    if not snapshots_data:
        raise ValueError("无快照数据可导出")

    now = datetime.now()
    timestamp = now.strftime('%Y%m%d_%H%M%S')
    mode_prefix = 'training' if mode == 'training' else 'prediction'

    if filename_prefix:
        filename = f"{filename_prefix}_{timestamp}.xlsx"
    else:
        parts = [mode_prefix]
        if sclass_names:
            league_str = '+'.join(sclass_names[:3])
            if len(sclass_names) > 3:
                league_str += f'等{len(sclass_names)}个'
            league_str = league_str.replace('/', '_').replace('\\', '_').replace(':', '_')
            parts.append(league_str)
        if date_start and date_end:
            parts.append(date_start.replace('-', ''))
            parts.append(date_end.replace('-', ''))
        elif date_start:
            parts.append(date_start.replace('-', ''))
        elif date_end:
            parts.append(date_end.replace('-', ''))
        parts.append(timestamp)
        filename = '_'.join(parts) + '.xlsx'

    filepath = os.path.join(EXCEL_EXPORT_DIR, filename)

    wb = Workbook()
    ws1 = wb.active
    ws1.title = 'match_overview'
    _gen_match_overview(ws1, snapshots_data, mode)

    ws2 = wb.create_sheet('tech_stats')
    _gen_tech_stats(ws2, snapshots_data, mode)

    ws3 = wb.create_sheet('events')
    _gen_events(ws3, snapshots_data, mode)

    ws4 = wb.create_sheet('player_stats')
    _gen_player_stats(ws4, snapshots_data, mode)

    ws5 = wb.create_sheet('near_matches')
    _gen_near_matches(ws5, snapshots_data, mode)

    ws6 = wb.create_sheet('vs_matches')
    _gen_vs_matches(ws6, snapshots_data, mode)

    ws7 = wb.create_sheet('goal_distribution')
    _gen_goal_distribution(ws7, snapshots_data, mode)

    wb.save(filepath)

    if include_dictionary:
        dict_path = os.path.join(EXCEL_EXPORT_DIR, 'data_dictionary.xlsx')
        _gen_data_dictionary(dict_path)

    return filepath


if __name__ == '__main__':
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from db import init_db, get_fulltime_snapshots_with_match_info
    init_db()
    print("=== 测试训练模式导出 ===")
    snapshots = get_fulltime_snapshots_with_match_info()
    print(f"获取到 {len(snapshots)} 场完场快照")
    if snapshots:
        filepath = export_excel(snapshots, mode='training', include_dictionary=True)
        print(f"Excel已导出: {filepath}")
