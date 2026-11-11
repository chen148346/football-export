"""
足球比赛数据文档分析系统 V2.6.3 - 批量ID导入模块

[V2.5.5] 变更说明：
- 防爬延迟参数改用 config.BATCH_IMPORT_DELAY_MIN/MAX（统一收口）

功能：从txt文件批量导入比赛ID，为每个完场比赛创建快照并生成报告
规则：
1. 每行一个ID
2. 不存在的ID和未完场的ID自动跳过
3. 完场比赛生成快照存入数据库
4. 生成Word报告存储在本地（V2.4.16：不再转换为PDF）
5. 支持进度回调（用于前端进度显示）
6. 防爬优化：随机延迟、随机User-Agent

V2.4.14变更：match_date字段自动填充逻辑版本标识升级（从V2.4.13升级为V2.4.14）
V2.4.16变更：报告格式从PDF改为Word，取消PDF转换步骤
"""
import os
import sys
import json
import time
import random
import re
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import (
    init_db, get_fulltime_snapshot_cached, get_or_create_match,
    create_snapshot, update_match, update_match_fulltime_snapshot
)
from scraper import fetch_match_detail, _fetch, _extract_jsondata, _filter_odds
from config import TITAN007_BASE, get_random_headers, BATCH_IMPORT_DELAY_MIN, BATCH_IMPORT_DELAY_MAX
from report_generator import generate_report


def _infer_year_from_analysis(analysis_json, month, day):
    """
    V2.4.8新增：利用analysis_json中nearMatches的matchTime作为锚点推断年份
    V2.4.10修复：年份推断逻辑修正（+1改为-1）
    V2.4.12修复：年份推断逻辑再次修正（-1改为+1），解决跨年比赛时间计算异常

    算法逻辑：
    1. 从nearMatches获取最近一场比赛的matchTime（Unix时间戳）
    2. 提取其年份Y_recent
    3. 用Y_recent拼接MM-DD得到假设比赛时间
    4. 若假设时间 >= 锚点时间，年份正确（同年）
       若假设时间 < 锚点时间，说明比赛在锚点之后（跨年），年份+1

    参数:
        analysis_json: Analysis页面JSON
        month: HTML中提取的月份（1-12）
        day: HTML中提取的日（1-31）

    返回: 推断的年份（int）
    """
    from datetime import datetime
    import logging
    logger = logging.getLogger(__name__)

    try:
        if not analysis_json or not isinstance(analysis_json, dict):
            raise ValueError("analysis_json为空")

        nm = analysis_json.get('nearMatches', {})
        if not nm:
            raise ValueError("nearMatches为空")

        # 优先用homeMatches，其次awayMatches
        recent_match = None
        for team_key in ['homeMatches', 'awayMatches']:
            team_data = nm.get(team_key, {})
            if isinstance(team_data, dict):
                matches = team_data.get('matches', [])
                if matches:
                    recent_match = matches[0]
                    break

        if not recent_match:
            raise ValueError("nearMatches中无比赛记录")

        # matchTime是Unix时间戳（秒），如 '1782921600'
        match_time_ts = recent_match.get('matchTime', '')
        if not match_time_ts:
            raise ValueError("matchTime字段为空")

        # 转换为datetime
        ts = int(match_time_ts)
        recent_dt = datetime.fromtimestamp(ts)
        Y_recent = recent_dt.year

        # 用Y_recent拼接MM-DD得到假设比赛时间
        try:
            assumed_dt = datetime(Y_recent, month, day)
        except ValueError:
            # 日期无效（如2月30日），降级用当前年份
            raise ValueError(f"无效日期: {Y_recent}-{month}-{day}")

        # V2.4.12修复：年份推断逻辑修正（-1改为+1）
        if assumed_dt >= recent_dt:
            # 假设时间 >= 锚点时间，年份正确（同年）
            print(f"[V2.4.12年份推断] 锚点={recent_dt.strftime('%Y-%m-%d')}, HTML={month:02d}-{day:02d} → 推断年份={Y_recent}（同年）")
            return Y_recent
        else:
            # 假设时间 < 锚点时间，说明比赛在锚点之后（跨年），年份+1
            inferred_year = Y_recent + 1
            print(f"[V2.4.12年份推断] 锚点={recent_dt.strftime('%Y-%m-%d')}, HTML={month:02d}-{day:02d} → 推断年份={inferred_year}（次年+1）")
            return inferred_year

    except Exception as e:
        # 降级：使用当前年份，输出警告
        from match_time_calc import now_beijing
        fallback_year = now_beijing().year
        print(f"[V2.4.12年份推断警告] 降级使用当前年份{fallback_year}，原因: {e}")
        logger.warning(f"[V2.4.12] 年份推断降级: {e}")
        return fallback_year


