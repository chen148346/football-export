"""
db_reader.py - 数据库读取模块
================================
只读访问 SQLite 数据库，按筛选条件查询完场比赛数据。

核心功能：
1. 连接数据库（只读模式，uri=file:...?mode=ro）
2. 按日期范围、联赛、球队筛选完场比赛
3. 读取每场比赛的 shijian_json 和 analysis_json
4. 返回结构化数据供 Excel 导出使用

真实数据库表结构（以 football.db 为准）：
- matches (31列): id, sclass_id, sclass_name, sclass_color, match_time(14位),
                  match_date, home_team, away_team, home_rank, away_rank,
                  weather, round_info, is_neutrality,
                  latest_state_code, latest_state_text, latest_state_display,
                  latest_home_score, latest_away_score,
                  latest_home_half_score, latest_away_half_score,
                  latest_home_red, latest_away_red,
                  latest_home_yellow, latest_away_yellow,
                  latest_elapsed_min, latest_updated_at, created_at,
                  first_seen_state,
                  halftime_snapshot_id, min60_snapshot_id, fulltime_snapshot_id
- snapshots (13列): id, match_id, snapshot_type, state_code, state_text,
                    home_score, away_score, home_half_score, away_half_score,
                    elapsed_min, shijian_json, analysis_json, created_at
- reports (7列): id, match_id, snapshot_id, report_type, file_path,
                 file_name, created_at

关联方式：
  matches.fulltime_snapshot_id -> snapshots.id  (优先)
  若 fulltime_snapshot_id 为空，则 fallback 到 snapshots.match_id + snapshot_type='fulltime'
"""

import sqlite3
import os
import json
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field

from . import config
from . import json_parser


# ============================================================================
# 数据类定义
# ============================================================================

@dataclass
class MatchRecord:
    """一场比赛的完整数据记录"""
    # --- matches 表核心字段 ---
    match_id: int
    sclass_id: int
    sclass_name: str
    sclass_color: str
    match_time: str              # 14位字符串 YYYYMMDDHHMMSS
    match_date: str              # YYYY-MM-DD
    home_team: str
    away_team: str
    home_rank: int               # 主队排名
    away_rank: int               # 客队排名
    weather: str
    round_info: str
    is_neutrality: int           # 是否中立场 0/1
    
    # --- matches 表状态字段 ---
    state_code: int
    state_text: str
    home_score: int
    away_score: int
    home_half_score: int
    away_half_score: int
    home_red: int
    away_red: int
    home_yellow: int
    away_yellow: int
    elapsed_min: int
    
    # --- snapshots 表字段 ---
    snapshot_id: int
    snapshot_type: str
    
    # --- 解析后的 JSON 数据 ---
    shijian_json: Optional[dict]
    analysis_json: Optional[dict]
    
    # --- 解析后的结构化数据（由 build_structured_data 填充）---
    structured: Optional[dict] = field(default=None, repr=False)


# ============================================================================
# 数据库连接
# ============================================================================

def connect_db(db_path: str = None) -> sqlite3.Connection:
    """
    以只读模式连接 SQLite 数据库。
    
    使用 URI 模式 mode=ro 确保不会意外修改数据库。
    
    路径兼容性处理：
    - 自动将Windows反斜杠路径转为正斜杠（URI要求）
    - 使用绝对路径避免相对路径问题
    """
    if db_path is None:
        db_path = config.DEFAULT_DB_PATH
    
    # 转为绝对路径
    db_path = os.path.abspath(db_path)
    
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"数据库文件不存在: {db_path}")
    
    # 只读模式连接
    # URI格式要求使用正斜杠，Windows路径需转换
    db_uri_path = db_path.replace("\\", "/")
    conn = sqlite3.connect(f"file:{db_uri_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row  # 使结果可通过列名访问
    return conn


def get_db_info(db_path: str = None) -> dict:
    """
    获取数据库基本信息（表列表、各表行数、列结构）。
    
    用于诊断和验证数据库结构。
    """
    if db_path is None:
        db_path = config.DEFAULT_DB_PATH
    
    info = {"db_path": db_path, "tables": {}}
    
    if not os.path.exists(db_path):
        info["error"] = "数据库文件不存在"
        return info
    
    conn = connect_db(db_path)
    try:
        cursor = conn.cursor()
        
        # 获取所有表
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]
        
        for table in tables:
            table_info = {"columns": [], "row_count": 0}
            
            # 获取列结构
            cursor.execute(f"PRAGMA table_info({table})")
            table_info["columns"] = [
                {"name": row[1], "type": row[2], "notnull": row[3]}
                for row in cursor.fetchall()
            ]
            
            # 获取行数
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            table_info["row_count"] = cursor.fetchone()[0]
            
            info["tables"][table] = table_info
    finally:
        conn.close()
    
    return info


