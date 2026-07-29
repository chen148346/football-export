"""
json_parser.py - JSON 解析工具
================================
负责解析 shijian_json 和 analysis_json，提取结构化数据。

核心功能：
1. 安全读取嵌套JSON字段（空值判断）
2. 过滤 odds（赔率）相关字段
3. 处理多语言字典（如 {"cn": "张三", "en": "Zhang San"}）
4. 时间戳转换（Unix时间戳 -> 可读时间）
5. 提取7个Sheet所需的结构化数据
"""

import json
import datetime
from typing import Any, Optional, Union, Dict, List

from . import config


# ============================================================================
# 基础工具函数
# ============================================================================

def safe_get(obj: Any, *keys, default=None) -> Any:
    """
    安全读取嵌套字典/列表字段。
    
    用法：
        safe_get(data, "events", "eventList", default=[])
        safe_get(data, "techStat", "itemList", 0, "home", "value", default="")
    
    遇到 None 或类型不匹配时返回 default，不会抛出异常。
    """
    current = obj
    for key in keys:
        if current is None:
            return default
        try:
            if isinstance(key, int):
                if isinstance(current, list) and 0 <= key < len(current):
                    current = current[key]
                else:
                    return default
            else:
                if isinstance(current, dict) and key in current:
                    current = current[key]
                else:
                    return default
        except (TypeError, KeyError, IndexError):
            return default
    return current if current is not None else default


def get_name(name_field: Any) -> str:
    """
    从球员/球队/裁判姓名字段中提取中文名。
    
    处理两种格式：
    1. 字符串：直接返回（如 "迪亚斯"）
    2. 多语言字典：返回 cn 键的值（如 {"cn": "张三", "en": "Zhang San"} -> "张三"）
       如果 cn 不存在，依次尝试 en、第一个可用值。
    3. None/空值：返回空字符串
    """
    if name_field is None:
        return ""
    if isinstance(name_field, str):
        return name_field.strip()
    if isinstance(name_field, dict):
        # 优先取中文
        for lang_key in ("cn", "zh", "zh_cn", "zh_CN"):
            val = name_field.get(lang_key)
            if val:
                return str(val).strip()
        # 其次取英文
        en_val = name_field.get("en")
        if en_val:
            return str(en_val).strip()
        # 最后取第一个非空值
        for v in name_field.values():
            if v:
                return str(v).strip()
        return ""
    return str(name_field).strip()


def to_int(value: Any, default: int = 0) -> int:
    """安全转换为整数"""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def to_str(value: Any, default: str = "") -> str:
    """安全转换为字符串"""
    if value is None:
        return default
    return str(value)


def parse_match_time_14(match_time_str: str) -> Optional[datetime.datetime]:
    """
    解析 matches 表的 14 位时间字符串（YYYYMMDDHHMMSS）。
    
    返回 datetime 对象，解析失败返回 None。
    """
    if not match_time_str or len(str(match_time_str)) < 14:
        return None
    try:
        s = str(match_time_str)[:14]
        return datetime.datetime.strptime(s, "%Y%m%d%H%M%S")
    except (ValueError, TypeError):
        return None


def parse_unix_timestamp(ts: Any) -> Optional[datetime.datetime]:
    """
    解析 analysis_json 中的 matchTime（10位Unix时间戳，秒）。
    
    时间戳为北京时间（UTC+8），返回 datetime 对象。
    解析失败返回 None。
    """
    if ts is None:
        return None
    try:
        # matchTime 可能是字符串或整数
        ts_int = int(ts)
        # Unix时间戳是UTC，加上北京时间偏移
        dt = datetime.datetime.utcfromtimestamp(ts_int)
        dt = dt + datetime.timedelta(hours=config.BEIJING_TZ_OFFSET_HOURS)
        return dt
    except (ValueError, TypeError, OSError):
        return None


