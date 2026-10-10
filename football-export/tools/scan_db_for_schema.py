#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
固定表头导出 - 数据库只读扫描脚本（V1.8 筹备工具）
=====================================================

作用：
    在不改动/不复制大体积数据库的前提下，只读扫描 football.db，
    产出三份小体积报告，供人工审核后确定「固定表头 Schema」。

产物（默认输出到脚本同目录 scan_report/）：
    1. schema_report.json / .md
       - 8 个目标 Sheet 的动态字段（kind / infoKind）清单
       - 每个字段出现次数、覆盖率（多少场比赛含此字段）
       - 各 JSON 段（techStat/eventTxt/nearMatches/vsMatches...）存在率
    2. team_master_seed.json
       - 球队ID -> {规范名建议, 出现过的所有名称写法, 出现次数}
    3. scan_summary.txt
       - 人类可读的概览（表数量、球队规模、字段缺失情况）

设计要点：
    - 只读连接：SQLite URI file:...?mode=ro，绝不写入数据库
    - 可采样：--limit N 只扫最近 N 场（快速摸底）；不填则全量
    - 不依赖项目其它模块，单文件可直接拷到 VPS 运行
    - 仅使用 Python 标准库（sqlite3 / json / argparse / collections）

用法：
    python3 scan_db_for_schema.py --db /root/football_system/football.db
    python3 scan_db_for_schema.py --db /path/football.db --limit 5000
    python3 scan_db_for_schema.py --db /path/football.db --out /root/scan_report
