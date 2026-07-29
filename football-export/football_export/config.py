"""
config.py - 配置文件
====================
足球比赛数据报表导出模块的配置常量。

包含：数据库路径、完场状态码、odds字段黑名单、技术统计kind映射等。

路径处理说明：
- 所有路径基于模块所在目录的相对路径计算，确保跨平台兼容
- 使用 os.path.join 拼接路径，避免硬编码分隔符
- 输出目录在模块加载时自动创建
- 可通过环境变量 FOOTBALL_DB_PATH / FOOTBALL_EXPORT_DIR 覆盖默认路径
"""

import os

# ============================================================================
# 路径基准（基于本文件所在位置，不依赖当前工作目录）
# ============================================================================

# 模块所在目录: football_export/
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))

# 项目目录（模块的上级目录，即 football-export/）
_SCRIPTS_DIR = os.path.dirname(_MODULE_DIR)

# 项目根目录（scripts/ 的上级目录，用于兼容旧版目录结构）
_PROJECT_ROOT = os.path.dirname(_SCRIPTS_DIR)


def _resolve_project_path(subpath: str) -> str:
    """
    跨平台路径解析：优先在项目目录(_SCRIPTS_DIR)下查找，
    若不存在则回退到项目父目录(_PROJECT_ROOT)。
    
    兼容两种目录结构：
    - 扁平结构：config.ini/upload/download 直接在 football-export/ 下
    - 嵌套结构：config.ini/upload/download 在 football-export/ 的父目录下
    """
    primary = os.path.join(_SCRIPTS_DIR, subpath)
    fallback = os.path.join(_PROJECT_ROOT, subpath)
    # 如果主路径已存在（文件/目录），优先使用
    if os.path.exists(primary):
        return primary
    # 如果回退路径存在，使用回退
    if os.path.exists(fallback):
        return fallback
    # 都不存在时，默认使用主路径（将在需要时自动创建）
    return primary

# ============================================================================
# 数据库配置
# ============================================================================