# ============================================================================
# 比赛查询
# ============================================================================

def query_matches(
    db_path: str = None,
    start_date: str = None,
    end_date: str = None,
    sclass_names: List[str] = None,
    team_name: str = None,
    state_code: int = config.STATE_CODE_FINISHED,
    require_snapshot: bool = True,
    limit: int = None,
) -> List[MatchRecord]:
    """
    按筛选条件查询完场比赛。
    
    参数：
        db_path: 数据库路径
        start_date: 开始日期 (YYYY-MM-DD)，None 表示不限
        end_date: 结束日期 (YYYY-MM-DD)，None 表示不限
        sclass_names: 联赛名称列表（多选），None 表示不限
        team_name: 球队名称（模糊搜索），None 表示不限
        state_code: 比赛状态码，默认 -1（完场）
        require_snapshot: 是否只返回有快照数据的比赛（默认True）
        limit: 最多返回多少条，None 表示不限
    
    返回：
        MatchRecord 列表，每条包含 matches + snapshots 数据
    
    查询逻辑：
        1. 从 matches 表筛选 state_code = -1 的完场比赛
        2. 优先用 matches.fulltime_snapshot_id 关联 snapshots 表
        3. 若 fulltime_snapshot_id 为空，fallback 到 snapshots.match_id + snapshot_type='fulltime'
        4. 按日期范围、联赛、球队进一步筛选
    """
    if db_path is None:
        db_path = config.DEFAULT_DB_PATH
    
    conn = connect_db(db_path)
    try:
        cursor = conn.cursor()
        
        # 构建 SQL 查询
        # 优先使用 matches.fulltime_snapshot_id 关联，fallback 到 snapshot_type='fulltime'
        # 使用 COALESCE 处理两种关联方式
        sql = """
            SELECT 
                m.id as match_id,
                m.sclass_id,
                m.sclass_name,
                m.sclass_color,
                m.match_time,
                m.match_date,
                m.home_team,
                m.away_team,
                m.home_rank,
                m.away_rank,
                m.weather,
                m.round_info,
                m.is_neutrality,
                m.latest_state_code as state_code,
                m.latest_state_text as state_text,
                m.latest_home_score as home_score,
                m.latest_away_score as away_score,
                m.latest_home_half_score as home_half_score,
                m.latest_away_half_score as away_half_score,
                m.latest_home_red as home_red,
                m.latest_away_red as away_red,
                m.latest_home_yellow as home_yellow,
                m.latest_away_yellow as away_yellow,
                m.latest_elapsed_min as elapsed_min,
                s.id as snapshot_id,
                s.snapshot_type,
                s.shijian_json,
                s.analysis_json
            FROM matches m
            LEFT JOIN snapshots s ON (s.id = m.fulltime_snapshot_id
                OR (m.fulltime_snapshot_id IS NULL 
                    AND s.match_id = m.id 
                    AND s.snapshot_type = ?))
            WHERE m.latest_state_code = ?
        """
        params = [config.SNAPSHOT_TYPE_FULLTIME, state_code]
        
        # 日期范围筛选（match_date 是 YYYY-MM-DD 格式）
        if start_date:
            sql += " AND m.match_date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND m.match_date <= ?"
            params.append(end_date)
        
        # 联赛筛选（多选）
        if sclass_names and len(sclass_names) > 0:
            placeholders = ",".join(["?"] * len(sclass_names))
            sql += f" AND m.sclass_name IN ({placeholders})"
            params.extend(sclass_names)
        
        # 球队名称模糊搜索（主队或客队）
        if team_name:
            sql += " AND (m.home_team LIKE ? OR m.away_team LIKE ?)"
            params.extend([f"%{team_name}%", f"%{team_name}%"])
        
        # V1.5修复: 只返回有快照数据的比赛
        # 原实现将条件放在WHERE子句，导致LEFT JOIN退化为INNER JOIN
        # 修复方案：改为在应用层过滤，保持LEFT JOIN语义正确
        # （require_snapshot=True时，在Python层过滤掉shijian_json为空的记录）
        
        sql += " ORDER BY m.match_time ASC"
        
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        
        matches = []
        for row in rows:
            # 解析 JSON
            shijian_json = json_parser.parse_json_safely(row["shijian_json"])
            analysis_json = json_parser.parse_json_safely(row["analysis_json"])
            
            # V1.5修复: 应用层过滤 - require_snapshot=True时跳过无快照数据的比赛
            # 保持LEFT JOIN语义正确，避免WHERE条件导致退化为INNER JOIN
            if require_snapshot and not shijian_json:
                continue
            
            # 过滤 odds 字段（二次保险）
            if shijian_json:
                shijian_json = json_parser.filter_odds(shijian_json)
            if analysis_json:
                analysis_json = json_parser.filter_odds(analysis_json)
            
            match = MatchRecord(
                match_id=row["match_id"],
                sclass_id=row["sclass_id"] or 0,
                sclass_name=row["sclass_name"] or "",
                sclass_color=row["sclass_color"] or "",
                match_time=row["match_time"] or "",
                match_date=row["match_date"] or "",
                home_team=row["home_team"] or "",
                away_team=row["away_team"] or "",
                home_rank=row["home_rank"] or 0,
                away_rank=row["away_rank"] or 0,
                weather=row["weather"] or "",
                round_info=row["round_info"] or "",
                is_neutrality=row["is_neutrality"] or 0,
                state_code=row["state_code"] if row["state_code"] is not None else 0,
                state_text=row["state_text"] or "",
                home_score=row["home_score"] or 0,
                away_score=row["away_score"] or 0,
                home_half_score=row["home_half_score"] or 0,
                away_half_score=row["away_half_score"] or 0,
                home_red=row["home_red"] or 0,
                away_red=row["away_red"] or 0,
                home_yellow=row["home_yellow"] or 0,
                away_yellow=row["away_yellow"] or 0,
                elapsed_min=row["elapsed_min"] or 0,
                snapshot_id=row["snapshot_id"] or 0,
                snapshot_type=row["snapshot_type"] or "",
                shijian_json=shijian_json,
                analysis_json=analysis_json,
            )
            matches.append(match)
        
        return matches
    finally:
        conn.close()