def format_datetime(dt: Optional[datetime.datetime], fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """格式化 datetime 为字符串"""
    if dt is None:
        return ""
    return dt.strftime(fmt)


def parse_percent(value: Any) -> Optional[float]:
    """
    将百分比字符串转换为浮点数。
    
    例：
        "6%"   -> 0.06
        "12.5%" -> 0.125
        "76%"  -> 0.76
        60     -> 60.0 (已经是数字则直接返回)
        ""     -> None
        None   -> None
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    try:
        if s.endswith("%"):
            return round(float(s[:-1]) / 100.0, 4)
        return float(s)
    except (ValueError, TypeError):
        return None


def parse_number(value: Any) -> Optional[float]:
    """
    将值转换为浮点数，支持字符串中包含数字的情况。
    
    例：
        "2.18"  -> 2.18
        "76%"   -> 76.0 (注意：parse_percent会转为0.76，这里保留原始数字)
        "90"    -> 90.0
        ""      -> None
        None    -> None
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


# ============================================================================
# Odds（赔率）字段过滤
# ============================================================================

def is_odds_key(key: str) -> bool:
    """
    判断一个键名是否属于赔率/盘口相关字段。
    
    判断规则：
    1. 精确匹配黑名单
    2. 键名中包含 odds/panlu/letgoal/handicap 子串（不区分大小写）
    """
    if not key or not isinstance(key, str):
        return False
    if key in config.ODDS_KEY_BLACKLIST:
        return True
    key_lower = key.lower()
    for sub in config.ODDS_KEY_SUBSTRINGS:
        if sub.lower() in key_lower:
            return True
    return False


def filter_odds(obj: Any) -> Any:
    """
    递归过滤 JSON 中的赔率相关字段。
    
    返回过滤后的新对象（不修改原对象）。
    对于字典：删除所有赔率相关的键。
    对于列表：递归过滤每个元素。
    """
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            if is_odds_key(k):
                continue  # 跳过赔率字段
            result[k] = filter_odds(v)
        return result
    elif isinstance(obj, list):
        return [filter_odds(item) for item in obj]
    else:
        return obj


def parse_json_safely(json_str: str) -> Optional[dict]:
    """
    安全解析 JSON 字符串。
    
    解析失败返回 None（不抛出异常）。
    """
    if not json_str:
        return None
    try:
        if isinstance(json_str, (dict, list)):
            return json_str
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError) as e:
        print(f"[WARNING] JSON解析失败: {e}")
        return None


# ============================================================================
# shijian_json 数据提取
# ============================================================================

def extract_match_info(shijian: dict) -> dict:
    """
    从 shijian_json 提取比赛基本信息。
    
    返回：
        {
            "home_name": str,
            "away_name": str,
            "state_code": int,
            "match_id": int,
        }
    """
    info = safe_get(shijian, "info", default={})
    return {
        "home_name": get_name(safe_get(info, "homeName", default="")),
        "away_name": get_name(safe_get(info, "awayName", default="")),
        "state_code": to_int(safe_get(info, "stateCode", default=0)),
        "match_id": to_int(safe_get(info, "id", default=0)),
    }


