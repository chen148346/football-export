"""
足球比赛数据文档分析系统 V2.6.3 - 主客队近期赛况报告生成模块

[V2.5.5] 变更说明：
- 清理 _convert_to_pdf 死代码导入

功能：为指定比赛的主队和客队分别生成近期10场比赛报告
报告内容：只保留原报告第一部分前6节（到球员技术统计）
报告格式：Word
命名规则：队伍名称_yymmdd_10（10代表最多包含10场比赛，实际不足则填实际数）

数据来源：
1. 从当前比赛的 Analysis 页面 nearMatches 获取近期比赛ID列表
2. 对每个近期比赛ID，优先从本地数据库获取完场快照
3. 如果本地没有，则从 titan007 抓取并保存到数据库
"""
import os
import json
from datetime import datetime
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

from config import REPORT_DIR, TEAM_RECENT_MATCH_COUNT
from db import (
    get_fulltime_snapshot_cached, get_or_create_match, create_snapshot,
    update_match, get_match
)
from scraper import fetch_match_detail, fetch_recent_match_ids
from report_generator import (
    _add_heading, _add_para, _gen_match_info, _gen_important_events,
    _gen_detailed_events, _gen_tech_stats, _gen_lineup, _gen_player_tech
)
# [V2.5.5] 已删除 _convert_to_pdf 导入（死代码，V2.4.16起不再使用PDF转换）


def generate_team_recent_reports(match_id):
    """
    为主客队分别生成近期赛况报告

    参数: match_id - 当前比赛ID

    返回: {
        'home_team': 主队名称,
        'away_team': 客队名称,
        'home_report': 主队报告文件路径（或None）,
        'away_report': 客队报告文件路径（或None）,
        'home_count': 主队报告包含的比赛数,
        'away_count': 客队报告包含的比赛数,
    }
    """
    # 1. 获取主客队近期比赛ID列表
    print(f"[近期赛况] 获取比赛 {match_id} 的主客队近期比赛列表...")
    recent_info = fetch_recent_match_ids(match_id, TEAM_RECENT_MATCH_COUNT)
    if not recent_info:
        raise ValueError(f"无法获取比赛 {match_id} 的近期比赛数据")

    home_team = recent_info['home_team']
    away_team = recent_info['away_team']
    home_ids = recent_info['home_match_ids']
    away_ids = recent_info['away_match_ids']

    print(f"[近期赛况] 主队 {home_team}: {len(home_ids)} 场近期比赛")
    print(f"[近期赛况] 客队 {away_team}: {len(away_ids)} 场近期比赛")

    # 2. 生成主队报告
    home_result = _generate_single_team_report(match_id, home_team, home_ids)

    # 3. 生成客队报告
    away_result = _generate_single_team_report(match_id, away_team, away_ids)

    return {
        'home_team': home_team,
        'away_team': away_team,
        'home_report': home_result['filepath'],
        'away_report': away_result['filepath'],
        'home_count': home_result['count'],
        'away_count': away_result['count'],
    }


def _generate_single_team_report(current_match_id, team_name, match_ids):
    """
    为单个队伍生成近期赛况报告

    参数:
        current_match_id: 当前比赛ID（用于获取队伍信息）
        team_name: 队伍名称
        match_ids: 近期比赛ID列表

    返回: {'filepath': 报告路径, 'count': 实际包含的比赛数}
    """
    if not match_ids:
        print(f"[近期赛况] {team_name} 无近期比赛数据")
        return {'filepath': None, 'count': 0}

    # 获取每场比赛的快照数据
    snapshots = []
    for i, mid in enumerate(match_ids):
        print(f"[近期赛况] 处理 {team_name} 第 {i+1}/{len(match_ids)} 场: ID={mid}")
        snapshot = _get_or_fetch_snapshot(mid)
        if snapshot:
            snapshots.append(snapshot)
        else:
            print(f"[近期赛况]   跳过（未完场或不存在）")

    if not snapshots:
        print(f"[近期赛况] {team_name} 无可用的完场快照")
        return {'filepath': None, 'count': 0}

    # 生成报告文档
    doc = _build_team_report_doc(team_name, snapshots, len(match_ids))

    # V2.4.16: 报告统一使用Word格式，不再转换为PDF
    now = datetime.now()
    date_str = now.strftime('%y%m%d')
    count = len(snapshots)
    filename = f"{team_name}_{date_str}_{count}.docx"
    # 清理文件名非法字符
    filename = ''.join(c for c in filename if c not in '<>:"/\\|?*')

    docx_filepath = os.path.join(REPORT_DIR, filename)
    doc.save(docx_filepath)

    print(f"[近期赛况] {team_name} 报告已生成: {filename} (含{count}场比赛)")
    return {'filepath': docx_filepath, 'count': count}