def _extract_match_info_from_html(html, analysis_json=None):
    """
    V2.0.1 新增：从ShiJian页面HTML中提取完整的比赛信息
    包括：比分、半场比分、联赛名、轮次、天气、比赛时间、排名

    V2.4.8 修复：年份推断逻辑优化
    当HTML中只有MM-DD HH:MM格式时，利用analysis_json中nearMatches的
    matchTime作为锚点推断年份，避免直接用当前年份导致历史数据变未来时间

    参数:
        html: ShiJian页面HTML
        analysis_json: Analysis页面JSON（可选，用于年份推断锚点）

    返回: dict 包含所有比赛信息
    """
    info = {
        'home_score': 0, 'away_score': 0,
        'home_half_score': 0, 'away_half_score': 0,
        'sclass_name': '', 'round_info': '', 'weather': '',
        'match_time': '', 'home_rank': 0, 'away_rank': 0,
    }

    if not html:
        return info

    # 比分
    m = re.search(r'id="homeScore"[^>]*>(\d+)<', html)
    if m:
        info['home_score'] = int(m.group(1))
    m = re.search(r'id="guestScore"[^>]*>(\d+)<', html)
    if m:
        info['away_score'] = int(m.group(1))

    # 半场比分
    m = re.search(r'halfScore[^>]*>\((\d+)-(\d+)\)', html)
    if m:
        info['home_half_score'] = int(m.group(1))
        info['away_half_score'] = int(m.group(2))

    # 联赛信息（含轮次、时间、天气）
    league_m = re.search(r'<div[^>]*class="league"[^>]*>(.*?)</div>', html, re.DOTALL)
    if league_m:
        league_text = re.sub(r'<[^>]+>', '', league_m.group(1))
        # 清理 &nbsp 实体（titan007使用 &nbsp 不带分号的形式）
        league_text = re.sub(r'&nbsp;?', ' ', league_text)
        league_text = re.sub(r'\xa0', ' ', league_text)
        league_text = re.sub(r'\s+', ' ', league_text).strip()

        # 提取联赛名（第一个空格前的内容）
        parts = league_text.split(' ', 1)
        if parts:
            info['sclass_name'] = parts[0].strip()

        # 提取轮次
        round_m = re.search(r'第(\d+)轮', league_text)
        if round_m:
            info['round_info'] = f"第{round_m.group(1)}轮"
        else:
            round_m2 = re.search(r'(资格赛|小组赛|1/8决赛|1/4决赛|半决赛|决赛|附加赛|季后赛)', league_text)
            if round_m2:
                info['round_info'] = round_m2.group(1)

        # 提取天气
        time_m = re.search(r'\d{2}-\d{2}\s+\d{2}:\d{2}\s+(.*)', league_text)
        if time_m:
            info['weather'] = time_m.group(1).strip()

    # 比赛时间提取
    # 方式1: 从 matchTime 变量提取（YYYYMMDDHHMMSS格式）
    m = re.search(r'matchTime\s*=\s*["\'](\d{14})', html)
    if m:
        info['match_time'] = m.group(1)
    else:
        # 方式2: 从联赛div提取 MM-DD HH:MM 格式，结合年份推断
        # 联赛div中的日期格式: "03-09 22:30"
        if league_m:
            date_m = re.search(r'(\d{2})-(\d{2})\s+(\d{2}):(\d{2})', league_text)
            if date_m:
                from datetime import datetime
                mo = int(date_m.group(1))
                d = int(date_m.group(2))
                h = int(date_m.group(3))
                mi = int(date_m.group(4))

                # V2.4.8: 年份推断 - 利用analysis_json中nearMatches作为锚点
                year = _infer_year_from_analysis(analysis_json, mo, d)

                info['match_time'] = f"{year}{mo:02d}{d:02d}{h:02d}{mi:02d}00"

    # 排名（从 document.write("[7]") 中提取）
    # 主队排名（元素ID: homeName）
    home_rank_m = re.search(r'id="homeName".*?document\.write\("\[(\d+)\]"\)', html, re.DOTALL)
    if home_rank_m:
        info['home_rank'] = int(home_rank_m.group(1))
    # 客队排名（元素ID: guestName）
    away_rank_m = re.search(r'id="guestName".*?document\.write\("\[(\d+)\]"\)', html, re.DOTALL)
    if away_rank_m:
        info['away_rank'] = int(away_rank_m.group(1))

    return info