def extract_events(shijian: dict, match_id: int) -> List[dict]:
    """
    从 shijian_json.events.eventList 提取事件列表。
    
    事件是多态的，通过特有字段判断事件类型：
    - goalIn: 进球
    - yellowCard: 黄牌
    - redCard: 红牌
    - changePlayer: 换人
    - videoReferee: 视频裁判(VAR)
    - penaltyKick: 点球
    - matchProcess: 比赛节点（半场/全场）
    
    返回事件字典列表，每个字典包含统一字段。
    """
    event_list = safe_get(shijian, "events", "eventList", default=[])
    if not isinstance(event_list, list):
        return []
    
    results = []
    for idx, ev in enumerate(event_list):
        if not isinstance(ev, dict):
            continue
        
        time_val = to_str(safe_get(ev, "time", default=""))
        kind = to_str(safe_get(ev, "kind", default=""))  # HOME / AWAY / OTHER
        process = to_str(safe_get(ev, "process", default=""))  # Regular / HalfTime / FullTime
        
        # 判断事件类型并提取特有字段
        event_type = ""
        player_name = ""
        player_id = 0
        assist_name = ""
        home_score = ""
        away_score = ""
        extra_info = ""
        
        if "goalIn" in ev:
            event_type = "进球"
            goal = ev["goalIn"]
            player_name = get_name(safe_get(goal, "player", "name"))
            player_id = to_int(safe_get(goal, "player", "id"))
            assist_name = get_name(safe_get(goal, "playerAssist", "name"))
            home_score = to_str(safe_get(goal, "homeScore", default=""))
            away_score = to_str(safe_get(goal, "guestScore", default=""))
        
        elif "yellowCard" in ev:
            event_type = "黄牌"
            card = ev["yellowCard"]
            player_name = get_name(safe_get(card, "player", "name"))
            player_id = to_int(safe_get(card, "player", "id"))
        
        elif "redCard" in ev:
            event_type = "红牌"
            card = ev["redCard"]
            player_name = get_name(safe_get(card, "player", "name"))
            player_id = to_int(safe_get(card, "player", "id"))
        
        elif "changePlayer" in ev:
            event_type = "换人"
            cp = ev["changePlayer"]
            on_name = get_name(safe_get(cp, "onPlayer", "name"))
            off_name = get_name(safe_get(cp, "offPlayer", "name"))
            player_name = on_name  # 上场球员
            player_id = to_int(safe_get(cp, "onPlayer", "id"))
            assist_name = off_name  # 下场球员放在 assist_name 列
            reason = to_str(safe_get(cp, "reason", default=""))
            if reason:
                extra_info = f"换人原因: {reason}"
        
        elif "videoReferee" in ev:
            event_type = "视频裁判"
            vr = ev["videoReferee"]
            player_name = get_name(safe_get(vr, "player", "name"))
            player_id = to_int(safe_get(vr, "player", "id"))
            extra_info = to_str(safe_get(vr, "eventType", default=""))
        
        elif "penaltyKick" in ev:
            event_type = "点球"
            pk = ev["penaltyKick"]
            player_name = get_name(safe_get(pk, "player", "name"))
            player_id = to_int(safe_get(pk, "player", "id"))
            home_score = to_str(safe_get(pk, "homeScore", default=""))
            away_score = to_str(safe_get(pk, "guestScore", default=""))
            extra_info = to_str(safe_get(pk, "eventType", default=""))
        
        elif "matchProcess" in ev:
            event_type = "比赛节点"
            mp = ev["matchProcess"]
            home_score = to_str(safe_get(mp, "homeScore", default=""))
            away_score = to_str(safe_get(mp, "guestScore", default=""))
            extra_info = process  # HalfTime / FullTime
        
        else:
            # 未知事件类型
            event_type = "其他"
            extra_fields = [k for k in ev.keys() if k not in ("time", "kind", "process", "animation")]
            if extra_fields:
                extra_info = ",".join(extra_fields)
        
        results.append({
            "match_id": match_id,
            "event_index": idx,
            "time": time_val,
            "side": kind,  # HOME / AWAY / OTHER
            "process": process,
            "event_type": event_type,
            "player_name": player_name,
            "player_id": player_id,
            "related_player": assist_name,  # 助攻球员 或 换下球员
            "home_score": home_score,
            "away_score": away_score,
            "extra_info": extra_info,
        })
    
    return results


