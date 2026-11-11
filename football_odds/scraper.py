"""
足球比赛数据文档分析系统 V2.6.3 - 数据抓取模块
负责从 titan007 抓取比赛列表、ShiJian页面、Analysis页面
所有 odds 相关数据在抓取阶段即被过滤（[V2.5.5] 过滤清单统一为10个字段）
集成 match_time_calc 实现实时比赛状态计算
防屏蔽：随机User-Agent、随机延迟、重试机制
"""
import re
import json
import time
import random
import logging
import requests
from datetime import datetime, timedelta
from config import (
    TITAN007_BASE, REQUEST_TIMEOUT,
    REQUEST_RETRIES, REQUEST_DELAY_MIN, REQUEST_DELAY_MAX,
    STATE_CODES, get_random_headers
)
from match_time_calc import (
    calc_difftime, show_match_state, extract_head_start_time,
    estimate_elapsed_min, beijing_date_str, get_server_time, now_beijing_naive
)

logger = logging.getLogger(__name__)


def _fetch(url, retries=REQUEST_RETRIES):
    """带重试和防屏蔽的HTTP请求"""
    last_err = None
    for i in range(retries):
        try:
            # 每次请求使用随机请求头（防屏蔽）
            headers = get_random_headers()
            r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            r.encoding = 'utf-8'
            # 随机延迟（防屏蔽）
            delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
            time.sleep(delay)
            return r.text
        except Exception as e:
            last_err = e
            time.sleep(1)
    raise last_err


def _extract_jsondata(html):
    """从HTML中提取 jsonData 变量"""
    patterns = [
        r'var\s+jsonData\s*=\s*(\{.*?\});\s*</script>',
        r'var\s+jsonData\s*=\s*(\{.*?\});\s*$',
        r'jsonData\s*=\s*(\{.*?\});\s*</script>',
    ]
    for p in patterns:
        m = re.search(p, html, re.DOTALL | re.MULTILINE)
        if m:
            return m.group(1)
    return None


# [football_odds] 本系统保留全部 odds 数据，原 _filter_odds 过滤逻辑已移除。
# 被保留的数据包括：
#   - ShiJian/Analysis jsonData 中的 7 个 odds key: oddsRecords / cornerOdds /
#     leaguePanlu / theSamePanKou / multiLeaguePanLu / multiSamePanKou / xinShuiRecommend
#   - 赛程列表 match 中的 odds 字段: [23]亚盘主水 [24]亚盘让球 [25]亚盘客水
#     [27]大小球盘口 [28]大小结果（见 fetch_schedule_list 解析段）


def fetch_schedule_list(date_str=None):
    """
    抓取比赛列表
    date_str: 日期字符串 YYYY-MM-DD（北京时间），默认获取当前比赛日的完整赛程

    V2.0.3 修复：titan007的即时比分页面显示的是"当前比赛日"的所有比赛
    比赛日定义：中午12点到次日中午12点
    Schedule.htm（无参数）只返回当天0点开始的比赛，会遗漏昨天12点后到今天0点的比赛

    修复方案：同时获取昨天和今天的比赛，合并去重
    这样可以确保与titan007"即时比分"页面显示的比赛完全一致

    返回: [{match_id, sclass_id, sclass_name, sclass_color, state_code, state_text,
           match_time, match_date, home_team, away_team, home_rank, away_rank,
           home_score, away_score, home_half_score, away_half_score,
           home_red, away_red, home_yellow, away_yellow, elapsed_min}, ...]
    """
    from match_time_calc import now_beijing
    from datetime import timedelta

    if date_str:
        # 指定日期，只获取该日期的比赛
        all_matches = _fetch_schedule_for_date(date_str)
    else:
        # V2.0.3: 获取昨天和今天的比赛，合并去重
        # 这样可以覆盖完整的"比赛日"（中午12点到次日中午12点）
        beijing_now = now_beijing()
        today_str = beijing_now.strftime('%Y-%m-%d')
        yesterday_str = (beijing_now - timedelta(days=1)).strftime('%Y-%m-%d')

        today_matches = _fetch_schedule_for_date(today_str)
        yesterday_matches = _fetch_schedule_for_date(yesterday_str)

        # 合并去重（以比赛ID为key）
        seen_ids = set()
        all_matches = []
        for m in today_matches + yesterday_matches:
            if m['id'] not in seen_ids:
                seen_ids.add(m['id'])
                all_matches.append(m)

    return all_matches