# 数据库文件路径（可通过环境变量覆盖）
# 默认查找顺序：环境变量 -> 项目根目录/upload/下的.db文件 -> 项目根目录/football.db
def _find_default_db():
    """
    自动查找默认数据库文件。
    
    查找顺序（跨平台兼容）：
    1. 环境变量 FOOTBALL_DB_PATH
    2. 项目目录/upload/*.db（优先）或 父目录/upload/*.db
    3. 项目目录/football.db（优先）或 父目录/football.db
    """
    # 1. 环境变量指定
    env_path = os.environ.get("FOOTBALL_DB_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
    
    # 2. upload/目录下的.db文件（优先项目目录，其次父目录）
    for base_dir in (_SCRIPTS_DIR, _PROJECT_ROOT):
        upload_dir = os.path.join(base_dir, "upload")
        if os.path.isdir(upload_dir):
            for fname in sorted(os.listdir(upload_dir)):
                if fname.endswith(".db") and fname != "test_football.db":
                    return os.path.join(upload_dir, fname)
    
    # 3. football.db（优先项目目录，其次父目录）
    for base_dir in (_SCRIPTS_DIR, _PROJECT_ROOT):
        db_path = os.path.join(base_dir, "football.db")
        if os.path.exists(db_path):
            return db_path
    
    # 都不存在，默认项目目录下
    return os.path.join(_SCRIPTS_DIR, "football.db")

DEFAULT_DB_PATH = _find_default_db()

# 导出文件输出目录
# 默认为项目目录下的 download/ 目录（跨平台兼容）
OUTPUT_DIR = os.environ.get(
    "FOOTBALL_EXPORT_DIR",
    _resolve_project_path("download")
)

# 确保输出目录存在（自动创建）
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ============================================================================
# 比赛状态码
# ============================================================================

# 完场状态码（仅导出完场比赛）
STATE_CODE_FINISHED = -1

# 状态码含义映射（供参考）
STATE_CODE_MAP = {
    -1: "完场",
    0: "未开始",
    1: "上半场",
    2: "中场",
    3: "下半场",
    4: "加时",
    -10: "取消",
    -11: "待定",
    -12: "腰斩",
    -13: "中断",
    -14: "推迟",
}

# 快照类型：完场快照
SNAPSHOT_TYPE_FULLTIME = "fulltime"

# ============================================================================
# 时区配置（北京时间 UTC+8）
# ============================================================================

BEIJING_TZ_OFFSET_HOURS = 8

# ============================================================================
# Odds（赔率）字段黑名单
# ============================================================================
# 根据需求文档和交接说明，以下字段属于赔率/盘口相关数据，严禁导出。
# scraper.py 抓取时已执行 _filter_odds() 过滤，但导出时仍需二次保险过滤。

# 需要完全过滤的键名（精确匹配）
ODDS_KEY_BLACKLIST = {
    # 文档明确列出的赔率字段
    "oddsRecords",        # 赔率记录
    "cornerOdds",         # 角球赔率
    "leaguePanlu",        # 盘口
    "letgoal",            # 让球
    "letGoal",
    "ou",                 # 欧赔
    "Ou",
    "OU",
    # 博彩公司相关
    "companyList",        # 博彩公司列表
    "companyList2",       # 博彩公司列表2
    "company",
    "CompanyName",
    "companyId",
    "company2",
    # 同盘口/同大小球比赛
    "sameHandicapMatches",  # 同盘口比赛
    "sameOuMatches",        # 同大小球比赛
    # vsMatches 中的 matches2（通常是盘口相关交锋记录）
    "matches2",
}

# 键名中包含以下子串的也视为赔率字段（模糊匹配，不区分大小写）
ODDS_KEY_SUBSTRINGS = (
    "odds",
    "panlu",
    "letgoal",
    "handicap",
)

# ============================================================================
# 技术统计 kind 中文名映射（供参考，实际以JSON中的name字段为准）
# ============================================================================

TECH_STAT_KIND_MAP = {
    "CORNER": "角球",
    "HALF_CORNER": "半场角球",
    "YELLOW": "黄牌",
    "RED": "红牌",
    "SHOOT": "射门",
    "TARGET": "射正",
    "ATTACK": "进攻",
    "DANGEROUS_ATTACK": "危险进攻",
    "OFFTARGET": "射门不中",
    "BLOCKED": "射门被挡",
    "FREEKICT": "任意球",
    "FOULS": "犯规",
    "OFFSIDE": "越位",
    "HEADER": "头球",
    "HEADER_SUCEESS": "头球成功",
    "SAVE": "救球",
    "CONTROL_PERCENT": "控球率",
    "HALF_CONTROL_PERCENT": "半场控球率",
    "PASSBALL": "传球",
    "PASSBALL_SUCCESS_PERCENT": "传球成功率",
    "TACKLE": "铲球",
    "SUBST": "换人",
    "DRIBBLES": "过人",
    "THROWINS": "界外球",
    "HIT_WOODWORK": "中柱",
    "STEAL_SUCCESS": "成功抢断",
    "HOLDUP": "阻截",
    "SUCCESS_CROSS": "成功传中",
    "ASSISTS": "助攻",
    "LONG_PASS": "长传",
    "KICK_OFF_FIRST": "先开球",
    "FIRST_YELLOW": "第一张黄牌",
    "LAST_YELLOW": "最后一张黄牌",
    "FIRST_SUBST": "第一个换人",
    "LAST_SUBST": "最后一个换人",
    "FIRST_CORNER": "第一个角球",
    "LAST_CORNER": "最后一个角球",
    "FIRST_OFFSIDE": "第一个越位",
    "LAST_OFFSIDE": "最后越位",
    "GOAL": "进球",
}

# ============================================================================
# 事件类型映射
# ============================================================================

# shijian_json.events.eventList 中的事件特有字段 -> 中文事件类型
EVENT_TYPE_MAP = {
    "goalIn": "进球",
    "yellowCard": "黄牌",
    "redCard": "红牌",
    "changePlayer": "换人",
    "videoReferee": "视频裁判",
    "penaltyKick": "点球",
    "matchProcess": "比赛节点",
}

# ============================================================================
# 进失球分布时间段
# ============================================================================

# jsq.jsqList 中的6个时间段
GOAL_DIST_TIME_PERIODS = ["1-15", "16-30", "31-45", "46-60", "61-75", "76-90"]

# jsq.jsqList 中的 count 类型
GOAL_DIST_COUNT_TYPES = ["Count_30", "Count_50"]

# ============================================================================
# 导出文件名格式
# ============================================================================

# 文件名格式：training_{联赛}_{开始日期}_{结束日期}_{时间戳}.xlsx
# 如果有多联赛，用 "multi" 代替
EXPORT_FILENAME_TEMPLATE = "training_{league}_{start_date}_{end_date}_{timestamp}.xlsx"

# ============================================================================
# V1.2 新增配置 - Sheet选择与文件命名规则
# ============================================================================

# V1.2: Sheet标识 -> Sheet名称映射（用于前端复选框与后端Sheet构建器的对应）
SHEET_ID_MAP = {
    "match":  "match_overview",
    "tech":   "tech_stats",
    "events": "events",
    "player": "player_stats",
    "near":   "near_matches",
    "vs":     "vs_matches",
    "dist":   "goal_distribution",
}

# V1.2: Sheet标识 -> 中文名映射（用于前端显示）
SHEET_DISPLAY_NAME = {
    "match":  "比赛",
    "tech":   "指标",
    "events": "事件",
    "player": "球员",
    "near":   "近绩",
    "vs":     "往绩",
    "dist":   "分布",
}

# V1.2: Sheet标识 -> 文件名后缀首字母映射（用于文件名后缀生成）
# 全选时后缀为 "all"，部分选择时用各Sheet首字母拼接
SHEET_SUFFIX_LETTER = {
    "match":  "m",
    "tech":   "t",
    "events": "e",
    "player": "p",
    "near":   "n",
    "vs":     "v",
    "dist":   "d",
}

# V1.2: 所有Sheet标识的有序列表（用于文件名后缀按固定顺序拼接）
ALL_SHEET_IDS = ["match", "tech", "events", "player", "near", "vs", "dist"]

# V1.2: 新文件名格式
# 格式：{导出日期}_{赛事名称}_{开始日期}_{结束日期}_{后缀}.xlsx
# 导出日期：yymmdd（如260708）
# 赛事名称：多赛事用-连接（文件名中/替换为-）
# 后缀：全选为all，部分选择用Sheet首字母拼接（如metv）
V12_FILENAME_TEMPLATE = "{export_date}_{league}_{start_date}_{end_date}_{suffix}.xlsx"

# V1.2: 默认单文件最大比赛数（分片导出用）
DEFAULT_MAX_MATCHES_PER_FILE = 50

# V1.2: 文件名中非法字符替换映射（安全处理）
ILLEGAL_CHAR_REPLACE = {
    "/": "-",
    "\\": "-",
    ":": "-",
    "*": "-",
    "?": "-",
    '"': "-",
    "<": "-",
    ">": "-",
    "|": "-",
}

# ============================================================================
# V1.4 新增配置 - 5个新Sheet、HA键映射、curLeagueStat映射、config.ini支持
# ============================================================================

# V1.4: 新增5个Sheet标识 -> Sheet名称映射
V14_NEW_SHEET_MAP = {
    "first_half":  "first_half_tech_stats",    # 上半场技术统计
    "second_half": "second_half_tech_stats",   # 下半场技术统计
    "league_rank": "league_rank_stats",        # 联赛排名统计
    "half_full":   "half_full_stats",          # 近两赛季半场/全场统计
    "detail_evt":  "detailed_events",          # 详细事件
}

# V1.4: 新增5个Sheet标识 -> 中文名映射
V14_NEW_SHEET_DISPLAY = {
    "first_half":  "上半场统计",
    "second_half": "下半场统计",
    "league_rank": "联赛排名",
    "half_full":   "半全统计",
    "detail_evt":  "详细事件",
}

# V1.4: 新增5个Sheet标识 -> 文件名后缀首字母
V14_NEW_SHEET_SUFFIX = {
    "first_half":  "f",
    "second_half": "s",
    "league_rank": "l",
    "half_full":   "h",
    "detail_evt":  "d",
}

# V1.4: 所有Sheet标识的有序列表（V1.2的7个 + V1.4的5个）
ALL_SHEET_IDS_V14 = [
    "match", "tech", "events", "player", "near", "vs", "dist",  # V1.0的7个
    "first_half", "second_half", "league_rank", "half_full", "detail_evt",  # V1.4的5个
]

# V1.4: 完整的Sheet标识 -> Sheet名称映射（12个）
SHEET_ID_MAP_V14 = {
    # V1.0的7个
    "match":  "match_overview",
    "tech":   "tech_stats",
    "events": "events",
    "player": "player_stats",
    "near":   "near_matches",
    "vs":     "vs_matches",
    "dist":   "goal_distribution",
    # V1.4的5个
    "first_half":  "first_half_tech_stats",
    "second_half": "second_half_tech_stats",
    "league_rank": "league_rank_stats",
    "half_full":   "half_full_stats",
    "detail_evt":  "detailed_events",
}

# V1.4: 完整的Sheet标识 -> 后缀字母映射（12个）
SHEET_SUFFIX_LETTER_V14 = {
    "match":  "m", "tech": "t", "events": "e", "player": "p",
    "near": "n", "vs": "v", "dist": "d",
    "first_half": "f", "second_half": "s", "league_rank": "l",
    "half_full": "h", "detail_evt": "x",  # detail_evt用x避免与dist的d冲突
}

# V1.4: HA键 -> 中文描述映射（9种半场/全场组合）
HA_TYPE_MAP = {
    "HA33": "半胜/全胜",
    "HA31": "半胜/全平",
    "HA30": "半胜/全负",
    "HA13": "半平/全胜",
    "HA11": "半平/全平",
    "HA10": "半平/全负",
    "HA03": "半负/全胜",
    "HA01": "半负/全平",
    "HA00": "半负/全负",
}

# V1.4: curLeagueStat的kind -> 中文名映射（10项）
CUR_LEAGUE_STAT_KIND_MAP = {
    "Rank":      "排名",
    "WinCount":  "获胜场次",
    "LoseCount": "输球场次",
    "DrawCount": "平局场次",
    "GoalAvg":   "平均进球",
    "LossAvg":   "平均失球",
    "Goal2":     "净胜2球以上",
    "Goal1":     "净胜1球",
    "Loss2":     "净输2球以上",
    "Loss1":     "净输1球",
}

# V1.4: curLeagueStat中需要转float的kind（其余转int）
CUR_LEAGUE_STAT_FLOAT_KINDS = {"GoalAvg", "LossAvg"}

# V1.4: techStat中需要百分比转换的kind（value是int，需/100转小数）
TECH_STAT_PERCENT_KINDS = {
    "CONTROL_PERCENT",
    "HALF_CONTROL_PERCENT",
    "PASSBALL_SUCCESS_PERCENT",
}

# V1.4: config.ini配置文件路径（跨平台兼容，优先项目目录）
CONFIG_INI_PATH = os.environ.get(
    "FOOTBALL_CONFIG_INI",
    _resolve_project_path("config.ini")
)

# ============================================================================
# V1.5 新增配置 - 文件命名规范升级、比分字段分离
# ============================================================================

# V1.5: 新文件名格式
# 格式：{时间戳}_{联赛}_{开始日期}_{结束日期}_{类型}_{字段选择}.xlsx
# - 时间戳：yymmddhhmm（精确到分钟，如2607141530）
# - 联赛：单联赛用中文名，多联赛统一用Multi
# - 开始/结束日期：yymmdd格式（如260710）
# - 类型：FT(完场)/HT(半场)/PR(进行中/自定义分钟区间)
# - 字段选择：all(12个全选) / part(没有全选12个就是part)
V15_FILENAME_TEMPLATE = "{timestamp}_{league}_{start_date}_{end_date}_{snapshot_type}_{field_select}.xlsx"

# V1.5: 快照业务类型映射
# FT=完场, HT=半场, PR=进行中/自定义分钟区间
V15_SNAPSHOT_TYPE_MAP = {
    "fulltime": "FT",
    "halftime": "HT",
    "custom": "PR",
}

# V1.5: 完整的12个Sheet标识列表（V1.4的7个 + V1.4新增的5个）
ALL_SHEET_IDS_V15 = [
    "match", "tech", "events", "player", "near", "vs", "dist",  # V1.0的7个
    "first_half", "second_half", "league_rank", "half_full", "detail_evt",  # V1.4的5个
]

# V1.5: 比分字段分离配置
# 原home_score/away_score拆分为：
# - current_home_score/current_away_score: 当前时点比分（特征，赛中可用）
# - label_home_score/label_away_score: 完场比分（标签，仅完场快照有值）
V15_SCORE_FIELD_RENAME = {
    "home_score": "current_home_score",
    "away_score": "current_away_score",
}

# V1.5: 百分比字段小数化配置（P0级Bug修复）
# techStat中需要百分比转换的kind（value是int，需/100转小数）
# V1.4已有3项，V1.5补充遗漏的百分比字段
V15_TECH_STAT_PERCENT_KINDS = {
    "CONTROL_PERCENT",           # 控球率（V1.4已有）
    "HALF_CONTROL_PERCENT",      # 半场控球率（V1.4已有）
    "PASSBALL_SUCCESS_PERCENT",  # 传球成功率（V1.4已有）
    "PASS_SUC_RATE",             # 传球成功率（部分联赛用此kind）
    "CROSS_SUC_RATE",            # 传中成功率
    "TACKLE_SUC_RATE",           # 铲球成功率
    "DRIBBLE_SUC_RATE",          # 过人成功率
    "SAVE_RATE",                 # 扑救成功率
}

# V1.5: player_stats中需要百分比转换的infoKind
# 球员技术统计中的百分比字段（infoValue是str如"76%"，需去%后/100转小数）
V15_PLAYER_PERCENT_KINDS = {
    "PassSucceeRatio",    # 传球成功率
    "CrossSucceeRatio",   # 传中成功率（如有）
    "TackleSucceeRatio",  # 铲球成功率（如有）
}


# ============================================================================
# V1.4: config.ini 配置文件读取
# ============================================================================

def _load_config_ini():
    """
    V1.4新增 - 读取config.ini配置文件，覆盖默认DB路径和输出目录。
    
    config.ini格式：
        [paths]
        db_path = /path/to/football.db
        output_dir = /path/to/output
    """
    import configparser
    global DEFAULT_DB_PATH, OUTPUT_DIR
    
    ini_path = CONFIG_INI_PATH
    if not os.path.exists(ini_path):
        return  # 配置文件不存在，使用默认值
    
    parser = configparser.ConfigParser()
    parser.read(ini_path, encoding='utf-8')
    
    if parser.has_section('paths'):
        if parser.has_option('paths', 'db_path'):
            ini_db = parser.get('paths', 'db_path').strip()
            if ini_db and os.path.exists(ini_db):
                DEFAULT_DB_PATH = ini_db
        if parser.has_option('paths', 'output_dir'):
            ini_dir = parser.get('paths', 'output_dir').strip()
            if ini_dir:
                OUTPUT_DIR = ini_dir
                os.makedirs(OUTPUT_DIR, exist_ok=True)

# V1.4: 模块加载时自动读取config.ini
_load_config_ini()