def extract_tech_stats(shijian: dict, match_id: int) -> dict:
    """
    从 shijian_json.techStat.itemList 提取技术统计。
    
    返回字典：
        {
            "match_id": int,
            "stats": {kind: {"home": value, "away": value, "name": name}, ...}
        }
    
    不同比赛的统计项可能不同，按 kind 动态匹配。
    
    V1.4变更：百分比字段小数化
    - CONTROL_PERCENT, HALF_CONTROL_PERCENT, PASSBALL_SUCCESS_PERCENT 的value是int（如56）
    - 转换为0.0-1.0小数（如0.56），适配ML训练
    """
    item_list = safe_get(shijian, "techStat", "itemList", default=[])
    if not isinstance(item_list, list):
        return {"match_id": match_id, "stats": {}}
    
    stats = {}
    for item in item_list:
        if not isinstance(item, dict):
            continue
        kind = to_str(safe_get(item, "kind", default=""))
        name = to_str(safe_get(item, "name", default=""))
        home_val = safe_get(item, "home", "value", default="")
        away_val = safe_get(item, "away", "value", default="")
        
        if not kind:
            continue
        
        # V1.5: 百分比字段小数化（int / 100 → 小数）
        # V1.4仅处理3项，V1.5扩展为8项（含PASS_SUC_RATE/CROSS_SUC_RATE等）
        if kind in config.V15_TECH_STAT_PERCENT_KINDS or kind in config.TECH_STAT_PERCENT_KINDS:
            home_val = _int_to_decimal(home_val)
            away_val = _int_to_decimal(away_val)
        
        stats[kind] = {
            "name": name,
            "home": home_val,
            "away": away_val,
        }
    
    return {"match_id": match_id, "stats": stats}


def extract_player_stats(shijian: dict, match_id: int) -> List[dict]:
    """
    从 shijian_json.playerTech 提取球员统计。
    
    返回球员字典列表，每个球员包含：
    - 基本信息：team_side, team_name, player_id, player_name, player_num, is_best
    - 动态技术指标：从 techInfos[] 中提取，按 infoKind 作为列名
    
    注意：playerName 可能是字符串或多语言字典。
    """
    player_tech = safe_get(shijian, "playerTech", default={})
    if not isinstance(player_tech, dict):
        return []
    
    results = []
    for side_key, side_label in [("homeTeamDatas", "home"), ("guestTeamDatas", "away")]:
        team_data = safe_get(player_tech, side_key, default={})
        if not isinstance(team_data, dict):
            continue
        
        team_name = get_name(safe_get(team_data, "teamName", default=""))
        formation = to_str(safe_get(team_data, "formation", default=""))
        player_list = safe_get(team_data, "playerTechInfo", default=[])
        
        if not isinstance(player_list, list):
            continue
        
        for player in player_list:
            if not isinstance(player, dict):
                continue
            
            player_id = to_int(safe_get(player, "playerId", default=0))
            player_name = get_name(safe_get(player, "playerName", default=""))
            player_num = to_str(safe_get(player, "playerNum", default=""))
            is_best = safe_get(player, "isBest", default=False)
            
            row = {
                "match_id": match_id,
                "team_side": side_label,
                "team_name": team_name,
                "formation": formation,
                "player_id": player_id,
                "player_name": player_name,
                "player_num": player_num,
                "is_best": 1 if is_best else 0,
            }
            
            # 提取动态技术指标
            tech_infos = safe_get(player, "techInfos", default=[])
            if isinstance(tech_infos, list):
                for ti in tech_infos:
                    if not isinstance(ti, dict):
                        continue
                    info_kind = to_str(safe_get(ti, "infoKind", default=""))
                    info_value = safe_get(ti, "infoValue", default="")
                    if info_kind:
                        # 尝试将值转为数值（百分比字符串如"76%"转为0.76，纯数字转为float）
                        # 但保留非数值字段（如位置"守门员"、排名"7.9"等）
                        if isinstance(info_value, str) and "%" in info_value:
                            row[f"tech_{info_kind}"] = parse_percent(info_value)
                        else:
                            num_val = parse_number(info_value)
                            row[f"tech_{info_kind}"] = num_val if num_val is not None else to_str(info_value)
            
            results.append(row)
    
    return results


