"""
足球比赛数据文档分析系统 V2.6.3 - 实时比赛状态计算模块
逆向工程 titan007 的 showMatchState JavaScript 函数，Python 1:1 复刻

核心原理（已修正时区处理）：
1. titan007 的所有时间（服务器时间、比赛时间、headStartTime）均为北京时间(UTC+8)
2. 本系统统一使用北京时间进行所有时间计算
3. 比赛列表的 match_time 字段是北京时间，如 "20260701160000" = 7月1日16:00北京
4. /txt/time.shtml 返回北京时间
5. ShiJian 页面的 headStartTime 也是北京时间

showMatchState 逻辑（来自 titan007 Schedule.js）：
  state=1 (上半场): df = (当前北京时间 - headStartTime) / 60
                    df<=0 → "1'", df<=45 → "df'", else → "45+(df-45)'"
  state=3 (下半场): df = (当前北京时间 - headStartTime) / 60 + 46
                    df<=46 → "46'", df<90 → "df'", else → "90+(df-90)'"
  state=2 (中场):   "中场"
  state=4 (加时):   "加时"
  state=0 (未开始): "VS"
  state=-1 (完场):  "完场"
  其他状态: 对应中文文本
"""
import re
import time
import threading
import requests
from datetime import datetime as dt_class, timedelta, timezone

from config import get_random_headers, REQUEST_TIMEOUT

# 北京时区 UTC+8
BEIJING_TZ = timezone(timedelta(hours=8))


def now_beijing():
    """获取当前北京时间（带时区信息的datetime对象）"""
    return dt_class.now(BEIJING_TZ)


def now_beijing_naive():
    """获取当前北京时间（无时区信息的naive datetime，用于与naive比较）"""
    return dt_class.now(BEIJING_TZ).replace(tzinfo=None)


def beijing_date_str():
    """获取当前北京日期字符串 YYYY-MM-DD（用于抓取赛程）"""
    return now_beijing().strftime('%Y-%m-%d')


def parse_beijing_time(time_str, fmt='%Y%m%d%H%M%S'):
    """
    将时间字符串解析为北京时间datetime对象（naive，但代表北京时间）
    titan007的所有时间字符串都是北京时间
    """
    try:
        return dt_class.strptime(time_str[:len(time_str)], fmt)
    except (ValueError, TypeError):
        return None


# ==================== 服务器时间获取 ====================

_server_time_cache = {'value': None, 'timestamp': 0}
_server_time_lock = threading.Lock()
_SERVER_TIME_CACHE_TTL = 300  # 服务器时间缓存5分钟


def fetch_server_time():
    """
    从 titan007 获取服务器时间（北京时间）
    接口: https://m.titan007.com/txt/time.shtml
    返回格式: YYYYMMDDHHMMSS (UTF-8 BOM)
    返回: naive datetime 对象（代表北京时间），失败返回 None
    """
    try:
        r = requests.get(
            'https://m.titan007.com/txt/time.shtml',
            headers=get_random_headers(),
            timeout=REQUEST_TIMEOUT
        )
        text = r.content.decode('utf-8-sig').strip()
        if len(text) >= 14 and text.isdigit():
            return dt_class.strptime(text[:14], '%Y%m%d%H%M%S')
    except Exception:
        pass
    return None


def get_server_time():
    """
    获取titan007服务器时间（北京时间），带缓存
    优先使用缓存，缓存过期后重新获取
    如果获取失败，回退到本地计算的北京时间
    """
    with _server_time_lock:
        now_ts = time.time()
        if _server_time_cache['value'] is not None:
            if now_ts - _server_time_cache['timestamp'] < _SERVER_TIME_CACHE_TTL:
                return _server_time_cache['value']

    server_time = fetch_server_time()
    if server_time is not None:
        with _server_time_lock:
            _server_time_cache['value'] = server_time
            _server_time_cache['timestamp'] = now_ts
        return server_time

    # 获取失败，使用本地北京时间
    return now_beijing_naive()


# ==================== headStartTime 提取 ====================