def get_sclass_list(db_path: str = None) -> List[str]:
    """获取数据库中所有联赛名称列表（用于前端筛选下拉框）"""
    if db_path is None:
        db_path = config.DEFAULT_DB_PATH
    
    conn = connect_db(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT sclass_name 
            FROM matches 
            WHERE sclass_name IS NOT NULL AND sclass_name != ''
            ORDER BY sclass_name
        """)
        return [row[0] for row in cursor.fetchall()]
    finally:
        conn.close()


def get_date_range(db_path: str = None) -> dict:
    """获取数据库中比赛的日期范围"""
    if db_path is None:
        db_path = config.DEFAULT_DB_PATH
    
    conn = connect_db(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT MIN(match_date), MAX(match_date) 
            FROM matches 
            WHERE match_date IS NOT NULL AND match_date != ''
        """)
        row = cursor.fetchone()
        return {"min_date": row[0] or "", "max_date": row[1] or ""}
    finally:
        conn.close()


def get_match_count_by_state(db_path: str = None) -> dict:
    """获取各状态的比赛数量统计（用于诊断）"""
    if db_path is None:
        db_path = config.DEFAULT_DB_PATH
    
    conn = connect_db(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT latest_state_code, latest_state_text, COUNT(*) as cnt
            FROM matches
            GROUP BY latest_state_code, latest_state_text
            ORDER BY cnt DESC
        """)
        result = {}
        for row in cursor.fetchall():
            result[str(row[0])] = {"text": row[1], "count": row[2]}
        return result
    finally:
        conn.close()


# ============================================================================
# V1.5 新增 - 非完场快照查询
# ============================================================================

def query_non_fulltime_snapshots(
    db_path: str = None,
    snapshot_filter: dict = None,
    include_fulltime: bool = False,
    start_date: str = None,
    end_date: str = None,
    sclass_names: list = None,
    team_name: str = None,
    limit: int = None,
) -> dict:
    """
    V1.5新增 - 查询非完场快照数据。
    
    参数：
        db_path: 数据库路径
        snapshot_filter: 快照筛选条件，两种模式：
            - {'mode': 'halftime'}  半场快照
            - {'mode': 'custom', 'min': 60, 'max': 70}  自定义分钟区间
        include_fulltime: 是否同时查询对应的完场快照（用于训练标签）
        start_date: 开始日期 YYYY-MM-DD
        end_date: 结束日期 YYYY-MM-DD
        sclass_names: 联赛名称列表
        team_name: 球队名称模糊搜索
        limit: 最多导出多少场比赛
    
    返回：
        {
            'prediction_snapshots': [MatchRecord, ...],  # 非完场快照（特征）
            'label_snapshots': [MatchRecord, ...],       # 完场快照（标签，仅include_fulltime=True时）
        }
    
    智能去重逻辑：
        同一场比赛在同一区间有多个快照时，选取最接近区间上限的快照。
        - halftime模式：选取elapsed_min最接近45的快照
        - custom模式：选取elapsed_min最接近max的快照
    """
    if db_path is None:
        db_path = config.DEFAULT_DB_PATH
    
    if snapshot_filter is None:
        snapshot_filter = {'mode': 'halftime'}
    
    mode = snapshot_filter.get('mode', 'halftime')
    
    conn = connect_db(db_path)
    try:
        cursor = conn.cursor()
        
        # 构建基础WHERE条件（联赛、日期、球队筛选穿透）
        where_clauses = []
        params = []
        
        if start_date:
            where_clauses.append("m.match_date >= ?")
            params.append(start_date)
        if end_date:
            where_clauses.append("m.match_date <= ?")
            params.append(end_date)
        if sclass_names:
            placeholders = ','.join('?' * len(sclass_names))
            where_clauses.append(f"m.sclass_name IN ({placeholders})")
            params.extend(sclass_names)
        if team_name:
            where_clauses.append("(m.home_team LIKE ? OR m.away_team LIKE ?)")
            params.extend([f'%{team_name}%', f'%{team_name}%'])
        
        where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        
        # ====================================================================
        # 第一步：查询非完场快照
        # ====================================================================
        
        if mode == 'halftime':
            # 半场模式：查询snapshot_type='halftime'的快照
            snapshot_where = "s.snapshot_type = 'halftime'"
            target_elapsed = 45
        elif mode == 'custom':
            # 自定义分钟区间模式
            min_val = snapshot_filter.get('min', 0)
            max_val = snapshot_filter.get('max', 90)
            snapshot_where = f"s.elapsed_min >= {int(min_val)} AND s.elapsed_min <= {int(max_val)} AND s.snapshot_type != 'fulltime'"
            target_elapsed = max_val
        else:
            snapshot_where = "s.snapshot_type = 'halftime'"
            target_elapsed = 45
        
        # 查询非完场快照（关联matches表应用筛选条件）
        sql = f"""
            SELECT s.id, s.match_id, s.snapshot_type, s.state_code, s.state_text,
                   s.home_score, s.away_score, s.home_half_score, s.away_half_score,
                   s.elapsed_min, s.shijian_json, s.analysis_json, s.created_at,
                   m.sclass_name, m.match_time, m.match_date, m.home_team, m.away_team,
                   m.home_rank, m.away_rank, m.weather, m.round_info, m.is_neutrality,
                   m.latest_home_red, m.latest_away_red,
                   m.latest_home_yellow, m.latest_away_yellow,
                   m.fulltime_snapshot_id
            FROM snapshots s
            JOIN matches m ON s.match_id = m.id
            WHERE {snapshot_where}
        """
        if where_clauses:
            sql += " AND " + " AND ".join(where_clauses)
        sql += " ORDER BY s.match_id, ABS(s.elapsed_min - ?) ASC"
        params_with_target = params + [target_elapsed]
        
        cursor.execute(sql, params_with_target)
        rows = cursor.fetchall()
        
        # 智能去重：同一场比赛只保留最接近区间上限的快照
        seen_matches = {}
        for row in rows:
            match_id = row[1]  # match_id
            elapsed = row[9] if row[9] is not None else 0  # elapsed_min
            if match_id not in seen_matches:
                seen_matches[match_id] = row
            else:
                # 比较与目标elapsed的距离，取更近的
                existing_elapsed = seen_matches[match_id][9] if seen_matches[match_id][9] is not None else 0
                if abs(elapsed - target_elapsed) < abs(existing_elapsed - target_elapsed):
                    seen_matches[match_id] = row
        
        prediction_records = []
        for match_id, row in seen_matches.items():
            record = _row_to_match_record(row)
            if record:
                prediction_records.append(record)
        
        # 应用limit
        if limit and len(prediction_records) > limit:
            prediction_records = prediction_records[:limit]
        
        # ====================================================================
        # 第二步：查询对应的完场快照（如果include_fulltime=True）
        # ====================================================================
        label_records = []
        if include_fulltime and prediction_records:
            match_ids = [r.match_id for r in prediction_records]
            placeholders = ','.join('?' * len(match_ids))
            
            cursor.execute(f"""
                SELECT s.id, s.match_id, s.snapshot_type, s.state_code, s.state_text,
                       s.home_score, s.away_score, s.home_half_score, s.away_half_score,
                       s.elapsed_min, s.shijian_json, s.analysis_json, s.created_at,
                       m.sclass_name, m.match_time, m.match_date, m.home_team, m.away_team,
                       m.home_rank, m.away_rank, m.weather, m.round_info, m.is_neutrality,
                       m.latest_home_red, m.latest_away_red,
                       m.latest_home_yellow, m.latest_away_yellow,
                       m.fulltime_snapshot_id
                FROM snapshots s
                JOIN matches m ON s.match_id = m.id
                WHERE s.snapshot_type = 'fulltime' AND s.match_id IN ({placeholders})
                ORDER BY s.match_id
            """, match_ids)
            
            label_rows = cursor.fetchall()
            for row in label_rows:
                record = _row_to_match_record(row)
                if record:
                    label_records.append(record)
        
        return {
            'prediction_snapshots': prediction_records,
            'label_snapshots': label_records,
        }
    
    finally:
        conn.close()


def _row_to_match_record(row) -> Optional[MatchRecord]:
    """将数据库行转换为MatchRecord对象（V1.5新增辅助函数）"""
    try:
        # 解析JSON
        shijian_json = None
        analysis_json = None
        if row[10]:
            try:
                shijian_json = json.loads(row[10])
            except (json.JSONDecodeError, TypeError):
                pass
        if row[11]:
            try:
                analysis_json = json.loads(row[11])
            except (json.JSONDecodeError, TypeError):
                pass
        
        return MatchRecord(
            match_id=row[1],
            sclass_id=0,  # V1.5: sclass_id不在查询中，默认0
            sclass_name=row[13] or "",
            sclass_color="",  # V1.5: sclass_color不在查询中，默认空
            match_time=row[14] or "",
            match_date=row[15] or "",
            home_team=row[16] or "",
            away_team=row[17] or "",
            home_rank=row[18] or 0,
            away_rank=row[19] or 0,
            weather=row[20] or "",
            round_info=row[21] or "",
            is_neutrality=row[22] or 0,
            state_code=row[3] if row[3] is not None else 0,
            state_text=row[4] or "",
            home_score=row[5] if row[5] is not None else 0,
            away_score=row[6] if row[6] is not None else 0,
            home_half_score=row[7] if row[7] is not None else 0,
            away_half_score=row[8] if row[8] is not None else 0,
            home_red=row[23] or 0,
            away_red=row[24] or 0,
            home_yellow=row[25] or 0,
            away_yellow=row[26] or 0,
            elapsed_min=row[9] or 0,
            snapshot_id=row[0],
            snapshot_type=row[2] or "",
            shijian_json=shijian_json,
            analysis_json=analysis_json,
            structured=None,
        )
    except Exception as e:
        print(f"[WARNING] MatchRecord转换失败: {e}")
        return None