def extract_goal_distribution(shijian: dict, match_id: int) -> List[dict]:
    """
    从 shijian_json.jsq 提取进失球分布。
    
    jsq.jsqList 包含多套数据（Count_30=近30场, Count_50=近50场），
    每套有 jsqInfoHome 和 jsqInfoGuest，各6个时间段。
    每个时间段有 JQ（进球率）和 SQ（失球率）。
    
    返回：每个 count_type 每个球队一行，共最多4行。
    """
    jsq_list = safe_get(shijian, "jsq", "jsqList", default=[])
    if not isinstance(jsq_list, list):
        return []
    
    results = []
    for jsq_item in jsq_list:
        if not isinstance(jsq_item, dict):
            continue
        
        count_type = to_str(safe_get(jsq_item, "count", default=""))
        
        for side_key, side_label in [("jsqInfoHome", "home"), ("jsqInfoGuest", "away")]:
            info_list = safe_get(jsq_item, side_key, default=[])
            if not isinstance(info_list, list) or len(info_list) == 0:
                continue
            
            row = {
                "match_id": match_id,
                "count_type": count_type,
                "team_side": side_label,
            }
            
            for period_info in info_list:
                if not isinstance(period_info, dict):
                    continue
                time_period = to_str(safe_get(period_info, "time", default=""))
                jq = safe_get(period_info, "JQ", default="")
                sq = safe_get(period_info, "SQ", default="")
                if time_period:
                    # JQ/SQ 是百分比字符串（如 "6%"），转为浮点数便于ML训练
                    row[f"{time_period}_JQ"] = parse_percent(jq)
                    row[f"{time_period}_SQ"] = parse_percent(sq)
            
            results.append(row)
    
    return results


def extract_lineup(shijian: dict) -> dict:
    """
    从 shijian_json.lineup 提取阵型和阵容信息。
    
    返回：
        {
            "home_formation": str,
            "away_formation": str,
            "home_starters": [...],
            "away_starters": [...],
            "home_subs": [...],
            "away_subs": [...],
        }
    """
    lineup = safe_get(shijian, "lineup", default={})
    if not isinstance(lineup, dict):
        return {
            "home_formation": "", "away_formation": "",
            "home_starters": [], "away_starters": [],
            "home_subs": [], "away_subs": [],
        }
    
    return {
        "home_formation": to_str(safe_get(lineup, "homeFormation", default="")),
        "away_formation": to_str(safe_get(lineup, "guestFormation", default="")),
        "home_starters": safe_get(lineup, "homePlayerList", default=[]),
        "away_starters": safe_get(lineup, "guestPlayerList", default=[]),
        "home_subs": safe_get(lineup, "homeBakPlayerList", default=[]),
        "away_subs": safe_get(lineup, "guestBakPlayerList", default=[]),
    }


def extract_corner_events(shijian: dict) -> dict:
    """从 shijian_json.conerEvent 提取角球事件"""
    ce = safe_get(shijian, "conerEvent", default={})
    if not isinstance(ce, dict):
        return {"home_corner": "", "away_corner": "", "home_half_corner": "", "away_half_corner": ""}
    return {
        "home_corner": to_str(safe_get(ce, "home", default="")),
        "away_corner": to_str(safe_get(ce, "guest", default="")),
        "home_half_corner": to_str(safe_get(ce, "homeHalf", default="")),
        "away_half_corner": to_str(safe_get(ce, "guestHalf", default="")),
    }


# ============================================================================
# analysis_json 数据提取
# ============================================================================