def batch_import_from_file(file_path, progress_callback=None):
    """
    从txt文件批量导入比赛ID并生成报告

    参数:
        file_path - txt文件路径，每行一个比赛ID
        progress_callback - 进度回调函数 callback(current, total, message)

    返回: {
        'total': 总ID数,
        'success': 成功数,
        'skipped_not_exist': 不存在的ID数,
        'skipped_not_finished': 未完场的ID数,
        'skipped_error': 处理出错的ID数,
        'results': [{'id': xxx, 'status': 'success'/'skipped'/'error', 'message': '...'}, ...]
    }
    """
    # 读取文件
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    match_ids = []
    for line in lines:
        line = line.strip()
        if line and line.isdigit():
            match_ids.append(int(line))

    total = len(match_ids)
    print(f"[批量导入] 读取到 {total} 个比赛ID")

    results = []
    success = 0
    skipped_not_exist = 0
    skipped_not_finished = 0
    skipped_error = 0

    def _progress(current, msg):
        if progress_callback:
            progress_callback(current, total, msg)
        print(f"[批量导入] [{current}/{total}] {msg}")

    _progress(0, f"开始处理 {total} 个ID")

    for i, mid in enumerate(match_ids):
        result = {'id': mid, 'status': '', 'message': ''}
        _progress(i, f"处理 ID={mid} ({i+1}/{total})")

        try:
            # 1. 检查本地是否已有完场快照
            snapshot = get_fulltime_snapshot_cached(mid)

            if snapshot and snapshot.get('shijian_json'):
                # 本地已有，直接生成报告
                _progress(i, f"ID={mid} 本地已有快照，直接生成报告")
                report_id, filepath = generate_report(mid, snapshot['id'], 'fulltime')
                result['status'] = 'success'
                result['message'] = f"报告已生成: {os.path.basename(filepath)}"
                success += 1
            else:
                # 2. 本地没有，从网页抓取
                _progress(i, f"ID={mid} 从网页抓取数据...")
                detail = fetch_match_detail(mid)

                if not detail or not detail.get('shijian_json'):
                    result['status'] = 'skipped'
                    result['message'] = 'ID不存在或无法获取数据'
                    skipped_not_exist += 1
                    _progress(i + 1, f"ID={mid} 跳过: 不存在")
                else:
                    sj_json = detail['shijian_json']
                    an_json = detail.get('analysis_json')
                    html = detail.get('shijian_html', '')

                    # 检查比赛状态
                    info = sj_json.get('info', {})
                    state_code = info.get('stateCode', 0)
                    home_name = info.get('homeName', '')
                    away_name = info.get('awayName', '')

                    if state_code != -1:
                        result['status'] = 'skipped'
                        result['message'] = f'未完场(state={state_code})'
                        skipped_not_finished += 1
                        _progress(i + 1, f"ID={mid} 跳过: 未完场")
                    else:
                        # V2.0.1: 从HTML提取完整比赛信息
                        # V2.4.8: 传入analysis_json用于年份推断
                        match_info = _extract_match_info_from_html(html, an_json)

                        # 创建或更新比赛记录（包含完整信息）
                        match = get_or_create_match(mid)
                        match_update = dict(match)
                        match_update['sclass_name'] = match_info['sclass_name'] or match.get('sclass_name', '')
                        match_update['home_team'] = home_name or match.get('home_team', '')
                        match_update['away_team'] = away_name or match.get('away_team', '')
                        match_update['match_time'] = match_info['match_time'] or match.get('match_time', '')
                        match_update['home_rank'] = match_info['home_rank'] or match.get('home_rank', 0)
                        match_update['away_rank'] = match_info['away_rank'] or match.get('away_rank', 0)
                        if match_info['weather']:
                            match_update['weather'] = match_info['weather']
                        if match_info['round_info']:
                            match_update['round_info'] = match_info['round_info']
                        match_update['latest_state_code'] = -1
                        match_update['latest_state_text'] = '完场'
                        match_update['latest_state_display'] = '完场'
                        match_update['latest_home_score'] = match_info['home_score']
                        match_update['latest_away_score'] = match_info['away_score']
                        match_update['latest_home_half_score'] = match_info['home_half_score']
                        match_update['latest_away_half_score'] = match_info['away_half_score']

                        # V2.4.14修复：自动填充match_date字段（从match_time提取）
                        # 根因：_extract_match_info_from_html()只提取match_time不提取match_date，
                        #       导致update_match()时match_date键缺失，数据库中保持NULL
                        # 修复：在update_match前，从match_time前8位提取日期，格式化为YYYY-MM-DD
                        # 防御性编程：检查match_time长度>=8，避免索引越界
                        # 降级策略：如果match_date已有值，不覆盖
                        match_time_val = match_update.get('match_time', '')
                        if match_time_val and len(match_time_val) >= 8 and not match_update.get('match_date'):
                            mt = match_time_val
                            inferred_date = f"{mt[0:4]}-{mt[4:6]}-{mt[6:8]}"
                            match_update['match_date'] = inferred_date
                            print(f"[V2.4.14] 比赛ID={mid} 自动填充match_date={inferred_date}（从match_time提取）")

                        update_match(match_update)

                        # [V2.6.3] 从ShiJian页面提取准确比分，覆盖HTML提取的值
                        batch_home_score = match_info['home_score']
                        batch_away_score = match_info['away_score']
                        batch_home_half_score = match_info['home_half_score']
                        batch_away_half_score = match_info['away_half_score']
                        try:
                            event_list = sj_json.get('events', {}).get('eventList', [])
                            for e in event_list:
                                if e.get('kind') == 'OTHER':
                                    process = e.get('process', '')
                                    mp = e.get('matchProcess', {})
                                    if mp and isinstance(mp, dict):
                                        if process == 'HalfTime':
                                            batch_home_half_score = mp.get('homeScore', batch_home_half_score)
                                            batch_away_half_score = mp.get('guestScore', batch_away_half_score)
                                        elif process == 'FullTime':
                                            batch_home_score = mp.get('homeScore', batch_home_score)
                                            batch_away_score = mp.get('guestScore', batch_away_score)
                        except Exception:
                            pass

                        # 创建快照（包含完整比分信息）
                        snapshot_id = create_snapshot({
                            'match_id': mid,
                            'snapshot_type': 'fulltime',
                            'state_code': -1,
                            'state_text': '完场',
                            'home_score': batch_home_score,
                            'away_score': batch_away_score,
                            'home_half_score': batch_home_half_score,
                            'away_half_score': batch_away_half_score,
                            'elapsed_min': 90,
                            'shijian_json': json.dumps(sj_json, ensure_ascii=False),
                            'analysis_json': json.dumps(an_json, ensure_ascii=False) if an_json else None,
                        })

                        # 更新比赛的完场快照ID
                        update_match_fulltime_snapshot(mid, snapshot_id)

                        # 生成报告
                        _progress(i, f"ID={mid} 生成报告中...")
                        report_id, filepath = generate_report(mid, snapshot_id, 'fulltime')
                        result['status'] = 'success'
                        result['message'] = f"报告已生成: {os.path.basename(filepath)}"
                        success += 1
                        _progress(i + 1, f"ID={mid} 成功")

            # [V2.5.5] 防爬延迟改用 config.BATCH_IMPORT_DELAY_MIN/MAX（统一收口）
            if i < total - 1:  # 最后一个不需要延迟
                delay = random.uniform(BATCH_IMPORT_DELAY_MIN, BATCH_IMPORT_DELAY_MAX)
                _progress(i + 1, f"防爬延迟 {delay:.1f}秒...")
                time.sleep(delay)

        except Exception as e:
            result['status'] = 'error'
            result['message'] = str(e)
            skipped_error += 1
            _progress(i + 1, f"ID={mid} 出错: {e}")

        results.append(result)

    summary = {
        'total': total,
        'success': success,
        'skipped_not_exist': skipped_not_exist,
        'skipped_not_finished': skipped_not_finished,
        'skipped_error': skipped_error,
        'results': results,
    }

    _progress(total, f"完成! 成功{success} 跳过{skipped_not_exist+skipped_not_finished} 出错{skipped_error}")
    return summary


if __name__ == '__main__':
    init_db()

    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    else:
        test_file = '/tmp/test_batch_ids.txt'
        with open(test_file, 'w') as f:
            f.write("2789499\n")
        file_path = test_file

    print(f"=== 批量导入测试: {file_path} ===")
    result = batch_import_from_file(file_path)
    print(f"\n=== 结果 ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))