def extract_head_start_time(html):
    """
    从 ShiJian 页面 HTML 中提取 headStartTime（北京时间）
    格式: headStartTime = new Date("2026/7/1 2:52:00")
    返回: naive datetime 对象（代表北京时间），失败返回 None
    """
    if not html:
        return None
    m = re.search(r'headStartTime\s*=\s*new Date\("([^"]+)"\)', html)
    if not m:
        return None
    date_str = m.group(1)
    # 手动解析（处理非零填充的日期，如 "2026/7/1 2:52:00"）
    try:
        parts = re.match(r'(\d+)/(\d+)/(\d+)\s+(\d+):(\d+):(\d+)', date_str)
        if parts:
            y, mo, d, h, mi, s = [int(x) for x in parts.groups()]
            return dt_class(y, mo, d, h, mi, s)
    except Exception:
        pass
    return None


# ==================== showMatchState 核心计算 ====================

def show_match_state(state_code, head_start_time=None, server_time=None):
    """
    Python 1:1 复刻 titan007 的 showMatchState JavaScript 函数
    计算比赛实时状态文本（含分钟数）

    参数:
        state_code: 比赛状态码
        head_start_time: 当前半场开始时间（naive datetime，北京时间）
        server_time: 当前北京时间（naive datetime），None则自动获取

    返回: 状态文本字符串，如 "23'", "45+2'", "67'", "90+1'", "中场", "完场" 等
    """
    state_text_map = {
        4: '加时', 3: '下半场', 2: '中场', 1: '上半场', 0: 'VS',
        -1: '完场', -10: '取消', -11: '待定', -12: '腰斩',
        -13: '中断', -14: '推迟', 5: '点球',
    }
    ms = state_text_map.get(state_code, '')

    # 仅对上半场和下半场计算实时分钟数
    if state_code == 1:
        # 上半场
        if head_start_time is None:
            return ms
        if server_time is None:
            server_time = get_server_time()

        df = int((server_time - head_start_time).total_seconds() / 60)

        if df <= 0:
            ms = "1'"
        elif df <= 45:
            ms = f"{df}'"
        else:
            ms = f"45+{df - 45}'"

    elif state_code == 3:
        # 下半场
        if head_start_time is None:
            return ms
        if server_time is None:
            server_time = get_server_time()

        df = int((server_time - head_start_time).total_seconds() / 60) + 46

        if df <= 46:
            ms = "46'"
        elif df < 90:
            ms = f"{df}'"
        else:
            ms = f"90+{df - 90}'"

    return ms


def calc_elapsed_min(state_code, head_start_time=None, server_time=None):
    """
    计算比赛已进行的分钟数（整数）
    返回: 分钟数（int），未进行中的比赛返回0
    """
    if state_code == 1:
        if head_start_time is None:
            return 0
        if server_time is None:
            server_time = get_server_time()
        df = int((server_time - head_start_time).total_seconds() / 60)
        return max(1, min(df, 45))

    elif state_code == 3:
        if head_start_time is None:
            return 46
        if server_time is None:
            server_time = get_server_time()
        df = int((server_time - head_start_time).total_seconds() / 60) + 46
        return max(46, min(df, 120))

    elif state_code == 4:
        return 91

    return 0


# ==================== 简化版：用比赛时间估算 ====================

def estimate_elapsed_min(state_code, match_time_str, server_time=None):
    """
    使用比赛计划时间估算已进行分钟数（不需要 headStartTime）
    精度较低（不考虑比赛延迟），适用于比赛列表快速展示

    参数:
        state_code: 状态码
        match_time_str: 比赛时间字符串（北京时间），如 "20260701020000"
        server_time: 当前北京时间（naive datetime），None则自动获取

    返回: 估算分钟数（int）
    """
    if state_code not in (1, 3, 4):
        return 0
    if not match_time_str or len(match_time_str) < 14:
        return 0

    kickoff = parse_beijing_time(match_time_str[:14], '%Y%m%d%H%M%S')
    if kickoff is None:
        return 0

    if server_time is None:
        server_time = get_server_time()

    # 两个都是naive datetime，代表北京时间，直接相减
    elapsed_min = int((server_time - kickoff).total_seconds() / 60)

    if state_code == 1:
        return max(1, min(elapsed_min, 45))
    elif state_code == 3:
        # 下半场: 减去中场休息(15分钟)
        return max(46, min(elapsed_min - 15, 120))
    elif state_code == 4:
        return 91

    return 0