def _extract_match_brief(m: dict) -> dict:
    """
    从近期比赛/交锋记录中提取比赛摘要。
    
    近期比赛和交锋记录的结构相同，共用此函数。
    """
    if not isinstance(m, dict):
        return {}
    
    match_time_ts = safe_get(m, "matchTime", default="")
    match_time_dt = parse_unix_timestamp(match_time_ts)
    
    home_team = safe_get(m, "homeTeam", default={})
    away_team = safe_get(m, "awayTeam", default={})
    
    return {
        "near_match_id": to_int(safe_get(m, "id", default=0)),
        "league_id": to_int(safe_get(m, "leagueId", default=0)),
        "league_name": to_str(safe_get(m, "leagueName", default="")),
        "league_name_full": to_str(safe_get(m, "leagueNameFull", default="")),
        "match_time": format_datetime(match_time_dt),
        "match_time_ts": to_str(match_time_ts),
        "home_team_id": to_int(safe_get(home_team, "id", default=0)),
        "home_team_name": get_name(safe_get(home_team, "name", default="")),
        "home_score": to_int(safe_get(home_team, "score", default=0)),
        "home_half_score": to_int(safe_get(home_team, "halfScore", default=0)),
        "home_corner": to_int(safe_get(home_team, "corner", default=0)),
        "home_yellow": to_int(safe_get(home_team, "yellowCard", default=0)),
        "home_red": to_int(safe_get(home_team, "redCard", default=0)),
        "home_half_corner": to_int(safe_get(home_team, "halfCorner", default=0)),
        "home_is_first_goal": 1 if safe_get(home_team, "isFirstGoal", default=False) else 0,
        "home_shot_on_target": to_int(safe_get(home_team, "shotOnTarget", default=0)),
        "away_team_id": to_int(safe_get(away_team, "id", default=0)),
        "away_team_name": get_name(safe_get(away_team, "name", default="")),
        "away_score": to_int(safe_get(away_team, "score", default=0)),
        "away_half_score": to_int(safe_get(away_team, "halfScore", default=0)),
        "away_corner": to_int(safe_get(away_team, "corner", default=0)),
        "away_yellow": to_int(safe_get(away_team, "yellowCard", default=0)),
        "away_red": to_int(safe_get(away_team, "redCard", default=0)),
        "away_half_corner": to_int(safe_get(away_team, "halfCorner", default=0)),
        "away_is_first_goal": 1 if safe_get(away_team, "isFirstGoal", default=False) else 0,
        "away_shot_on_target": to_int(safe_get(away_team, "shotOnTarget", default=0)),
        "is_neutrality": 1 if safe_get(m, "isNeutrality", default=False) else 0,
    }


def extract_near_matches(analysis: dict, match_id: int) -> List[dict]:
    """
    从 analysis_json.nearMatches 提取近期战绩。
    
    包含主队近期比赛和客队近期比赛。
    """
    near = safe_get(analysis, "nearMatches", default={})
    if not isinstance(near, dict):
        return []
    
    results = []
    for side_key, side_label in [("homeMatches", "home"), ("awayMatches", "away")]:
        side_data = safe_get(near, side_key, default={})
        if not isinstance(side_data, dict):
            continue
        
        team_name = get_name(safe_get(side_data, "teamName", default=""))
        matches = safe_get(side_data, "matches", default=[])
        
        if not isinstance(matches, list):
            continue
        
        for m in matches:
            brief = _extract_match_brief(m)
            if not brief:
                continue
            brief["match_id"] = match_id
            brief["team_side"] = side_label
            brief["team_name"] = team_name
            results.append(brief)
    
    return results


def extract_vs_matches(analysis: dict, match_id: int) -> List[dict]:
    """
    从 analysis_json.vsMatches.matches 提取交锋历史。
    
    注意：只提取 matches（不提取 matches2，因为 matches2 是赔率相关）。
    """
    vs = safe_get(analysis, "vsMatches", default={})
    if not isinstance(vs, dict):
        return []
    
    matches = safe_get(vs, "matches", default=[])
    if not isinstance(matches, list):
        return []
    
    results = []
    for m in matches:
        brief = _extract_match_brief(m)
        if not brief:
            continue
        brief["match_id"] = match_id
        results.append(brief)
    
    return results


def extract_referee(analysis: dict) -> dict:
    """
    从 analysis_json.referee 提取裁判信息。
    
    注意：referee.name 是多语言字典，需提取 cn 键。
    """
    ref = safe_get(analysis, "referee", default={})
    if not isinstance(ref, dict):
        return {"referee_id": 0, "referee_name": ""}
    
    ref_info = safe_get(ref, "referee", default={})
    return {
        "referee_id": to_int(safe_get(ref_info, "id", default=0)),
        "referee_name": get_name(safe_get(ref_info, "name", default="")),
    }