def fetch_schedule_status_batch(match_ids):
    """
    [V2.5.3] 批量获取比赛状态（监控拥堵优化核心）
    ============================================================
    一次抓取完整赛程列表，从中提取指定match_id的状态信息。
    避免refresh_match_status每场比赛都重复抓取整个赛程列表。

    参数: match_ids - 需要查询状态的match_id列表
    返回: dict {match_id: match_status_dict, ...}
          match_status_dict包含: latest_state_code, latest_state_text,
          latest_state_display, latest_home_score, latest_away_score等
    """
    if not match_ids:
        return {}

    # 一次抓取完整赛程列表（昨天+今天合并）
    try:
        all_matches = fetch_schedule_list()
    except Exception as e:
        logger.error(f"[V2.5.3] 批量状态查询抓取赛程失败: {e}")
        return {}

    # 构建match_id到状态的映射
    id_set = set(match_ids)
    result = {}
    for m in all_matches:
        if m['id'] in id_set:
            result[m['id']] = m

    return result


def _fetch_schedule_for_date(date_str):
    """
    获取指定日期的比赛列表（内部函数）
    date_str: 日期字符串 YYYY-MM-DD（北京时间）
    """
    url = f'{TITAN007_BASE}/Schedule.htm?date={date_str}'
    html = _fetch(url)

    # 提取 scheduleDataStr
    m = re.search(r'scheduleDataStr\s*=\s*"([^"]*)"', html)
    schedule_str = m.group(1) if m else ''

    # 提取 sclassDataStr
    m2 = re.search(r'sclassDataStr\s*=\s*"([^"]*)"', html)
    sclass_str = m2.group(1) if m2 else ''

    # 解析联赛信息
    # sclass 格式: sclassName^sclassID^...^sclassColor^...  用 ! 分隔
    sclass_map = {}
    for part in sclass_str.split('$'):
        for entry in part.split('!'):
            if not entry:
                continue
            fields = entry.split('^')
            if len(fields) >= 2:
                sname = fields[0]
                sid = fields[1]
                sclass_map[sid] = {
                    'sclass_id': int(sid) if sid.isdigit() else 0,
                    'sclass_name': sname,
                    'sclass_color': fields[4] if len(fields) > 4 else '',
                }

    # 解析比赛列表
    # 字段顺序: [0]match_id [1]sclass_id [2]state_code [3]match_time [4]match_time2
    #          [5]home_team [6]away_team [7]home_score [8]away_score
    #          [9]home_half_score [10]away_half_score [11]home_red [12]away_red
    #          [13]home_yellow [14]away_yellow [15]? [16]caiPiaoHao [17]?
    #          [18]isZhenRong [19]home_rank [20]away_rank [21]cupExplain [22]liveTv
    #          [23]亚盘主水 [24]亚盘让球 [25]亚盘客水 [26]isHighTv
    #          [27]大小球盘口 [28]大小结果(大/小/走) [29]待定
    #          [football_odds] 以上 odds 字段全部解析保留
    matches = []

    # 获取 titan007 服务器时间（北京时间），用于实时状态计算
    server_time = get_server_time()

    # V2.0.4: 对于进行中的比赛，需要从ShiJian页面获取headStartTime（实际开球时间）
    # 因为计划开赛时间(match_time_str)可能与实际开球时间有偏差
    # 先收集所有进行中的比赛ID
    live_match_ids = []
    parsed_records = []
    for rec in schedule_str.split('!'):
        if not rec:
            continue
        fields = rec.split('^')
        if len(fields) < 22:
            continue
        parsed_records.append(fields)
        state_code = int(fields[2]) if fields[2].lstrip('-').isdigit() else 0
        if state_code in (1, 3):  # 上半场或下半场
            live_match_ids.append(int(fields[0]))

    # 批量获取进行中比赛的headStartTime
    head_start_times = {}
    if live_match_ids:
        for mid in live_match_ids:
            try:
                html = _fetch(f'{TITAN007_BASE}/Analy/ShiJian/{mid}.htm')
                hst = extract_head_start_time(html)
                if hst:
                    head_start_times[mid] = hst
            except Exception:
                pass  # 获取失败则使用计划时间

    for fields in parsed_records:

        try:
            match_id = int(fields[0])
            sclass_id = fields[1]
            state_code = int(fields[2]) if fields[2].lstrip('-').isdigit() else 0
            match_time_str = fields[3]  # YYYYMMDDHHMMSS (北京时间)

            # 解析比赛时间（北京时间）
            match_dt = None
            match_date = ''
            if len(match_time_str) >= 14:
                try:
                    match_dt = datetime.strptime(match_time_str[:14], '%Y%m%d%H%M%S')
                    match_date = match_dt.strftime('%Y-%m-%d')
                except ValueError:
                    pass

            # V2.0.4: 使用headStartTime（实际开球时间）计算实时分钟数
            # 如果有headStartTime，用论文中的公式精确计算
            # 否则用estimate_elapsed_min估算（使用计划开赛时间）
            head_start_time = head_start_times.get(match_id)
            if head_start_time and state_code in (1, 3):
                # 使用论文中的showMatchState公式
                df = int((server_time - head_start_time).total_seconds() / 60)
                if state_code == 1:  # 上半场
                    if df <= 0:
                        elapsed_min = 1
                    elif df <= 45:
                        elapsed_min = df
                    else:
                        elapsed_min = df  # 补时也显示
                elif state_code == 3:  # 下半场
                    df = df + 46
                    if df <= 46:
                        elapsed_min = 46
                    elif df < 90:
                        elapsed_min = df
                    else:
                        elapsed_min = df  # 补时也显示
            else:
                # 没有headStartTime，用计划时间估算
                elapsed_min = estimate_elapsed_min(state_code, match_time_str, server_time)

            # 生成状态显示文本
            if state_code in (1, 3, 4) and elapsed_min > 0:
                if state_code == 1:  # 上半场
                    if elapsed_min <= 45:
                        state_display = f"{elapsed_min}'"
                    else:
                        state_display = f"45+{elapsed_min - 45}'"
                elif state_code == 3:  # 下半场
                    if elapsed_min <= 90:
                        state_display = f"{elapsed_min}'"
                    else:
                        state_display = f"90+{elapsed_min - 90}'"
                else:  # 加时
                    state_display = f"{elapsed_min}'"
            else:
                state_display = STATE_CODES.get(state_code, '未知')

            sclass_info = sclass_map.get(sclass_id, {})

            def safe_int(v):
                try:
                    return int(v)
                except (ValueError, TypeError):
                    return 0

            def safe_float(v):
                try:
                    return float(v)
                except (ValueError, TypeError):
                    return None

            # [football_odds] 赛程 odds 字段（存在才取值，防越界）
            asian_home = safe_float(fields[23]) if len(fields) > 23 else None
            asian_letgoal = safe_float(fields[24]) if len(fields) > 24 else None
            asian_away = safe_float(fields[25]) if len(fields) > 25 else None
            ou_line = safe_float(fields[27]) if len(fields) > 27 else None
            ou_result = fields[28].strip() if len(fields) > 28 else ''

            matches.append({
                'id': match_id,
                'sclass_id': sclass_info.get('sclass_id', 0),
                'sclass_name': sclass_info.get('sclass_name', ''),
                'sclass_color': sclass_info.get('sclass_color', ''),
                'match_time': match_time_str,
                'match_date': match_date,
                'home_team': fields[5],
                'away_team': fields[6],
                'home_rank': safe_int(fields[19]) if len(fields) > 19 else 0,
                'away_rank': safe_int(fields[20]) if len(fields) > 20 else 0,
                'latest_state_code': state_code,
                'latest_state_text': STATE_CODES.get(state_code, '未知'),
                'latest_state_display': state_display,
                'latest_home_score': safe_int(fields[7]),
                'latest_away_score': safe_int(fields[8]),
                'latest_home_half_score': safe_int(fields[9]),
                'latest_away_half_score': safe_int(fields[10]),
                'latest_home_red': safe_int(fields[11]),
                'latest_away_red': safe_int(fields[12]),
                'latest_home_yellow': safe_int(fields[13]),
                'latest_away_yellow': safe_int(fields[14]),
                'latest_elapsed_min': elapsed_min,
                'weather': '',
                'round_info': '',
                'is_neutrality': 0,
                # [football_odds] 赛程阶段赔率（亚盘 + 大小球）
                'asian_home': asian_home,
                'asian_letgoal': asian_letgoal,
                'asian_away': asian_away,
                'ou_line': ou_line,
                'ou_result': ou_result,
            })
        except (ValueError, IndexError):
            continue

    return matches