# ==================== 综合接口 ====================

def get_realtime_status(match_id, state_code, match_time_str, html=None, server_time=None):
    """
    获取比赛的实时状态（综合接口）

    返回: {
        'state_code': 状态码,
        'state_text': 状态文本（含分钟数，如 "23'" 或 "中场"）,
        'elapsed_min': 已进行分钟数（int）,
    }
    """
    if server_time is None:
        server_time = get_server_time()

    # 尝试从HTML提取headStartTime
    head_start_time = None
    if html:
        head_start_time = extract_head_start_time(html)

    # 如果没有headStartTime，用match_time_str估算
    if head_start_time is None:
        elapsed = estimate_elapsed_min(state_code, match_time_str, server_time)
        state_text = show_match_state(state_code, None, server_time)
        # 对于进行中的比赛，用估算的分钟数生成显示文本
        if state_code in (1, 3) and elapsed > 0:
            if state_code == 1:
                if elapsed <= 45:
                    state_text = f"{elapsed}'"
                else:
                    state_text = f"45+{elapsed - 45}'"
            elif state_code == 3:
                if elapsed <= 90:
                    state_text = f"{elapsed}'"
                else:
                    state_text = f"90+{elapsed - 90}'"
        return {
            'state_code': state_code,
            'state_text': state_text,
            'elapsed_min': elapsed,
        }

    # 有headStartTime，精确计算
    state_text = show_match_state(state_code, head_start_time, server_time)
    elapsed = calc_elapsed_min(state_code, head_start_time, server_time)

    return {
        'state_code': state_code,
        'state_text': state_text,
        'elapsed_min': elapsed,
    }


# ==================== 兼容旧接口 ====================

def calc_difftime():
    """
    兼容旧接口 - 已废弃，保留以防外部调用
    返回0（不再需要时差计算，直接使用北京时间）
    """
    return 0


if __name__ == '__main__':
    print("=== 测试北京时间获取 ===")
    print(f"当前北京时间: {now_beijing_naive()}")
    print(f"北京日期: {beijing_date_str()}")
    print(f"titan007服务器时间: {get_server_time()}")

    print("\n=== 测试状态计算 ===")
    st = get_server_time()
    print(f"完场: {show_match_state(-1, server_time=st)}")
    print(f"中场: {show_match_state(2, server_time=st)}")
    print(f"未开始: {show_match_state(0, server_time=st)}")

    # 测试进行中比赛
    print("\n=== 测试进行中比赛 ===")
    import requests
    HEADERS = get_random_headers()
    # 找一场进行中的比赛
    url = f'https://m.titan007.com/Schedule.htm?date={beijing_date_str()}'
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.encoding = 'utf-8'
    m = re.search(r'scheduleDataStr\s*=\s*"([^"]*)"', r.text)
    sched = m.group(1) if m else ''
    records = sched.split('!')
    for rec in records:
        fields = rec.split('^')
        if len(fields) > 10:
            state = int(fields[2]) if fields[2].lstrip('-').isdigit() else 0
            if state in (1, 3):
                mid = fields[0]
                home = fields[5]
                away = fields[6]
                mtime = fields[3]
                print(f"\n进行中比赛: ID={mid} {home} vs {away} state={state} time={mtime}")
                # 估算
                elapsed = estimate_elapsed_min(state, mtime, st)
                print(f"  估算已进行: {elapsed}分钟")
                # 获取headStartTime精确计算
                r2 = requests.get(f'https://m.titan007.com/Analy/ShiJian/{mid}.htm', headers=HEADERS, timeout=15)
                r2.encoding = 'utf-8'
                hst = extract_head_start_time(r2.text)
                print(f"  headStartTime: {hst}")
                if hst:
                    result = get_realtime_status(mid, state, mtime, r2.text, st)
                    print(f"  实时状态: {result}")
                break