# ============================================================================
# V1.4 新增函数 - 百分比小数化辅助 + 5个新Sheet数据提取
# ============================================================================

def _int_to_decimal(value):
    """
    V1.4新增 - 将int类型的百分比值转为0.0-1.0小数。
    
    techStat的百分比字段value是int（如56），需/100转为0.56。
    """
    if value is None or value == "":
        return ""
    try:
        return round(float(value) / 100.0, 4)
    except (ValueError, TypeError):
        return value


def extract_half_tech_stats(shijian: dict, match_id: int, half: str) -> dict:
    """
    V1.4新增 - 从 shijian_json.techStat.firstHalfList 或 secondHalfList 提取半场技术统计。
    
    参数：
        half: "first" 或 "second"
    
    返回字典：
        {
            "match_id": int,
            "stats": {kind: {"home": value, "away": value, "name": name}, ...}
        }
    
    注意：firstHalfList和secondHalfList长度可能不同（如35项 vs 37项），必须按kind匹配。
    百分比字段同样需要小数化。
    """
    list_key = "firstHalfList" if half == "first" else "secondHalfList"
    item_list = safe_get(shijian, "techStat", list_key, default=[])
    if not isinstance(item_list, list):
        return {"match_id": match_id, "stats": {}}
    
    stats = {}
    for item in item_list:
        if not isinstance(item, dict):
            continue
        kind = to_str(safe_get(item, "kind", default=""))
        name = to_str(safe_get(item, "name", default=""))
        home_val = safe_get(item, "home", "value", default="")
        away_val = safe_get(item, "away", "value", default="")
        
        if not kind:
            continue
        
        # V1.5: 百分比字段小数化（扩展为8项）
        if kind in config.V15_TECH_STAT_PERCENT_KINDS or kind in config.TECH_STAT_PERCENT_KINDS:
            home_val = _int_to_decimal(home_val)
            away_val = _int_to_decimal(away_val)
        
        stats[kind] = {
            "name": name,
            "home": home_val,
            "away": away_val,
        }
    
    return {"match_id": match_id, "stats": stats}


def extract_league_rank_stats(analysis: dict, match_id: int) -> dict:
    """
    V1.4新增 - 从 analysis_json.curLeagueStat.itemList 提取联赛排名统计。
    
    返回字典：
        {
            "match_id": int,
            "stats": {kind: {"home": value, "away": value, "name": name}, ...}
        }
    
    注意：
    - curLeagueStat可能为None（如世界杯等杯赛），需判空
    - homeValue/awayValue是字符串，需根据kind转int或float
    - GoalAvg和LossAvg转float，其余转int
    """
    cls = safe_get(analysis, "curLeagueStat", default=None)
    if not cls or not isinstance(cls, dict):
        return {"match_id": match_id, "stats": {}}
    
    item_list = safe_get(cls, "itemList", default=[])
    if not isinstance(item_list, list):
        return {"match_id": match_id, "stats": {}}
    
    stats = {}
    for item in item_list:
        if not isinstance(item, dict):
            continue
        kind = to_str(safe_get(item, "kind", default=""))
        home_val = safe_get(item, "homeValue", default="")
        away_val = safe_get(item, "awayValue", default="")
        
        if not kind:
            continue
        
        name = config.CUR_LEAGUE_STAT_KIND_MAP.get(kind, kind)
        
        # V1.4: 字符串转数值（GoalAvg/LossAvg转float，其余转int）
        if kind in config.CUR_LEAGUE_STAT_FLOAT_KINDS:
            home_val = _safe_float(home_val)
            away_val = _safe_float(away_val)
        else:
            home_val = _safe_int(home_val)
            away_val = _safe_int(away_val)
        
        stats[kind] = {
            "name": name,
            "home": home_val,
            "away": away_val,
        }
    
    return {"match_id": match_id, "stats": stats}


def _safe_int(value):
    """安全转int"""
    if value is None or value == "":
        return ""
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return value