"""

import argparse
import json
import os
import sqlite3
import sys
from collections import OrderedDict, defaultdict
from datetime import datetime


# ============================================================================
# 目标 8 个 Sheet（固定表头模式保留项）
# ============================================================================
TARGET_SHEETS = [
    "match",              # 比赛
    "tech",               # 指标
    "near",               # 近绩
    "vs",                 # 往绩
    "first_half",         # 上半场统计
    "second_half",        # 下半场统计
    "league_rank",        # 联赛排名
    "detail_evt",         # 详细事件
]


# ============================================================================
# 极简 JSON 安全读取（避免依赖项目内模块）
# ============================================================================
def _load_json(raw):
    """把数据库里的 JSON 文本解析为 dict/list；失败返回 None。"""
    if not raw:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def _safe_get(obj, *keys, default=None):
    """按路径安全取值，任一层缺失/类型不符都返回 default。"""
    cur = obj
    for key in keys:
        if isinstance(cur, dict):
            cur = cur.get(key)
        elif isinstance(cur, list) and isinstance(key, int):
            if -len(cur) <= key < len(cur):
                cur = cur[key]
            else:
                return default
        else:
            return default
    return default if cur is None else cur


def _to_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


# ============================================================================
# 多语言 name 提取（{cn:..,hk:..,en:..} 或纯字符串）
# ============================================================================
def _get_name(raw) -> str:
    """
    数据源里的 name 可能是多语言 dict 或纯字符串。
    固定表头要求简体，优先取 cn，其次 zh / zho，再退回原始字符串。
    （繁体 hk / en 也保留记录，供后续映射参考，不在这里丢弃。）
    """
    if isinstance(raw, dict):
        for key in ("cn", "zh", "zho", "zh-CN", "chs"):
            val = raw.get(key)
            if val:
                return _to_str(val)
        # 没有简体键时，取任意非空值占位（具体语言在报告里可辨）
        for val in raw.values():
            if val:
                return _to_str(val)
        return ""
    return _to_str(raw)


def _name_lang(raw) -> str:
    """粗略判断 name 取到的是哪种语言键，用于报告分析简繁体来源。"""
    if isinstance(raw, dict):
        for key in ("cn", "zh", "zho", "zh-CN", "chs"):
            if raw.get(key):
                return key
        if raw.get("hk") or raw.get("zh-TW"):
            return "hk"
        if raw.get("en"):
            return "en"
    return "str"


# ============================================================================
# 扫描状态收集器
# ============================================================================
class ScanCollector:
    def __init__(self):
        # 总比赛数（实际处理到的）
        self.total_matches = 0
        # 有完场快照的比赛数
        self.fulltime_matches = 0

        # 各 JSON 顶层段存在计数
        self.section_present = defaultdict(int)
        # shijian / analysis 非空计数
        self.shijian_present = 0
        self.analysis_present = 0

        # 指标类字段：sheet -> kind -> {name, count, name_langs}
        # count = 有多少场比赛含该 kind
        self.tech_kinds = {
            "tech": OrderedDict(),
            "first_half": OrderedDict(),
            "second_half": OrderedDict(),
            "league_rank": OrderedDict(),
        }

        # 详细事件 kind 计数
        self.detail_event_kinds = defaultdict(int)

        # 球队：team_id -> {"names": {name: count}, "count": n, "lang": set}
        self.teams = defaultdict(lambda: {"names": defaultdict(int), "count": 0, "lang": set()})

        # 当前比赛（matches 表主行）的名称：name -> count
        # 用于发现"只有名称、暂无ID"的球队，提示主数据缺口
        self.current_team_names = defaultdict(int)

        # JSON 解析失败计数
        self.json_parse_fail = {"shijian": 0, "analysis": 0}

    # ---------- 指标 kind 记录 ----------
    def record_tech_kind(self, sheet: str, kind: str, name: str):
        kind = _to_str(kind)
        if not kind:
            return
        bucket = self.tech_kinds[sheet]
        if kind not in bucket:
            bucket[kind] = {"name": _to_str(name), "count": 0}
        bucket[kind]["count"] += 1
        # 如果首次没名字、后来有名字，补上
        if not bucket[kind]["name"] and name:
            bucket[kind]["name"] = _to_str(name)

    # ---------- 球队记录 ----------
    def record_team(self, team_id, name: str, lang: str = ""):
        team_id = _to_str(team_id)
        name = _to_str(name)
        if not team_id or team_id == "0":
            return
        info = self.teams[team_id]
        info["count"] += 1
        if name:
            info["names"][name] += 1
        if lang:
            info["lang"].add(lang)

    def record_current_name(self, name: str):
        name = _to_str(name)
        if name:
            self.current_team_names[name] += 1


# ============================================================================
# 单场比赛扫描
# ============================================================================
def scan_match(row, col: ScanCollector):
    """
    row: (match_id, sclass_name, home_team, away_team, shijian_json, analysis_json)
    """
    match_id, sclass_name, home_team, away_team, sj_raw, an_raw = row
    col.total_matches += 1

    # 当前比赛名称（无 ID），先记录
    col.record_current_name(home_team)
    col.record_current_name(away_team)

    shijian = _load_json(sj_raw)
    analysis = _load_json(an_raw)

    if sj_raw and shijian is None:
        col.json_parse_fail["shijian"] += 1
    if an_raw and analysis is None:
        col.json_parse_fail["analysis"] += 1

    if isinstance(shijian, dict):
        col.shijian_present += 1
        _scan_shijian(shijian, col)

    if isinstance(analysis, dict):
        col.analysis_present += 1
        _scan_analysis(analysis, col)


def _scan_shijian(shijian: dict, col: ScanCollector):
    # ---- 指标 tech：techStat.itemList ----
    tech_stat = _safe_get(shijian, "techStat", default=None)
    if isinstance(tech_stat, dict):
        col.section_present["techStat"] += 1
        for list_key, sheet in [
            ("itemList", "tech"),
            ("firstHalfList", "first_half"),
            ("secondHalfList", "second_half"),
        ]:
            items = _safe_get(tech_stat, list_key, default=[])
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        col.record_tech_kind(sheet, item.get("kind"), item.get("name"))

    # ---- 详细事件：eventTxt.EventTxtLives ----
    event_txt = _safe_get(shijian, "eventTxt", default=None)
    if isinstance(event_txt, dict):
        col.section_present["eventTxt"] += 1
        lives = _safe_get(event_txt, "EventTxtLives", default=[])
        if isinstance(lives, list):
            for live in lives:
                if isinstance(live, dict):
                    kind = _to_str(live.get("kind"))
                    if kind:
                        col.detail_event_kinds[kind] += 1

    # ---- 阵型/角球（lineup/cornerEvent）存在性，供参考 ----
    if _safe_get(shijian, "lineup", default=None) is not None:
        col.section_present["lineup"] += 1
    if _safe_get(shijian, "cornerEvent", default=None) is not None:
        col.section_present["cornerEvent"] += 1
    if _safe_get(shijian, "allhalf", default=None) is not None:
        col.section_present["allhalf"] += 1


def _scan_analysis(analysis: dict, col: ScanCollector):
    # ---- 联赛排名：curLeagueStat.itemList ----
    cur_ls = _safe_get(analysis, "curLeagueStat", default=None)
    if isinstance(cur_ls, dict):
        col.section_present["curLeagueStat"] += 1
        items = _safe_get(cur_ls, "itemList", default=[])
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    col.record_tech_kind(
                        "league_rank", item.get("kind"), item.get("kind")
                    )

    # ---- 近绩：nearMatches.homeMatches/awayMatches ----
    near = _safe_get(analysis, "nearMatches", default=None)
    if isinstance(near, dict):
        col.section_present["nearMatches"] += 1
        for side_key in ("homeMatches", "awayMatches"):
            side = _safe_get(near, side_key, default=None)
            if isinstance(side, dict):
                matches = _safe_get(side, "matches", default=[])
                if isinstance(matches, list):
                    for m in matches:
                        _scan_brief_match(m, col)

    # ---- 往绩：vsMatches.matches（不含 matches2 赔率） ----
    vs = _safe_get(analysis, "vsMatches", default=None)
    if isinstance(vs, dict):
        col.section_present["vsMatches"] += 1
        matches = _safe_get(vs, "matches", default=[])
        if isinstance(matches, list):
            for m in matches:
                _scan_brief_match(m, col)

    # ---- 裁判（存在性参考） ----
    if _safe_get(analysis, "referee", default=None) is not None:
        col.section_present["referee"] += 1


def _scan_brief_match(m: dict, col: ScanCollector):
    """从近绩/往绩的单场记录中收集球队 ID 与名称（这是 ID 的核心来源）。"""
    if not isinstance(m, dict):
        return

    for side_key in ("homeTeam", "awayTeam"):
        team = _safe_get(m, side_key, default=None)
        if isinstance(team, dict):
            tid = team.get("id")
            name_raw = team.get("name")
            col.record_team(tid, _get_name(name_raw), _name_lang(name_raw))


def _analysis_cond(only_analysis: bool) -> str:
    """为完场查询拼接仅取 analysis 非空快照的过滤条件（避免引号嵌套问题）。"""
    if not only_analysis:
        return ""
    return "AND COALESCE(s.analysis_json, '') != '' "


# ============================================================================
# 数据库连接与遍历
# ============================================================================
def iter_matches(db_path: str, limit: int = None, only_analysis: bool = False):
    """
    只读连接，遍历"带完场快照"的比赛（与导出主逻辑口径一致）。

    优先用 matches.fulltime_snapshot_id 关联；
    若该字段大面积为空，则回退到 snapshots 中 snapshot_type='fulltime'。
    生成 row: (match_id, sclass_name, home_team, away_team, shijian, analysis)
    only_analysis=True 时只返回 analysis_json 非空的完场（有效数据段），
    使覆盖率基于"有效完场"而非被无分析比赛稀释的总量。
    """
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = None

    try:
        # 判断 fulltime_snapshot_id 覆盖率，决定关联方式
        cur = conn.execute(
            "SELECT COUNT(*) FROM matches "
            "WHERE fulltime_snapshot_id IS NOT NULL AND fulltime_snapshot_id <> 0"
        )
        with_ft_id = cur.fetchone()[0]
        cur = conn.execute("SELECT COUNT(*) FROM matches")
        total = cur.fetchone()[0]

        use_ft_id = total > 0 and with_ft_id > total * 0.5

        if use_ft_id:
            sql = (
                "SELECT m.id, m.sclass_name, m.home_team, m.away_team, "
                "s.shijian_json, s.analysis_json "
                "FROM matches m "
                "LEFT JOIN snapshots s ON s.id = m.fulltime_snapshot_id "
                "WHERE m.latest_state_code = -1 "
                + _analysis_cond(only_analysis)
                + "ORDER BY m.match_time DESC"
            )
        else:
            sql = (
                "SELECT m.id, m.sclass_name, m.home_team, m.away_team, "
                "s.shijian_json, s.analysis_json "
                "FROM matches m "
                "LEFT JOIN snapshots s "
                "  ON s.match_id = m.id AND s.snapshot_type = 'fulltime' "
                "WHERE m.latest_state_code = -1 "
                + _analysis_cond(only_analysis)
                + "ORDER BY m.match_time DESC"
            )

        params = ()
        if limit:
            sql += " LIMIT ?"
            params = (int(limit),)

        cursor = conn.execute(sql, params)
        for row in cursor:
            yield row
    finally:
        conn.close()


# ============================================================================
# 月份分布分析（快速模式，不扫描内容，仅 SQL 聚合）
# ============================================================================
def run_dist_analysis(db_path: str):
    """
    输出带 JSON 的完场比赛按月分布，用于定位深层数据集中在哪些历史月份。
    只读连接；展示：月份 / 完场总数 / 带 shijian / 带 analysis。
    """
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    rows = []
    try:
        # 同 iter_matches 的关联口径：优先 fulltime_snapshot_id
        cur = conn.execute(
            "SELECT COUNT(*) FROM matches "
            "WHERE fulltime_snapshot_id IS NOT NULL AND fulltime_snapshot_id <> 0"
        )
        with_ft_id = cur.fetchone()[0]
        cur = conn.execute("SELECT COUNT(*) FROM matches")
        total = cur.fetchone()[0]
        use_ft_id = total > 0 and with_ft_id > total * 0.5

        if use_ft_id:
            sql = (
                "SELECT substr(m.match_time,1,6) ym, "
                "COUNT(DISTINCT m.id) ft_total, "
                "COUNT(DISTINCT CASE WHEN COALESCE(s.shijian_json,'')!='' THEN m.id END) has_sj, "
                "COUNT(DISTINCT CASE WHEN COALESCE(s.analysis_json,'')!='' THEN m.id END) has_an "
                "FROM matches m "
                "LEFT JOIN snapshots s ON s.id = m.fulltime_snapshot_id "
                "WHERE m.latest_state_code = -1 "
                "GROUP BY ym ORDER BY ym"
            )
        else:
            sql = (
                "SELECT substr(m.match_time,1,6) ym, "
                "COUNT(DISTINCT m.id) ft_total, "
                "COUNT(DISTINCT CASE WHEN COALESCE(s.shijian_json,'')!='' THEN m.id END) has_sj, "
                "COUNT(DISTINCT CASE WHEN COALESCE(s.analysis_json,'')!='' THEN m.id END) has_an "
                "FROM matches m "
                "LEFT JOIN snapshots s ON s.match_id = m.id AND s.snapshot_type='fulltime' "
                "WHERE m.latest_state_code = -1 "
                "GROUP BY ym ORDER BY ym"
            )
        rows = conn.execute(sql).fetchall()
    finally:
        conn.close()

    lines = ["月份      完场数  带shijian  带analysis"]
    for ym, ft, sj, an in rows:
        lines.append(f"{ym}    {ft:<7} {sj:<9} {an}")
    total_ft = sum(r[1] for r in rows)
    total_sj = sum(r[2] for r in rows)
    total_an = sum(r[3] for r in rows)
    lines.append("-" * 40)
    lines.append(f"合计      {total_ft:<7} {total_sj:<9} {total_an}")
    print("\n".join(lines))
    return rows


# ============================================================================
# 报告生成
# ============================================================================
def build_team_seed(col: ScanCollector) -> dict:
    """
    生成 team_master_seed.json：
    每个 ID 给一个简体规范名建议（该 ID 下出现次数最多的名称）。
    """
    seed = OrderedDict()
    for tid, info in sorted(col.teams.items(), key=lambda kv: kv[1]["count"], reverse=True):
        names = info["names"]
        # 出现次数最多的名称作为默认规范名；平票时取名称字典序，保证稳定
        suggested = sorted(names.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] if names else ""
        seed[tid] = {
            "canonical_name": suggested,
            "occurrence_count": info["count"],
            "name_variants": OrderedDict(
                sorted(names.items(), key=lambda kv: (-kv[1], kv[0]))
            ),
            "observed_lang": sorted(info["lang"]),
        }
    return seed


def build_schema_report(col: ScanCollector) -> dict:
    total = max(col.total_matches, 1)

    sheets = OrderedDict()

    # 比赛/近绩/往绩/详细事件：列本身固定或每行一记录，记录结构存在性
    sheets["match"] = {
        "title": "比赛",
        "column_type": "fixed",
        "note": "列固定；字段来自 matches 表 + shijian(阵型/角球) + analysis(裁判)",
    }
    sheets["near"] = {
        "title": "近绩",
        "column_type": "fixed_rows",
        "rows_source_present_ratio": round(col.section_present["nearMatches"] / total, 4),
        "note": "每行一场近期比赛；球队ID来自 homeTeam/awayTeam.id",
    }
    sheets["vs"] = {
        "title": "往绩",
        "column_type": "fixed_rows",
        "rows_source_present_ratio": round(col.section_present["vsMatches"] / total, 4),
        "note": "每行一场交锋；只取 vsMatches.matches（matches2 为赔率，已排除）",
    }

    # 三个动态指标 sheet
    kind_title = {
        "tech": "指标",
        "first_half": "上半场统计",
        "second_half": "下半场统计",
        "league_rank": "联赛排名",
    }
    for sheet in ("tech", "first_half", "second_half", "league_rank"):
        kinds = col.tech_kinds[sheet]
        ordered = OrderedDict()
        for kind, info in sorted(kinds.items(), key=lambda kv: (-kv[1]["count"], kv[0])):
            ordered[kind] = {
                "name_cn_hint": info["name"],
                "match_count": info["count"],
                "coverage_ratio": round(info["count"] / total, 4),
            }
        sheets[sheet] = {
            "title": kind_title[sheet],
            "column_type": "fixed_by_kind",
            "distinct_kind_count": len(kinds),
            "kinds": ordered,
        }

    # 详细事件 kind
    de_kinds = OrderedDict(
        (k, v) for k, v in sorted(col.detail_event_kinds.items(), key=lambda kv: (-kv[1], kv[0]))
    )
    sheets["detail_evt"] = {
        "title": "详细事件",
        "column_type": "fixed_rows",
        "rows_source_present_ratio": round(col.section_present["eventTxt"] / total, 4),
        "distinct_event_kind_count": len(de_kinds),
        "event_kinds": de_kinds,
        "note": "每行一个事件；EventTxtLives 原始倒序，导出时已反转",
    }

    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scanned_matches": col.total_matches,
        "shijian_present": col.shijian_present,
        "analysis_present": col.analysis_present,
        "section_present": dict(col.section_present),
        "json_parse_fail": dict(col.json_parse_fail),
        "team_id_count": len(col.teams),
        "current_team_name_count": len(col.current_team_names),
        "sheets": sheets,
    }
    return report


def write_markdown(report: dict, team_seed: dict, path: str):
    """生成便于人工审阅的 Markdown 报告。"""
    lines = []
    add = lines.append

    add("# 固定表头 Schema 扫描报告")
    add("")
    add(f"- 生成时间：{report['generated_at']}")
    add(f"- 扫描比赛数：{report['scanned_matches']}")
    add(f"- shijian 非空：{report['shijian_present']}")
    add(f"- analysis 非空：{report['analysis_present']}")
    add(f"- 唯一球队ID数：{report['team_id_count']}")
    add(f"- 当前比赛名称种类数（无ID锚点）：{report['current_team_name_count']}")
    add("")
    add("## JSON 段存在情况")
    add("")
    add("| 段 | 出现次数 | 覆盖率 |")
    add("|----|---------|--------|")
    total = max(report["scanned_matches"], 1)
    for sec, cnt in sorted(report["section_present"].items(), key=lambda kv: -kv[1]):
        add(f"| {sec} | {cnt} | {round(cnt/total, 4)} |")
    add("")

    for sheet in TARGET_SHEETS:
        info = report["sheets"][sheet]
        add(f"## {info['title']}（{sheet}）")
        add("")
        if "kinds" in info:
            add(f"- 不同 kind 数：{info['distinct_kind_count']}")
            add("")
            add("| kind | 名称提示 | 比赛数 | 覆盖率 |")
            add("|------|---------|--------|--------|")
            for kind, kinfo in info["kinds"].items():
                add(
                    f"| {kind} | {kinfo['name_cn_hint']} | "
                    f"{kinfo['match_count']} | {kinfo['coverage_ratio']} |"
                )
            add("")
        elif "event_kinds" in info:
            add(f"- 不同事件 kind 数：{info['distinct_event_kind_count']}")
            add("")
            add("| 事件 kind | 次数 |")
            add("|----------|------|")
            for kind, cnt in info["event_kinds"].items():
                add(f"| {kind} | {cnt} |")
            add("")
        else:
            add(f"- 列类型：{info['column_type']}")
            if "rows_source_present_ratio" in info:
                add(f"- 数据源存在率：{info['rows_source_present_ratio']}")
            add(f"- 说明：{info.get('note', '')}")
            add("")

    add("## 球队主数据（Top 100 预览，完整见 team_master_seed.json）")
    add("")
    add("| 球队ID | 建议规范名 | 出现次数 | 名称写法数 |")
    add("|--------|-----------|---------|-----------|")
    for i, (tid, info) in enumerate(team_seed.items()):
        if i >= 100:
            break
        add(
            f"| {tid} | {info['canonical_name']} | "
            f"{info['occurrence_count']} | {len(info['name_variants'])} |"
        )
    add("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_summary_txt(report: dict, team_seed: dict, path: str):
    total = max(report["scanned_matches"], 1)
    lines = []
    add = lines.append
    add("=" * 60)
    add("固定表头导出 - 扫描概览")
    add("=" * 60)
    add(f"扫描比赛数        : {report['scanned_matches']}")
    add(f"shijian 非空      : {report['shijian_present']}")
    add(f"analysis 非空     : {report['analysis_present']}")
    add(f"JSON解析失败      : {report['json_parse_fail']}")
    add(f"唯一球队ID数      : {report['team_id_count']}")
    add(f"当前球队名称种类  : {report['current_team_name_count']}")
    add("")
    add("各 Sheet 动态 kind 数量：")
    for sheet in TARGET_SHEETS:
        info = report["sheets"][sheet]
        if "distinct_kind_count" in info:
            add(f"  - {info['title']:<8}: {info['distinct_kind_count']} 种 kind")
        elif "distinct_event_kind_count" in info:
            add(f"  - {info['title']:<8}: {info['distinct_event_kind_count']} 种事件 kind")
        else:
            add(f"  - {info['title']:<8}: 列固定")
    add("")
    add("字段分级建议（覆盖率基于有效完场计算）：")
    for sheet in TARGET_SHEETS:
        info = report["sheets"][sheet]
        kinds = info.get("kinds") or info.get("event_kinds") or {}
        if not kinds:
            continue

        def _kind_count(v):
            # kinds 值是 dict（含 match_count），event_kinds 值是 int
            return v["match_count"] if isinstance(v, dict) else v

        fixed = [k for k, v in kinds.items() if _kind_count(v) / total >= 0.5]
        optional = [k for k, v in kinds.items() if 0.2 <= _kind_count(v) / total < 0.5]
        drop = [k for k, v in kinds.items() if _kind_count(v) / total < 0.2]
        add(
            f"  - {info['title']:<8}: 固定(≥50%) {len(fixed)} | 可选(20-50%) {len(optional)} | "
            f"剔除(<20%) {len(drop)}"
        )
    add("（说明：固定=进固定表头；可选=你评估后决定；剔除=仅个别比赛才有的罕见字段）")
    add("")
    # 多名称写法的球队（翻译不一致重点对象）
    multi_name = [
        (tid, info) for tid, info in team_seed.items()
        if len(info["name_variants"]) > 1
    ]
    add(f"存在多种名称写法的球队数：{len(multi_name)}")
    add("（这些是需要人工确认规范名的重点，详见 team_master_seed.json）")
    add("")
    add("产物文件：")
    add("  - schema_report.json / schema_report.md : 固定表头依据")
    add("  - team_master_seed.json                 : 球队主数据初始表")
    add("  - scan_summary.txt                      : 本文件")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ============================================================================
# main
# ============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="足球数据库只读扫描，产出固定表头 Schema 报告"
    )
    parser.add_argument("--db", required=True, help="football.db 完整路径")
    parser.add_argument(
        "--limit", type=int, default=None,
        help="只扫描最近 N 场完场比赛（快速摸底）；不填则全量"
    )
    parser.add_argument(
        "--out", default=None,
        help="报告输出目录（默认：脚本所在目录/scan_report）"
    )
    parser.add_argument(
        "--dist", action="store_true",
        help="只输出带JSON比赛的月份分布（快速聚合），不做全量扫描"
    )
    parser.add_argument(
        "--valid", action="store_true",
        help="只看带 analysis 的有效完场（推荐），覆盖率基于有效完场计算"
    )
    args = parser.parse_args()

    db_path = os.path.abspath(args.db)

    if args.dist:
        run_dist_analysis(db_path)
        return
    if not os.path.exists(db_path):
        print(f"[错误] 数据库不存在：{db_path}", file=sys.stderr)
        sys.exit(1)

    if args.out:
        out_dir = os.path.abspath(args.out)
    else:
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scan_report")
    os.makedirs(out_dir, exist_ok=True)

    print(f"[信息] 数据库（只读）：{db_path}")
    print(f"[信息] 报告目录    ：{out_dir}")
    if args.limit:
        print(f"[信息] 采样模式    ：最近 {args.limit} 场")
    else:
        print("[信息] 全量扫描")
    if args.valid:
        print("[信息] 有效范围    ：仅带 analysis 的完场（覆盖率基于有效完场）")

    col = ScanCollector()
    processed = 0
    for row in iter_matches(db_path, limit=args.limit, only_analysis=args.valid):
        scan_match(row, col)
        processed += 1
        if processed % 2000 == 0:
            print(f"  ... 已扫描 {processed} 场")

    print(f"[信息] 扫描完成，共 {processed} 场")

    # 生成报告
    report = build_schema_report(col)
    team_seed = build_team_seed(col)

    with open(os.path.join(out_dir, "schema_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    with open(os.path.join(out_dir, "team_master_seed.json"), "w", encoding="utf-8") as f:
        json.dump(team_seed, f, ensure_ascii=False, indent=2)

    write_markdown(report, team_seed, os.path.join(out_dir, "schema_report.md"))
    write_summary_txt(report, team_seed, os.path.join(out_dir, "scan_summary.txt"))

    print("[完成] 报告已生成：")
    for name in ("schema_report.md", "schema_report.json",
                 "team_master_seed.json", "scan_summary.txt"):
        print(f"  - {os.path.join(out_dir, name)}")


if __name__ == "__main__":
    main()