def _get_or_fetch_snapshot(match_id):
    """
    V2.0 核心功能：获取比赛快照
    1. 先查本地数据库（完场快照缓存）
    2. 如果本地没有，从网页抓取并保存

    返回: snapshot dict 或 None（未完场或不存在）
    """
    # 1. 先查本地数据库
    snapshot = get_fulltime_snapshot_cached(match_id)
    if snapshot and snapshot.get('shijian_json') and snapshot.get('analysis_json'):
        print(f"[近期赛况]   命中本地缓存")
        return snapshot

    # 2. 本地没有，从网页抓取
    try:
        detail = fetch_match_detail(match_id)
        if not detail or not detail.get('shijian_json'):
            return None

        sj_json = detail['shijian_json']
        an_json = detail.get('analysis_json')
        html = detail.get('shijian_html', '')

        # 从 ShiJian 页面获取比赛状态
        info = sj_json.get('info', {})
        state_code = info.get('stateCode', 0)
        home_name = info.get('homeName', '')
        away_name = info.get('awayName', '')

        # 只处理完场比赛（stateCode == -1）
        if state_code != -1:
            print(f"[近期赛况]   未完场(state={state_code})，跳过")
            return None

        # V2.0.2: 从HTML提取完整的比赛信息（比分、联赛名、排名等）
        from batch_import import _extract_match_info_from_html
        match_info = _extract_match_info_from_html(html)

        # 获取或创建比赛记录
        match = get_or_create_match(match_id, home_team=home_name, away_team=away_name)

        # 更新比赛信息（使用从HTML提取的完整数据）
        match_update = dict(match)
        match_update['home_team'] = home_name
        match_update['away_team'] = away_name
        if match_info.get('sclass_name'):
            match_update['sclass_name'] = match_info['sclass_name']
        if match_info.get('round_info'):
            match_update['round_info'] = match_info['round_info']
        if match_info.get('weather'):
            match_update['weather'] = match_info['weather']
        if match_info.get('match_time'):
            match_update['match_time'] = match_info['match_time']
        if match_info.get('home_rank'):
            match_update['home_rank'] = match_info['home_rank']
        if match_info.get('away_rank'):
            match_update['away_rank'] = match_info['away_rank']
        match_update['latest_state_code'] = -1
        match_update['latest_state_text'] = '完场'
        match_update['latest_state_display'] = '完场'
        match_update['latest_home_score'] = match_info.get('home_score', 0)
        match_update['latest_away_score'] = match_info.get('away_score', 0)
        match_update['latest_home_half_score'] = match_info.get('home_half_score', 0)
        match_update['latest_away_half_score'] = match_info.get('away_half_score', 0)

        update_match(match_update)

        # 创建快照（使用正确的比分和半场比分）
        from db import create_snapshot, update_match_fulltime_snapshot
        snapshot_id = create_snapshot({
            'match_id': match_id,
            'snapshot_type': 'fulltime',
            'state_code': -1,
            'state_text': '完场',
            'home_score': match_info.get('home_score', 0),
            'away_score': match_info.get('away_score', 0),
            'home_half_score': match_info.get('home_half_score', 0),
            'away_half_score': match_info.get('away_half_score', 0),
            'elapsed_min': 90,
            'shijian_json': json.dumps(sj_json, ensure_ascii=False),
            'analysis_json': json.dumps(an_json, ensure_ascii=False) if an_json else None,
        })
        update_match_fulltime_snapshot(match_id, snapshot_id)

        # 重新获取完整快照
        snapshot = get_fulltime_snapshot_cached(match_id)
        print(f"[近期赛况]   已抓取并缓存")
        return snapshot

    except Exception as e:
        print(f"[近期赛况]   抓取失败: {e}")
        return None


def _build_team_report_doc(team_name, snapshots, total_count):
    """
    构建队伍近期赛况报告文档
    只包含原报告第一部分前6节：比赛基本信息、重要事件、详细事件、技术统计、首发阵容、球员技术统计
    """
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

    # 封面标题
    _add_heading(doc, f"{team_name} 近期赛况报告", level=1)
    _add_para(doc, f"包含 {len(snapshots)} 场比赛", bold=True, size=12, align='center', color=(100, 100, 100))
    _add_para(doc, f"报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
              size=9, align='center', color=(128, 128, 128))
    doc.add_paragraph()

    # 为每场比赛生成报告（只含前6节）
    for i, snapshot in enumerate(snapshots):
        match = get_match(snapshot['match_id'])
        if not match:
            continue

        sj_json = json.loads(snapshot['shijian_json']) if snapshot.get('shijian_json') else {}
        an_json = json.loads(snapshot['analysis_json']) if snapshot.get('analysis_json') else {}

        # 比赛标题
        _add_heading(doc, f"第 {i+1} 场: {match.get('sclass_name', '')} {match.get('home_team', '')} vs {match.get('away_team', '')}", level=1)

        # 只生成前6节
        _gen_match_info(doc, match, snapshot)
        _gen_important_events(doc, sj_json)
        _gen_detailed_events(doc, sj_json)
        _gen_tech_stats(doc, sj_json, snapshot)
        _gen_lineup(doc, sj_json, match)
        _gen_player_tech(doc, sj_json, match)

        doc.add_paragraph()  # 场次间空行

    return doc


if __name__ == '__main__':
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from db import init_db
    init_db()

    # 测试
    test_id = 2789499
    print(f"=== 测试近期赛况报告生成 (比赛ID: {test_id}) ===")
    result = generate_team_recent_reports(test_id)
    print(f"\n=== 生成结果 ===")
    print(f"主队: {result['home_team']}")
    print(f"  报告: {result['home_report']}")
    print(f"  场次: {result['home_count']}")
    print(f"客队: {result['away_team']}")
    print(f"  报告: {result['away_report']}")
    print(f"  场次: {result['away_count']}")