def _safe_float(value):
    """安全转float"""
    if value is None or value == "":
        return ""
    try:
        return float(value)
    except (ValueError, TypeError):
        return value


def extract_half_full_stats(shijian: dict, match_id: int) -> List[dict]:
    """
    V1.4新增 - 从 shijian_json.allhalf.list 提取近两赛季半场/全场统计。
    
    返回字典列表，每个HA类型一行：
        [
            {
                "match_id": int,
                "ha_type": "HA33",
                "ha_desc": "半胜/全胜",
                "home_half": int,   # 主队半场场次
                "home_all": int,    # 主队全场场次
                "away_half": int,   # 客队半场场次
                "away_all": int,    # 客队全场场次
            },
            ...
        ]
    
    注意：allhalf可能为None（如世界杯等杯赛），需判空。
    9种HA类型：HA33, HA31, HA30, HA13, HA11, HA10, HA03, HA01, HA00
    """
    ah = safe_get(shijian, "allhalf", default=None)
    if not ah or not isinstance(ah, dict):
        return []
    
    item_list = safe_get(ah, "list", default=[])
    if not isinstance(item_list, list):
        return []
    
    results = []
    for item in item_list:
        if not isinstance(item, dict):
            continue
        ha_type = to_str(safe_get(item, "type", default=""))
        if not ha_type:
            continue
        
        ha_desc = config.HA_TYPE_MAP.get(ha_type, ha_type)
        
        results.append({
            "match_id": match_id,
            "ha_type": ha_type,
            "ha_desc": ha_desc,
            "home_half": safe_get(item, "halfHome", default=0),
            "home_all": safe_get(item, "allHome", default=0),
            "away_half": safe_get(item, "halfGuest", default=0),
            "away_all": safe_get(item, "allGuest", default=0),
        })
    
    return results


def extract_detailed_events(shijian: dict, match_id: int) -> List[dict]:
    """
    V1.4新增 - 从 shijian_json.eventTxt.EventTxtLives 提取详细事件。
    
    返回字典列表，每个事件一行：
        [
            {
                "match_id": int,
                "event_index": int,
                "time_txt": str,       # 时间文本（如"10'", "完"）
                "happen_time": int,    # 发生时间（分钟）
                "match_state": int,    # 比赛状态码（1=上半场, 2=中场, 3=下半场, -1=完场）
                "injure_time": int,    # 伤停补时
                "kind": str,           # 事件类型（Start, Goal, Corner, ChangePlayer等）
                "context": str,        # 事件内容（已剔除HTML标签）
            },
            ...
        ]
    
    ⚠️ 踩坑提醒（最重要）：
    EventTxtLives是倒序排列的（最后一条是开赛，第一条是完场）！
    必须使用 reversed() 反转后才是正序（从1'开赛到完场）。
    
    Context字段可能包含HTML标签，需用正则剔除。
    """
    import re
    
    event_txt = safe_get(shijian, "eventTxt", default=None)
    if not event_txt or not isinstance(event_txt, dict):
        return []
    
    lives = safe_get(event_txt, "EventTxtLives", default=[])
    if not isinstance(lives, list) or len(lives) == 0:
        return []
    
    # ⚠️ 必须反转！原始数据是倒序的（完场在前，开赛在后）
    lives = list(reversed(lives))
    
    results = []
    for i, live in enumerate(lives):
        if not isinstance(live, dict):
            continue
        
        context = to_str(safe_get(live, "Context", default=""))
        # 剔除HTML标签
        context = re.sub(r'<[^>]+>', '', context).strip()
        
        results.append({
            "match_id": match_id,
            "event_index": i,
            "time_txt": to_str(safe_get(live, "timeTxt", default="")),
            "happen_time": safe_get(live, "happenTime", default=0),
            "match_state": safe_get(live, "matchState", default=0),
            "injure_time": safe_get(live, "InjureTime", default=0),
            "kind": to_str(safe_get(live, "kind", default="")),
            "context": context,
        })
    
    return results
