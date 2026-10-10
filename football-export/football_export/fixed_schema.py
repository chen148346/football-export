"""
fixed_schema.py - 固定表头导出 Schema 配置
=============================================
为"固定表头导出"功能提供统一的、简体中文的固定字段清单。

背景与设计要点：
1. 8 个 Sheet 表头固定，不随比赛内容动态变化。
2. 同一统计项在数据库中存在"双编码"：
   - 英文键（老数据）：CORNER, SHOOT, TARGET, ...
   - 数字码（新数据）：50(禁区内射球), 51(禁区外射球), ... 60(解围) ...
   导出时必须把两种编码归一到一个中文列。
3. 全部字段统一使用简体中文字段名。
4. 覆盖率原则（基于有效完场扫描）：常见字段进固定表头，罕见字段不纳入。
"""

from collections import OrderedDict

# ============================================================================
# 1. 统计项：数字码 → 简体中文名（新数据源）
# ============================================================================
# 依据 VPS 全量扫描（--valid，26730 场）得出的数字 kind 映射。
DIGIT_KIND_CN = {
    "50": "禁区内射球",
    "51": "禁区外射球",
    "52": "预期进球(xG)",
    "53": "运动战预期进球",
    "54": "定位球预期进球",
    "55": "非点球预期进球",
    "56": "射正预期进球",
    "57": "得分机会",
    "58": "错失得分机会",
    "59": "对方禁区触球",
    "60": "解围",
    "61": "地面对抗成功",
    "62": "横传",
    "63": "争顶成功",
    "64": "1对1成功",
}

# ============================================================================
# 2. 统计项：英文键 → 简体中文名（老数据源，含拼写变体归一）
# ============================================================================
EN_KIND_CN = {
    "CORNER": "角球",
    "HALF_CORNER": "半场角球",
    "YELLOW": "黄牌",
    "GOLD": "黄牌",
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
    "HEADER_SUCCESS": "头球成功",
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
    # ---- 数字码对应的英文键（同一统计项的另一套编码）----
    "CLEARANCES": "解围",
    "SHOOT_INSIDE": "禁区内射球",
    "SHOOT_OUTSIDE": "禁区外射球",
    "DUELS_WON": "1对1成功",
    "EXPECTED_GOALS": "预期进球(xG)",
    "AERIALDUELS_WON": "争顶成功",
    "GROUNDDUELSWON": "地面对抗成功",
    "TIOBX": "对方禁区触球",
    "XGOT": "射正预期进球",
    "BIG_CHANCES": "得分机会",
    "BIG_CHANCES_MISSED": "错失得分机会",
    "ACCURATECROSSES": "横传",
    "XGNON_PENAlTY": "非点球预期进球",
    "XGOPEN_PlAY": "运动战预期进球",
    "XGSET_PlAY": "定位球预期进球",
}

# 合并为统一 kind → 中文名 映射（英文键优先，数字码补充）
KIND_CN = {}
KIND_CN.update(EN_KIND_CN)
for k, v in DIGIT_KIND_CN.items():
    KIND_CN.setdefault(k, v)


def kind_to_cn(kind: str) -> str:
    """任意 kind（英文键/数字码）→ 简体中文名；未收录则原样返回。"""
    if not kind:
        return ""
    return KIND_CN.get(str(kind).strip(), str(kind))


# ============================================================================
# 3. 指标 / 上下半场统计：固定统计项清单（中文名 → 各 kind 候选）
# ============================================================================
# 覆盖率原则（有效完场）：≥25% 纳入固定表头；同一中文名兼容英文键与数字码。
# 结构：中文名 -> (发生该统计项时写入的主/客取值应处理的候选 kind 列表)

STAT_CANDIDATES = {
    # 主队/客队取 home/away 的原始值，统一转数字字符串
}

# 每类指标的"中文名 -> 全部候选 kind"（含双编码）
FIXED_STAT_KINDS = OrderedDict()
for _cn in [
    # 按覆盖率从高到低（英文键主力 + 数字码同项合并后 ≥25%）
    "角球", "射门", "射正", "射门不中", "危险进攻", "进攻", "控球率",
    "半场控球率", "半场角球", "黄牌", "犯规", "任意球", "救球", "传球",
    "阻截", "界外球", "铲球", "传球成功率", "过人", "越位", "长传",
    "成功抢断", "射门被挡", "成功传中", "助攻", "头球",
    # 数字码为主（覆盖率 0.26~0.35）
    "解围", "禁区内射球", "禁区外射球", "1对1成功", "预期进球(xG)",
    "争顶成功", "地面对抗成功", "对方禁区触球", "射正预期进球", "得分机会",
    "错失得分机会", "头球成功", "横传", "中柱", "非点球预期进球",
    "运动战预期进球", "定位球预期进球",
]:
    candidates = [k for k, cn in KIND_CN.items() if cn == _cn]
    if candidates:
        FIXED_STAT_KINDS[_cn] = candidates

