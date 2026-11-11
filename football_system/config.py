"""
足球比赛数据文档分析系统 V2.6.3 - 配置文件

[V2.5.5] 版本号同步清洗
- 统一版本号为 V2.5.5
- 防爬延迟参数统一收口到 config.py
- min60窗口统一为 57-63（以 monitor.py 为准）

历史变更说明：
- V2.0: 移除自动刷新功能（所有刷新必须手动触发）；移除自动报告生成；新增主客队近期赛况报告功能；新增批量ID导入功能
"""
import os
import random

# 项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 数据库路径
DB_PATH = os.path.join(BASE_DIR, 'football.db')

# 报告输出目录
REPORT_DIR = os.path.join(BASE_DIR, 'download')

# 确保目录存在
os.makedirs(REPORT_DIR, exist_ok=True)

# titan007 请求配置
TITAN007_BASE = 'https://m.titan007.com'

# 防屏蔽：多 User-Agent 轮换
USER_AGENTS = [
    'Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 14_8 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (Linux; Android 12; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.120 Mobile Safari/537.36',
    'Mozilla/5.0 (Linux; Android 11; Redmi Note 10 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.131 Mobile Safari/537.36',
    'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.5359.128 Mobile Safari/537.36',
    'Mozilla/5.0 (iPad; CPU OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1',
]


def get_random_headers():
    """获取随机请求头（防屏蔽）"""
    return {
        'User-Agent': random.choice(USER_AGENTS),
        'Referer': 'https://m.titan007.com/',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9',
    }


# [V2.5.3] HTTP请求参数优化（监控拥堵场景）
# 超时从20秒缩短为10秒：避免单次请求卡住整个监控轮询
# 重试从3次降为2次：失败快速放弃，让下一轮轮询接管
REQUEST_TIMEOUT = 10
REQUEST_RETRIES = 2
# 请求间随机延迟（0.5-2.0秒）
REQUEST_DELAY_MIN = 0.5
REQUEST_DELAY_MAX = 2.0

# [V2.5.5] 防爬延迟参数统一收口（替代 monitor.py 和 batch_import.py 中的硬编码）
# 监控场景防爬延迟（原 monitor.py CRAWL_DELAY_MIN/MAX）
MONITOR_CRAWL_DELAY_MIN = 1
MONITOR_CRAWL_DELAY_MAX = 2
# 批量导入场景防爬延迟（原 batch_import.py 第372行 random.uniform(2,5)）
BATCH_IMPORT_DELAY_MIN = 2
BATCH_IMPORT_DELAY_MAX = 5

# V2.0: 移除自动刷新间隔配置（所有刷新必须手动触发）
# SCHEDULE_REFRESH_INTERVAL 已移除
# SNAPSHOT_CHECK_INTERVAL 已移除

# [V2.5.7] 任务1：定时自动刷新配置
# 每天北京时间凌晨4:00和下午16:00各自动刷新一次
# 格式：['HH:MM', 'HH:MM']，支持多个时间点
AUTO_REFRESH_TIMES = ['04:00', '16:00']
# 定时刷新时区（北京时间）
AUTO_REFRESH_TIMEZONE = 'Asia/Shanghai'

# [Deprecated] [V2.5.5] 以下配置已废弃，不再使用。
# 手动报告的min60窗口已统一为 57-63（见 scheduler.py 和 app.py 中的硬编码）。
# 监控报告的min60窗口以 monitor.py MONITOR_NODES 中的 57-63 为准。
# 保留此配置仅作为历史记录，请勿在新代码中引用。
MIN60_SNAPSHOT_LOWER = 58
MIN60_SNAPSHOT_UPPER = 65

# 比赛状态码
STATE_CODES = {
    -1: '完场',
    0: '未开始',
    1: '上半场',
    2: '中场',
    3: '下半场',
    4: '加时',
    -10: '取消',
    -11: '待定',
    -12: '腰斩',
    -13: '中断',
    -14: '推迟',
}

# V2.0: 报告生成规则简化
# 所有报告必须手动生成，不再有 first_seen_state 跳过逻辑
# 但保留 first_seen_state 字段用于记录首次发现状态

# odds 相关字段（在所有层面过滤，不存储、不展示、不在文档中体现）
# [V2.5.5] odds 加入 ODDS_MATCH_FIELDS，过滤清单总数为10个（7个JSON层 + 3个Match层）
ODDS_JSON_KEYS = {
    'oddsRecords', 'cornerOdds', 'leaguePanlu', 'theSamePanKou',
    'multiLeaguePanLu', 'multiSamePanKou', 'xinShuiRecommend',
}

ODDS_MATCH_FIELDS = {
    'letgoal', 'ou', 'odds',
}

# [V2.5.4] 比赛列表排序优先级（数字越小越靠前）
# 优化：上半场(1)、中场(2)、下半场(3)、加时(4)统一归为"进行中"大类（优先级0）
# 修复V2.5.3问题：中场(2)原优先级为1，导致排在下半场(3)后面
STATE_SORT_PRIORITY = {
    1: 0,   # 上半场（进行中）
    2: 0,   # 中场（进行中）—— [V2.5.4] 从1改为0，归入进行中大类
    3: 0,   # 下半场（进行中）
    4: 0,   # 加时（进行中）
    0: 2,   # 未开始
    -1: 3,  # 完场
    -13: 4, # 中断
    -14: 4, # 推迟
    -11: 4, # 待定
    -12: 4, # 腰斩
    -10: 4, # 取消
}

# V2.0: 近期赛况报告配置
TEAM_RECENT_MATCH_COUNT = 10  # 近期比赛数量（不足10场则取实际数量）

# V2.4.9: LibreOffice路径配置（用于Word转PDF）
# 优先级：环境变量LIBREOFFICE_PATH > 以下配置 > 系统PATH
# Windows默认路径示例: r'C:\Program Files\LibreOffice\program\soffice.exe'
# Linux默认路径示例: '/usr/bin/libreoffice' 或 '/usr/bin/soffice'
LIBREOFFICE_PATH = os.environ.get('LIBREOFFICE_PATH', '')

# 自动检测常见安装路径（如果环境变量未设置）
if not LIBREOFFICE_PATH:
    _common_paths = [
        # Windows
        r'C:\Program Files\LibreOffice\program\soffice.exe',
        r'C:\Program Files (x86)\LibreOffice\program\soffice.exe',
        # Linux/Mac
        '/usr/bin/libreoffice',
        '/usr/bin/soffice',
        '/opt/libreoffice/program/soffice',
        '/Applications/LibreOffice.app/Contents/MacOS/soffice',
    ]
    for p in _common_paths:
        if os.path.exists(p):
            LIBREOFFICE_PATH = p
            break