def fetch_shijian_page(match_id):
    """
    抓取 ShiJian 页面
    返回: (html, json_data) 或 (html, None)
    json_data 已过滤 odds 字段
    """
    url = f'{TITAN007_BASE}/Analy/ShiJian/{match_id}.htm'
    html = _fetch(url)

    # 从HTML提取天气和轮次信息
    weather = ''
    round_info = ''

    # 天气和轮次在 div class="league" 中
    # 格式: 英超&nbsp第38轮&nbsp05-24 23:00&nbsp多云 19℃～20℃
    league_match = re.search(r'<div[^>]*class="league"[^>]*>(.*?)</div>', html, re.DOTALL)
    if league_match:
        # 替换 &nbsp; 为普通空格，去除HTML标签
        league_text = re.sub(r'<[^>]+>', '', league_match.group(1))
        league_text = league_text.replace('&nbsp;', ' ').replace('\u00a0', ' ').strip()
        # 规范化空白
        league_text = re.sub(r'\s+', ' ', league_text)

        # 提取轮次
        round_m = re.search(r'第(\d+)轮', league_text)
        if round_m:
            round_info = f'第{round_m.group(1)}轮'
        else:
            # 有些比赛显示"资格赛"等
            round_m2 = re.search(r'(资格赛|小组赛|1\/8决赛|1\/4决赛|半决赛|决赛|附加赛|季后赛)', league_text)
            if round_m2:
                round_info = round_m2.group(1)

        # 提取天气：在日期时间之后的部分
        # 格式: 联赛名 轮次 MM-DD HH:MM 天气温度
        # 时间后面的所有内容就是天气信息
        time_m = re.search(r'\d{2}-\d{2}\s+\d{2}:\d{2}\s+(.*)', league_text)
        if time_m:
            weather = time_m.group(1).strip()
        else:
            # 备选：匹配天气关键词到行尾
            weather_m = re.search(
                r'((?:晴|多云|阴|雨|雪|雾|雷|冰雹|大风|间中有云|局部有雨|零星雷雨|'
                r'阵雨|小雨|中雨|大雨|暴雨|小雪|中雪|大雪|浮尘|扬沙|沙尘暴).*)',
                league_text
            )
            if weather_m:
                weather = weather_m.group(1).strip()

    # 提取 jsonData
    js_str = _extract_jsondata(html)
    json_data = None
    if js_str:
        try:
            json_data = json.loads(js_str)
            # [football_odds] 保留完整 jsonData（含 oddsRecords/cornerOdds 等 odds 数据）
        except json.JSONDecodeError:
            pass

    # 将天气和轮次信息附加到返回数据中
    return html, json_data, weather, round_info