# 指标 / 上下半场通用（上下半场统计项集合从 FIXED_STAT_KINDS 复用）
TECH_FIXED_CN = list(FIXED_STAT_KINDS.keys())
FIRST_HALF_FIXED_CN = list(TECH_FIXED_CN)
SECOND_HALF_FIXED_CN = list(TECH_FIXED_CN)

# ============================================================================
# 4. 联赛排名固定字段（结构化，10 项全保留）
# ============================================================================
# 中文名 -> kind
LEAGUE_RANK_FIXED = OrderedDict([
    ("排名", "Rank"),
    ("获胜场次", "WinCount"),
    ("输球场次", "LoseCount"),
    ("平局场次", "DrawCount"),
    ("平均进球", "GoalAvg"),
    ("平均失球", "LossAvg"),
    ("净胜2球以上", "Goal2"),
    ("净胜1球", "Goal1"),
    ("净输2球以上", "Loss2"),
    ("净输1球", "Loss1"),
])

# 联赛排名需要转 float 的 kind
LEAGUE_RANK_FLOAT_KINDS = {"GoalAvg", "LossAvg"}

# ============================================================================
# 5. 详细事件固定类型（简体中文，按主流保留）
# ============================================================================
# 事件 kind（英文，来自 shijian_json.eventTxt.EventTxtLives）→ 中文
EVENT_KIND_CN = {
    "Goal": "进球",
    "Shot": "射门",
    "Corner": "角球",
    "ChangePlayer": "换人",
    "Yellow_Card": "黄牌",
    "RedCard": "红牌",
    "Offside": "越位",
    "Start": "开球",
    "Half_end": "半场结束",
    "End": "完场",
}
# 固定保留的事件类型顺序
DETAIL_EVENT_FIXED = list(EVENT_KIND_CN.keys())

# 完整事件中文表（含未纳入固定的类型，供参考/扩展）
EVENT_KIND_CN_FULL = dict(EVENT_KIND_CN)
EVENT_KIND_CN_FULL.update({
    "VAR": "视频回放",
    "Penalty": "点球",
    "PenaltyIn": "点球罚进",
    "PenaltyFailure": "点球罚失",
    "PenaltyOut": "点球射飞",
    "OwnGoal": "乌龙球",
    "DoubleYellow": "两黄变红",
})

# ============================================================================
# 6. 比赛 Sheet 固定列（matches 表 + shijian/analysis 提取）
# ============================================================================
MATCH_FIXED_HEADERS = [
    "match_id", "sclass_name", "match_date", "match_time",
    "home_team", "away_team",
    "home_rank", "away_rank",
    "home_score", "away_score",
    "home_half_score", "away_half_score",
    "home_red", "away_red",
    "home_yellow", "away_yellow",
    "home_formation", "away_formation",
    "home_corner", "away_corner",
    "home_half_corner", "away_half_corner",
    "referee_name",
]

# 近绩/往绩固定列（简体中文明）
BRIEF_FIXED_HEADERS = [
    "match_id", "match_time", "league_name",
    "home_team", "home_id", "home_score", "home_half_score",
    "home_corner", "home_yellow", "home_red",
    "away_team", "away_id", "away_score", "away_half_score",
    "away_corner", "away_yellow", "away_red",
    "result",
]

# ============================================================================
# 7. 8 个 Sheet 元信息（顺序即工作簿顺序）
# ============================================================================
FIXED_SHEETS = [
    ("match_overview", "比赛", MATCH_FIXED_HEADERS),
    ("tech_stats", "指标", ["比赛编号"] + [f"主队_{cn}" for cn in TECH_FIXED_CN] + [f"客队_{cn}" for cn in TECH_FIXED_CN]),
    ("near_matches", "近绩", BRIEF_FIXED_HEADERS),
    ("vs_matches", "往绩", BRIEF_FIXED_HEADERS),
    ("first_half_stats", "上半场统计", ["比赛编号"] + [f"主队_{cn}" for cn in FIRST_HALF_FIXED_CN] + [f"客队_{cn}" for cn in FIRST_HALF_FIXED_CN]),
    ("second_half_stats", "下半场统计", ["比赛编号"] + [f"主队_{cn}" for cn in SECOND_HALF_FIXED_CN] + [f"客队_{cn}" for cn in SECOND_HALF_FIXED_CN]),
    ("league_rank_stats", "联赛排名", ["比赛编号", "主队"] + [f"主队_{cn}" for cn in LEAGUE_RANK_FIXED] + ["客队"] + [f"客队_{cn}" for cn in LEAGUE_RANK_FIXED]),
    ("detail_events", "详细事件", ["比赛编号", "事件时间", "事件类型", "球队", "球员", "详情"]),
]