def fetch_analysis_page(match_id):
    """
    抓取 Analysis 页面
    返回: json_data（已过滤 odds 字段）或 None
    """
    url = f'{TITAN007_BASE}/analy/Analysis/{match_id}.htm'
    html = _fetch(url)

    js_str = _extract_jsondata(html)
    if js_str:
        try:
            json_data = json.loads(js_str)
            # [football_odds] 保留完整 jsonData（含 leaguePanlu/theSamePanKou 等 odds 数据）
            return json_data
        except json.JSONDecodeError:
            pass
    return None


def fetch_match_detail(match_id):
    """
    抓取比赛详情（ShiJian + Analysis）
    返回: {
        'shijian_html': html,
        'shijian_json': json_data,
        'analysis_json': json_data,
        'weather': weather,
        'round_info': round_info,
    }
    """
    html, sj_json, weather, round_info = fetch_shijian_page(match_id)
    an_json = fetch_analysis_page(match_id)

    return {
        'shijian_html': html,
        'shijian_json': sj_json,
        'analysis_json': an_json,
        'weather': weather,
        'round_info': round_info,
    }


def fetch_recent_match_ids(match_id, count=10):
    """
    V2.0 新增：获取主客队近期比赛ID列表
    从 Analysis 页面的 nearMatches 数据中提取

    参数:
        match_id: 当前比赛ID
        count: 最多获取的场次（不足则返回实际数量）

    返回: {
        'home_team': 主队名称,
        'away_team': 客队名称,
        'home_match_ids': [主队近期比赛ID列表],
        'away_match_ids': [客队近期比赛ID列表],
    }
    """
    an_json = fetch_analysis_page(match_id)
    if not an_json:
        return None

    nm = an_json.get('nearMatches', {})
    if not nm:
        return None

    home_data = nm.get('homeMatches', {})
    away_data = nm.get('awayMatches', {})

    home_matches = home_data.get('matches', []) if isinstance(home_data, dict) else []
    away_matches = away_data.get('matches', []) if isinstance(away_data, dict) else []

    # 提取比赛ID（按时间倒序，最近的在前）
    home_ids = [m.get('id') for m in home_matches if m.get('id')][:count]
    away_ids = [m.get('id') for m in away_matches if m.get('id')][:count]

    home_team = home_data.get('teamName', '') if isinstance(home_data, dict) else ''
    away_team = away_data.get('teamName', '') if isinstance(away_data, dict) else ''

    return {
        'home_team': home_team,
        'away_team': away_team,
        'home_match_ids': home_ids,
        'away_match_ids': away_ids,
    }


if __name__ == '__main__':
    # 测试
    print("=== 测试比赛列表抓取 ===")
    matches = fetch_schedule_list()
    print(f"获取到 {len(matches)} 场比赛")
    for m in matches[:5]:
        print(f"  {m['id']} {m['sclass_name']} {m['home_team']} vs {m['away_team']} "
              f"状态={m['latest_state_text']} 比分={m['latest_home_score']}-{m['latest_away_score']}")

    print("\n=== 测试ShiJian页面抓取 ===")
    if matches:
        test_id = matches[0]['id']
        html, sj_json, weather, round_info = fetch_shijian_page(test_id)
        print(f"比赛ID: {test_id}")
        print(f"天气: {weather}")
        print(f"轮次: {round_info}")
        if sj_json:
            print(f"ShiJian JSON keys: {list(sj_json.keys())}")
