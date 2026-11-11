"""
足球比赛数据文档分析系统 V2.6.3 - 数据库模块
简化设计：3张表（matches / snapshots / reports）+ monitor_tasks表

[V2.5.5] 变更说明：
- 删除 update_match_min60_snapshot 死函数（min60快照不回写matches表，设计决策）
"""
import sqlite3
import json
import os
import logging
from datetime import datetime
from config import DB_PATH

logger = logging.getLogger(__name__)


def get_conn():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """初始化数据库，创建表结构"""
    conn = get_conn()
    c = conn.cursor()

    # 1. matches 表 - 比赛基本信息 + 最新状态（每次刷新更新）
    c.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY,
            sclass_id INTEGER,
            sclass_name TEXT,
            sclass_color TEXT,
            match_time TEXT,
            match_date TEXT,
            home_team TEXT,
            away_team TEXT,
            home_rank INTEGER,
            away_rank INTEGER,
            weather TEXT,
            round_info TEXT,
            is_neutrality INTEGER DEFAULT 0,
            latest_state_code INTEGER,
            latest_state_text TEXT,
            latest_state_display TEXT,
            latest_home_score INTEGER,
            latest_away_score INTEGER,
            latest_home_half_score INTEGER,
            latest_away_half_score INTEGER,
            latest_home_red INTEGER,
            latest_away_red INTEGER,
            latest_home_yellow INTEGER,
            latest_away_yellow INTEGER,
            latest_elapsed_min INTEGER,
            latest_updated_at TEXT,
            created_at TEXT,
            first_seen_state INTEGER,
            halftime_snapshot_id INTEGER,
            min60_snapshot_id INTEGER,
            fulltime_snapshot_id INTEGER
        )
    """)

    # 2. snapshots 表 - 数据快照（在关键时点保存完整JSON）
    c.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER NOT NULL,
            snapshot_type TEXT,
            state_code INTEGER,
            state_text TEXT,
            home_score INTEGER,
            away_score INTEGER,
            home_half_score INTEGER,
            away_half_score INTEGER,
            elapsed_min INTEGER,
            shijian_json TEXT,
            analysis_json TEXT,
            created_at TEXT,
            FOREIGN KEY (match_id) REFERENCES matches(id)
        )
    """)

    # 3. reports 表 - 报告记录
    c.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER NOT NULL,
            snapshot_id INTEGER,
            report_type TEXT,
            file_path TEXT,
            file_name TEXT,
            created_at TEXT,
            FOREIGN KEY (match_id) REFERENCES matches(id),
            FOREIGN KEY (snapshot_id) REFERENCES snapshots(id)
        )
    """)

    # 创建索引
    c.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_match ON snapshots(match_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_type ON snapshots(match_id, snapshot_type)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_reports_match ON reports(match_id)")

    # V2.4.11: 性能优化索引（应对数据量增长，确保首页加载<2秒）
    # 1. 首页时间窗口查询专用索引（核心）
    #    优化 WHERE match_time BETWEEN ? AND ? ORDER BY match_time ASC
    c.execute("CREATE INDEX IF NOT EXISTS idx_matches_time_state ON matches(match_time, latest_state_code)")

    # 2. 联赛筛选+时间窗口复合索引
    #    优化 WHERE sclass_name = ? AND match_time BETWEEN ? AND ?
    c.execute("CREATE INDEX IF NOT EXISTS idx_matches_sclass_time ON matches(sclass_name, match_time)")

    # 3. 完场比赛查询索引（用于导出功能）
    #    优化 WHERE latest_state_code = -1 AND match_time BETWEEN ? AND ?
    c.execute("CREATE INDEX IF NOT EXISTS idx_matches_finished_time ON matches(latest_state_code, match_time)")

    print("[V2.4.11] 性能优化索引已创建：idx_matches_time_state, idx_matches_sclass_time, idx_matches_finished_time")

    # [V2.5.2] 数据库导入清理重建专用索引（保障批量UPDATE性能）
    # 1. 快照清理与外键重建核心索引：覆盖(match_id, snapshot_type, created_at)三列
    #    优化 DELETE重复快照 和 UPDATE外键 的子查询匹配
    c.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_match_type_created ON snapshots(match_id, snapshot_type, created_at)")

    # 2. 比赛表外键字段独立索引：加速悬空指针检测
    #    优化 WHERE halftime_snapshot_id NOT IN (SELECT id FROM snapshots)
    c.execute("CREATE INDEX IF NOT EXISTS idx_matches_halftime_snap ON matches(halftime_snapshot_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_matches_fulltime_snap ON matches(fulltime_snapshot_id)")

    print("[V2.5.2] 导入清理重建索引已创建：idx_snapshots_match_type_created, idx_matches_halftime_snap, idx_matches_fulltime_snap")

    # 数据库迁移：为已有数据库添加新字段（如果不存在）
    # 检查 matches 表的列
    columns = [row[1] for row in c.execute("PRAGMA table_info(matches)").fetchall()]
    if 'first_seen_state' not in columns:
        c.execute("ALTER TABLE matches ADD COLUMN first_seen_state INTEGER")
    if 'min60_snapshot_id' not in columns:
        c.execute("ALTER TABLE matches ADD COLUMN min60_snapshot_id INTEGER")
    if 'latest_state_display' not in columns:
        c.execute("ALTER TABLE matches ADD COLUMN latest_state_display TEXT")

    # V2.4.15: 新增 monitor_tasks 监控任务表（定时快照监控功能）
    # 安全性：CREATE TABLE IF NOT EXISTS，不影响现有matches/snapshots/reports表
    c.execute("""
        CREATE TABLE IF NOT EXISTS monitor_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER NOT NULL,
            ht_status INTEGER DEFAULT 0,
            min60_status INTEGER DEFAULT 0,
            min75_status INTEGER DEFAULT 0,
            ft_status INTEGER DEFAULT 0,
            enable_min60 INTEGER DEFAULT 0,
            enable_min75 INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT,
            FOREIGN KEY (match_id) REFERENCES matches(id)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_monitor_tasks_match_id ON monitor_tasks(match_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_monitor_tasks_active ON monitor_tasks(ft_status) WHERE ft_status = 0")
    print("[V2.4.15] monitor_tasks 监控任务表已创建")

    # [V2.6.3] 为已有数据库添加 enable_min60/enable_min75 字段
    columns = [row[1] for row in c.execute("PRAGMA table_info(monitor_tasks)").fetchall()]
    if 'enable_min60' not in columns:
        c.execute("ALTER TABLE monitor_tasks ADD COLUMN enable_min60 INTEGER DEFAULT 0")
    if 'enable_min75' not in columns:
        c.execute("ALTER TABLE monitor_tasks ADD COLUMN enable_min75 INTEGER DEFAULT 0")

    # [V2.5.5] 任务6：自动监控联赛配置表
    c.execute("""
        CREATE TABLE IF NOT EXISTS auto_monitor_leagues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sclass_name TEXT NOT NULL UNIQUE,
            created_at TEXT
        )
    """)
    print("[V2.5.5] auto_monitor_leagues 自动监控联赛配置表已创建")

    conn.commit()
    conn.close()


def upsert_match(match_data):
    """插入或更新比赛信息"""
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 检查是否已存在
    row = c.execute("SELECT id FROM matches WHERE id = ?", (match_data['id'],)).fetchone()

    if row:
        # 更新（保留 weather, round_info 如果新数据为空）
        updates = []
        params = []
        for k, v in match_data.items():
            if k == 'id':
                continue
            if v is not None:
                updates.append(f"{k} = ?")
                params.append(v)
        updates.append("latest_updated_at = ?")
        params.append(now)
        params.append(match_data['id'])
        c.execute(f"UPDATE matches SET {', '.join(updates)} WHERE id = ?", params)
    else:
        # 插入
        match_data['created_at'] = now
        match_data['latest_updated_at'] = now
        cols = ', '.join(match_data.keys())
        placeholders = ', '.join(['?'] * len(match_data))
        c.execute(f"INSERT INTO matches ({cols}) VALUES ({placeholders})", list(match_data.values()))

    conn.commit()
    conn.close()


def update_match(match_data):
    """更新比赛信息（别名）"""
    upsert_match(match_data)


def get_match(match_id):
    """获取单场比赛信息"""
    conn = get_conn()
    row = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_matches(sclass_id=None, state_code=None, date=None):
    """获取比赛列表"""
    conn = get_conn()
    query = "SELECT * FROM matches WHERE 1=1"
    params = []
    if sclass_id:
        query += " AND sclass_id = ?"
        params.append(sclass_id)
    if state_code is not None:
        query += " AND latest_state_code = ?"
        params.append(state_code)
    if date:
        query += " AND match_date = ?"
        params.append(date)
    query += " ORDER BY match_time ASC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_matches():
    """获取所有比赛"""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM matches ORDER BY match_time ASC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_matches_in_time_window(start_time_str, end_time_str):
    """
    V2.4.11: 获取时间窗口内的比赛（±10小时过滤）
    性能优化：只查询首页渲染需要的核心字段，禁止SELECT *和JOIN大字段表
    利用idx_matches_time_state索引加速
    """
    conn = get_conn()
    print(f"[V2.4.11时间窗口] 查询范围: {start_time_str} 至 {end_time_str}")
    # V2.4.11: 只查询首页需要的10-15个核心字段，避免加载大字段
    rows = conn.execute(
        """SELECT id, sclass_id, sclass_name, sclass_color, match_time, match_date,
                  home_team, away_team, home_rank, away_rank,
                  latest_state_code, latest_state_text, latest_state_display,
                  latest_home_score, latest_away_score,
                  latest_home_half_score, latest_away_half_score,
                  latest_home_red, latest_away_red,
                  latest_home_yellow, latest_away_yellow, latest_elapsed_min
           FROM matches
           WHERE match_time >= ? AND match_time <= ?
           ORDER BY match_time ASC""",
        (start_time_str, end_time_str)
    ).fetchall()
    conn.close()
    print(f"[V2.4.11时间窗口] 查询结果: {len(rows)} 场比赛")
    return [dict(r) for r in rows]


def repair_match_date_field():
    """
    V2.4.9新增：修复matches表中match_date为NULL的字段
    从match_time前8位提取日期，格式化为YYYY-MM-DD
    返回: 修复的记录数
    """
    conn = get_conn()
    need_fix = conn.execute(
        "SELECT COUNT(*) as c FROM matches WHERE (match_date IS NULL OR match_date = '') AND match_time IS NOT NULL AND length(match_time) >= 8"
    ).fetchone()['c']

    if need_fix > 0:
        conn.execute("""
            UPDATE matches
            SET match_date = substr(match_time, 1, 4) || '-' ||
                             substr(match_time, 5, 2) || '-' ||
                             substr(match_time, 7, 2)
            WHERE (match_date IS NULL OR match_date = '')
              AND match_time IS NOT NULL
              AND length(match_time) >= 8
        """)
        conn.commit()
        print(f"[V2.4.9修复] 已修复 {need_fix} 条match_date为空的记录")
    else:
        print(f"[V2.4.9修复] 无需修复，所有match_date字段均有值")

    conn.close()
    return need_fix


def sync_matches(matches_data, do_maintenance=False):
    """
    同步比赛列表 - V2.4.11: 数据永久保留，只增不删+状态更新

    V2.4.11重大变更：
    - 废除7天自动清理机制，所有历史数据永久保留
    - 不再删除任何matches/snapshots/reports记录
    - 仅对titan007列表中的比赛做INSERT或UPDATE
    - 已下架的历史比赛及其关联数据原封不动保留
    - 同步成功后执行VACUUM和ANALYZE维护数据库

    [V2.6.0] 变更：VACUUM+ANALYZE 改为按需执行
    - do_maintenance=False（默认）：不执行VACUUM+ANALYZE（手动刷新时）
    - do_maintenance=True：执行VACUUM+ANALYZE（定时自动刷新时）

    伪代码逻辑：
    def sync_matches(new_matches_from_web):
        existing_ids = get_all_match_ids()
        for match in new_matches_from_web:
            if match['id'] in existing_ids:
                update_match_status(match)  # 仅更新状态、比分等易变字段
            else:
                insert_new_match(match)
        # 【已删除】原DELETE逻辑全部移除
    """
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    current_ids = set()
    for m in matches_data:
        current_ids.add(m['id'])

    # 获取现有比赛ID和weather/round_info（用于保留已有数据）
    existing_rows = c.execute("SELECT id, weather, round_info FROM matches").fetchall()
    existing_ids = {row['id'] for row in existing_rows}
    existing_weather = {row['id']: (row['weather'] or '', row['round_info'] or '') for row in existing_rows}

    new_count = len(current_ids - existing_ids)
    update_count = len(current_ids & existing_ids)
    print(f"[V2.4.11同步] 抓取到 {len(current_ids)} 场比赛，数据库现有 {len(existing_ids)} 场（新增{new_count}场，更新{update_count}场）")
    print(f"[V2.4.11同步] 数据永久保留模式：不删除任何历史数据")

    # V2.4.11: 已废除所有DELETE逻辑
    # 原代码中计算 ids_to_delete 并执行 DELETE FROM matches/snapshots/reports 的逻辑已全部移除
    # 历史比赛及其关联的snapshots和reports原封不动保留

    # 插入/更新当前列表中的比赛
    for m in matches_data:
        # 确保match_date有值，从match_time提取
        if (not m.get('match_date')) and m.get('match_time') and len(m['match_time']) >= 8:
            mt = m['match_time']
            m['match_date'] = f"{mt[0:4]}-{mt[4:6]}-{mt[6:8]}"

        # 保留已有的 weather/round_info（如果新数据为空）
        if m['id'] in existing_weather:
            old_weather, old_round = existing_weather[m['id']]
            if not m.get('weather'):
                m['weather'] = old_weather
            if not m.get('round_info'):
                m['round_info'] = old_round

        if m['id'] in existing_ids:
            # 已存在：仅更新状态、比分等易变字段
            updates = []
            params = []
            for k, v in m.items():
                if k == 'id':
                    continue
                if v is not None:
                    updates.append(f"{k} = ?")
                    params.append(v)
            updates.append("latest_updated_at = ?")
            params.append(now)
            params.append(m['id'])
            c.execute(f"UPDATE matches SET {', '.join(updates)} WHERE id = ?", params)
        else:
            # 不存在：插入新记录
            m['created_at'] = now
            m['latest_updated_at'] = now
            cols = ', '.join(m.keys())
            placeholders = ', '.join(['?'] * len(m))
            c.execute(f"INSERT INTO matches ({cols}) VALUES ({placeholders})", list(m.values()))

    conn.commit()
    conn.close()

    # [V2.6.0] VACUUM+ANALYZE 改为按需执行（仅定时自动刷新时执行，手动刷新不执行）
    if not do_maintenance:
        return len(matches_data)

    # V2.4.11: 同步成功后执行VACUUM和ANALYZE维护数据库
    # VACUUM回收空闲空间（解决SQLite频繁UPDATE导致文件虚胖）
    # ANALYZE更新查询优化器统计信息（提升索引命中率）
    # 注意：VACUUM不能在事务中执行，需单独连接
    try:
        import os
        db_size_before = os.path.getsize(DB_PATH) / 1024 / 1024
        maint_conn = get_conn()
        maint_conn.execute("ANALYZE")
        maint_conn.commit()
        maint_conn.close()
        # VACUUM需要autocommit模式
        vacuum_conn = sqlite3.connect(DB_PATH, isolation_level=None)
        vacuum_conn.execute("VACUUM")
        vacuum_conn.close()
        db_size_after = os.path.getsize(DB_PATH) / 1024 / 1024
        print(f"[V2.4.11维护] VACUUM+ANALYZE完成，数据库体积: {db_size_before:.1f}MB → {db_size_after:.1f}MB")
    except Exception as e:
        print(f"[V2.4.11维护] VACUUM/ANALYZE失败（不影响数据）: {e}")

    return len(matches_data)


def get_sclass_list():
    """获取联赛列表（用于筛选下拉框）
    [V2.5.9] 任务1：修复历史联赛缺失问题
    原SQL: WHERE sclass_id IS NOT NULL（sclass_id为NULL的历史联赛被过滤）
    新SQL: WHERE sclass_name IS NOT NULL AND sclass_name != ''（以sclass_name为准）
    """
    conn = get_conn()
    rows = conn.execute("""
        SELECT DISTINCT sclass_id, sclass_name, sclass_color
        FROM matches
        WHERE sclass_name IS NOT NULL AND sclass_name != ''
        ORDER BY sclass_name ASC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# V2.4.11: 联赛列表内存缓存（避免每次首页加载都查询DISTINCT）
_sclass_cache = None
_sclass_cache_time = None

def get_sclass_names_cached():
    """
    V2.4.11: 获取所有联赛名称（内存缓存版）
    缓存在首次调用或刷新数据后更新，避免实时查询数据库DISTINCT
    返回: list of str，联赛名称列表
    """
    global _sclass_cache
    if _sclass_cache is not None:
        return _sclass_cache
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT sclass_name FROM matches WHERE sclass_name IS NOT NULL AND sclass_name != ''"
    ).fetchall()
    conn.close()
    _sclass_cache = [row['sclass_name'] for row in rows]
    return _sclass_cache

def invalidate_sclass_cache():
    """V2.4.11: 清除联赛列表缓存（刷新数据后调用）"""
    global _sclass_cache
    _sclass_cache = None
    print("[V2.4.11缓存] 联赛列表缓存已清除")


def create_snapshot(snapshot_data):
    """创建数据快照"""
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    snapshot_data['created_at'] = now
    cols = ', '.join(snapshot_data.keys())
    placeholders = ', '.join(['?'] * len(snapshot_data))
    c.execute(f"INSERT INTO snapshots ({cols}) VALUES ({placeholders})", list(snapshot_data.values()))
    snapshot_id = c.lastrowid

    # 更新 matches 表中的快照ID
    match_id = snapshot_data.get('match_id')
    snap_type = snapshot_data.get('snapshot_type')
    if snap_type == 'halftime':
        c.execute("UPDATE matches SET halftime_snapshot_id = ? WHERE id = ?", (snapshot_id, match_id))
    elif snap_type == 'fulltime':
        c.execute("UPDATE matches SET fulltime_snapshot_id = ? WHERE id = ?", (snapshot_id, match_id))

    conn.commit()
    conn.close()
    return snapshot_id


def get_snapshot(snapshot_id):
    """获取单个快照"""
    conn = get_conn()
    row = conn.execute("SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_snapshot_by_match(match_id, snapshot_type=None):
    """获取比赛的快照"""
    conn = get_conn()
    if snapshot_type:
        row = conn.execute(
            "SELECT * FROM snapshots WHERE match_id = ? AND snapshot_type = ? ORDER BY created_at DESC LIMIT 1",
            (match_id, snapshot_type)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM snapshots WHERE match_id = ? ORDER BY created_at DESC LIMIT 1",
            (match_id,)
        ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_fulltime_snapshot_cached(match_id):
    """
    V2.0 新增：获取完场快照（本地缓存查询）
    如果本地数据库已有该比赛的完场快照，直接返回；否则返回None（需从网页抓取）

    返回: snapshot dict 或 None
    """
    return get_snapshot_by_match(match_id, 'fulltime')


def get_or_create_match(match_id, sclass_name='', home_team='', away_team='', match_time=''):
    """
    V2.0 新增：获取或创建比赛记录（用于批量导入时）
    如果比赛不存在则创建一条基本记录
    """
    conn = get_conn()
    row = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
    if row:
        conn.close()
        return dict(row)

    # 创建新比赛记录
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn.execute("""
        INSERT INTO matches (id, sclass_name, home_team, away_team, match_time,
                            latest_state_code, latest_state_text, created_at, latest_updated_at)
        VALUES (?, ?, ?, ?, ?, 0, '未开始', ?, ?)
    """, (match_id, sclass_name, home_team, away_team, match_time, now, now))
    conn.commit()
    row = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_snapshots_by_match(match_id):
    """获取比赛的所有快照"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM snapshots WHERE match_id = ? ORDER BY created_at DESC",
        (match_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_match_halftime_snapshot(match_id, snapshot_id):
    """更新比赛的半场快照ID"""
    conn = get_conn()
    conn.execute(
        "UPDATE matches SET halftime_snapshot_id = ? WHERE id = ?",
        (snapshot_id, match_id)
    )
    conn.commit()
    conn.close()


# [V2.5.5] 已删除 update_match_min60_snapshot 函数
# 原因：min60快照不回写matches表（设计决策），该函数从未被调用，属于死代码


def update_match_fulltime_snapshot(match_id, snapshot_id):
    """更新比赛的全场快照ID"""
    conn = get_conn()
    conn.execute(
        "UPDATE matches SET fulltime_snapshot_id = ? WHERE id = ?",
        (snapshot_id, match_id)
    )
    conn.commit()
    conn.close()


def update_first_seen_state(match_id, state_code):
    """更新比赛的首次发现状态（仅当尚未设置时）"""
    conn = get_conn()
    conn.execute(
        "UPDATE matches SET first_seen_state = ? WHERE id = ? AND first_seen_state IS NULL",
        (state_code, match_id)
    )
    conn.commit()
    conn.close()


def create_report(report_data):
    """创建报告记录"""
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    report_data['created_at'] = now
    cols = ', '.join(report_data.keys())
    placeholders = ', '.join(['?'] * len(report_data))
    c.execute(f"INSERT INTO reports ({cols}) VALUES ({placeholders})", list(report_data.values()))
    report_id = c.lastrowid
    conn.commit()
    conn.close()
    return report_id


def get_reports(match_id=None):
    """获取报告列表"""
    conn = get_conn()
    if match_id:
        rows = conn.execute(
            "SELECT * FROM reports WHERE match_id = ? ORDER BY created_at DESC",
            (match_id,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM reports ORDER BY created_at DESC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_report(report_id):
    """获取单个报告"""
    conn = get_conn()
    row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_report(report_id):
    """删除报告记录"""
    conn = get_conn()
    conn.execute("DELETE FROM reports WHERE id = ?", (report_id,))
    conn.commit()
    conn.close()


# ==================== V2.4.9: Excel导出相关查询函数 ====================

def get_fulltime_snapshots_with_match_info(date_start=None, date_end=None, sclass_names=None):
    """
    V2.4.9: 获取完场快照及关联的比赛信息（用于训练模式导出）
    日期查询双重保险：match_time前8位 + match_date回退
    """
    conn = get_conn()
    query = """
        SELECT s.id as snapshot_id, s.match_id, s.snapshot_type, s.state_code,
               s.state_text, s.home_score, s.away_score, s.home_half_score,
               s.away_half_score, s.elapsed_min, s.shijian_json, s.analysis_json,
               s.created_at as snapshot_created_at,
               m.sclass_name, m.match_time, m.match_date, m.home_team, m.away_team,
               m.home_rank, m.away_rank, m.weather, m.round_info
        FROM snapshots s
        JOIN matches m ON s.match_id = m.id
        WHERE s.snapshot_type = 'fulltime'
    """
    params = []
    if date_start:
        date_start_compact = date_start.replace('-', '')
        query += " AND (substr(m.match_time,1,8) >= ? OR (m.match_time IS NULL AND m.match_date >= ?))"
        params.append(date_start_compact)
        params.append(date_start)
    if date_end:
        date_end_compact = date_end.replace('-', '')
        query += " AND (substr(m.match_time,1,8) <= ? OR (m.match_time IS NULL AND m.match_date <= ?))"
        params.append(date_end_compact)
        params.append(date_end)
    if sclass_names:
        cleaned_names = [s.strip() for s in sclass_names if s and s.strip()]
        if cleaned_names:
            placeholders = ','.join(['?'] * len(cleaned_names))
            query += f" AND m.sclass_name IN ({placeholders})"
            params.extend(cleaned_names)
    query += " ORDER BY m.match_time DESC"

    print(f"[V2.4.9导出SQL] {query}")
    print(f"[V2.4.9导出参数] {params}")

    rows = conn.execute(query, params).fetchall()
    print(f"[V2.4.9导出结果] 查询到 {len(rows)} 条完场快照")
    conn.close()
    return [dict(r) for r in rows]


def get_snapshots_by_match_ids(match_ids, snapshot_types=None):
    """
    V2.4.9: 按比赛ID列表获取快照（用于预测模式导出）
    """
    if not match_ids:
        return []
    conn = get_conn()
    results = []
    for mid in match_ids:
        row = None
        if snapshot_types:
            for st in snapshot_types:
                row = conn.execute(
                    """SELECT s.*, m.sclass_name, m.match_time, m.match_date,
                              m.home_team, m.away_team, m.home_rank, m.away_rank,
                              m.weather, m.round_info
                       FROM snapshots s JOIN matches m ON s.match_id = m.id
                       WHERE s.match_id = ? AND s.snapshot_type = ?
                       ORDER BY s.created_at DESC LIMIT 1""",
                    (mid, st)
                ).fetchone()
                if row:
                    break
        else:
            row = conn.execute(
                """SELECT s.*, m.sclass_name, m.match_time, m.match_date,
                          m.home_team, m.away_team, m.home_rank, m.away_rank,
                          m.weather, m.round_info
                   FROM snapshots s JOIN matches m ON s.match_id = m.id
                   WHERE s.match_id = ?
                   ORDER BY s.created_at DESC LIMIT 1""",
                (mid,)
            ).fetchone()
        if row:
            results.append(dict(row))
    conn.close()
    return results


def get_finished_matches_in_time_window(start_str, end_str):
    """
    V2.4.9: 获取时间窗口内的完场比赛（用于预测模式默认匹配）
    """
    conn = get_conn()
    rows = conn.execute(
        """SELECT * FROM matches
           WHERE match_time >= ? AND match_time <= ?
           AND latest_state_code = -1
           ORDER BY match_time DESC""",
        (start_str, end_str)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ==================== V2.4.15: monitor_tasks 监控任务表 CRUD ====================

def add_monitor_task(match_id, enable_min60=0, enable_min75=0):
    """
    V2.4.15: 添加监控任务
    如果该match_id已有监控任务且ft_status=0（进行中），则不重复添加
    [V2.6.3] 增加 enable_min60/enable_min75 参数，默认关闭60/75分钟快照
    返回: (success: bool, message: str)
    """
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 检查比赛是否存在
    match = c.execute("SELECT id, latest_state_code, home_team, away_team FROM matches WHERE id = ?", (match_id,)).fetchone()
    if not match:
        conn.close()
        return False, f"比赛ID {match_id} 不存在，请先在首页同步数据"

    # 检查是否已完场（架构师答复1：已完场拒绝监控）
    if match['latest_state_code'] == -1:
        conn.close()
        return False, f"比赛 {match['home_team']} vs {match['away_team']} 已完场，无需监控"

    # 检查是否已有进行中的监控任务
    existing = c.execute("SELECT id, ft_status FROM monitor_tasks WHERE match_id = ? ORDER BY id DESC LIMIT 1", (match_id,)).fetchone()
    if existing and existing['ft_status'] == 0:
        conn.close()
        return False, f"比赛 {match_id} 已在监控队列中"

    # 创建新监控任务
    c.execute("""
        INSERT INTO monitor_tasks (match_id, ht_status, min60_status, min75_status, ft_status, enable_min60, enable_min75, created_at, updated_at)
        VALUES (?, 0, 0, 0, 0, ?, ?, ?, ?)
    """, (match_id, enable_min60, enable_min75, now, now))
    conn.commit()
    conn.close()
    return True, f"比赛 {match['home_team']} vs {match['away_team']} 已加入监控队列"


def get_active_monitor_tasks():
    """V2.4.15: 获取所有进行中的监控任务（ft_status=0）"""
    conn = get_conn()
    rows = conn.execute("""
        SELECT mt.*, m.home_team, m.away_team, m.latest_state_code, m.latest_state_text,
               m.latest_elapsed_min, m.match_time, m.sclass_name
        FROM monitor_tasks mt
        JOIN matches m ON mt.match_id = m.id
        WHERE mt.ft_status = 0
        ORDER BY mt.created_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_monitor_tasks(limit=100):
    """V2.4.15: 获取所有监控任务（含历史），用于前端展示"""
    conn = get_conn()
    rows = conn.execute("""
        SELECT mt.*, m.home_team, m.away_team, m.latest_state_code, m.latest_state_text,
               m.latest_elapsed_min, m.match_time, m.sclass_name
        FROM monitor_tasks mt
        JOIN matches m ON mt.match_id = m.id
        ORDER BY mt.created_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ==================== V2.5.1: 监控列表优化查询 ====================

def get_all_monitor_tasks_v251(sclass_names=None, limit=200, date_start=None, date_end=None):
    """
    V2.5.1: 获取监控任务列表（支持联赛筛选）
    V2.5.4: 排序逻辑与主页面统一（状态大类优先 + match_time正序）
            补充比分等基础字段，与主页面保持一致
    [V2.5.5] 任务5：增加时间段筛选（date_start/date_end，14位格式YYYYMMDDHHMMSS）

    参数:
        sclass_names: 联赛名称列表（多选），None或空列表表示全部
        limit: 返回条数上限
        date_start: 起始时间（14位YYYYMMDDHHMMSS），None表示不限制
        date_end: 结束时间（14位YYYYMMDDHHMMSS），None表示不限制

    返回: list[dict]
    """
    from config import STATE_SORT_PRIORITY

    conn = get_conn()

    # [V2.5.5] 任务5：构建动态WHERE条件
    where_clauses = []
    params = []

    if sclass_names:
        placeholders = ','.join(['?'] * len(sclass_names))
        where_clauses.append(f"m.sclass_name IN ({placeholders})")
        params.extend(list(sclass_names))

    if date_start:
        where_clauses.append("m.match_time >= ?")
        params.append(date_start)
    if date_end:
        where_clauses.append("m.match_time <= ?")
        params.append(date_end)

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    sql = f"""
        SELECT mt.*, m.home_team, m.away_team, m.latest_state_code, m.latest_state_text,
               m.latest_state_display, m.latest_elapsed_min, m.match_time, m.sclass_name, m.sclass_color,
               m.latest_home_score, m.latest_away_score,
               m.latest_home_half_score, m.latest_away_half_score
        FROM monitor_tasks mt
        JOIN matches m ON mt.match_id = m.id
        {where_sql}
        LIMIT ?
    """
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    tasks = [dict(r) for r in rows]

    # [V2.5.4] 统一排序逻辑：状态大类优先（进行中>未开始>完场>其他），同大类内按match_time正序
    def sort_key(t):
        state_code = t.get('latest_state_code', 0)
        priority = STATE_SORT_PRIORITY.get(state_code, 99)
        match_time = t.get('match_time', '')
        return (priority, match_time)

    tasks.sort(key=sort_key)
    return tasks


def get_monitor_sclass_list():
    """
    V2.5.1: 获取监控任务中涉及的联赛列表（按拼音排序）
    复用xpinyin排序逻辑，确保A-Z排列
    """
    conn = get_conn()
    rows = conn.execute("""
        SELECT DISTINCT m.sclass_name, m.sclass_color
        FROM monitor_tasks mt
        JOIN matches m ON mt.match_id = m.id
        WHERE m.sclass_name IS NOT NULL AND m.sclass_name != ''
        ORDER BY m.sclass_name ASC
    """).fetchall()
    conn.close()
    names = [dict(r) for r in rows]

    # 按拼音排序
    try:
        from xpinyin import Pinyin
        p = Pinyin()
        names = sorted(names, key=lambda x: p.get_pinyin(x['sclass_name'] or '', ''))
    except ImportError:
        names = sorted(names, key=lambda x: x['sclass_name'] or '')
    return names


def get_snapshots_for_report(match_id):
    """
    V2.5.1: 获取比赛的所有快照（用于纯读生成报告）
    返回所有类型的快照，按创建时间排序
    """
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM snapshots
        WHERE match_id = ?
        ORDER BY created_at ASC
    """, (match_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_monitor_task_by_match(match_id):
    """V2.4.15: 获取指定比赛的监控任务"""
    conn = get_conn()
    row = conn.execute("""
        SELECT mt.*, m.home_team, m.away_team, m.latest_state_code, m.latest_state_text,
               m.latest_elapsed_min, m.match_time, m.sclass_name
        FROM monitor_tasks mt
        JOIN matches m ON mt.match_id = m.id
        WHERE mt.match_id = ?
        ORDER BY mt.id DESC LIMIT 1
    """, (match_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_monitor_task_status(match_id, node, status):
    """
    V2.4.15: 更新监控任务的节点状态
    node: 'ht' / 'min60' / 'min75' / 'ft'
    status: 0=待抓取, 1=成功, 2=放弃/失败
    """
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    col = f"{node}_status"
    # 安全拼接列名（白名单校验）
    if col not in ('ht_status', 'min60_status', 'min75_status', 'ft_status'):
        conn.close()
        raise ValueError(f"无效的节点名: {node}")
    c.execute(f"UPDATE monitor_tasks SET {col} = ?, updated_at = ? WHERE match_id = ? AND ft_status = 0",
              (status, now, match_id))
    conn.commit()
    conn.close()


def delete_monitor_task(match_id):
    """V2.4.15: 删除监控任务（用户主动取消）"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM monitor_tasks WHERE match_id = ?", (match_id,))
    conn.commit()
    conn.close()


# ==================== [V2.5.5] 任务6：自动监控联赛配置 ====================

def get_auto_monitor_leagues():
    """[V2.5.5] 获取自动监控联赛列表"""
    conn = get_conn()
    rows = conn.execute("SELECT sclass_name FROM auto_monitor_leagues ORDER BY sclass_name ASC").fetchall()
    conn.close()
    return [row['sclass_name'] for row in rows]


def add_auto_monitor_league(sclass_name):
    """[V2.5.5] 添加自动监控联赛（已存在则忽略）"""
    conn = get_conn()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn.execute(
        "INSERT OR IGNORE INTO auto_monitor_leagues (sclass_name, created_at) VALUES (?, ?)",
        (sclass_name, now)
    )
    conn.commit()
    conn.close()


def remove_auto_monitor_league(sclass_name):
    """[V2.5.5] 移除自动监控联赛"""
    conn = get_conn()
    conn.execute("DELETE FROM auto_monitor_leagues WHERE sclass_name = ?", (sclass_name,))
    conn.commit()
    conn.close()


def get_unstarted_matches_by_league(sclass_name):
    """[V2.5.5] 获取指定联赛中未开始且未监控的比赛ID列表
    [V2.5.6] 任务3：放宽为"未结束"比赛（state_code >= 0），覆盖进行中和未开始
    原逻辑仅查询 state_code=0（未开始），遗漏了已进行但未结束的比赛
    新逻辑查询 state_code >= 0（未开始+进行中），排除完场(-1)和取消/推迟等负值
    返回: [match_id, ...]
    """
    conn = get_conn()
    rows = conn.execute("""
        SELECT m.id FROM matches m
        WHERE m.sclass_name = ?
          AND m.latest_state_code >= 0
          AND m.id NOT IN (
              SELECT match_id FROM monitor_tasks WHERE ft_status = 0
          )
        ORDER BY m.match_time ASC
    """, (sclass_name,)).fetchall()
    conn.close()
    return [row['id'] for row in rows]


# ==================== V2.5: 数据库导出/导入功能 ====================

def export_database(date_start, date_end, output_path, sclass_names=None):
    """
    V2.5: 数据库导出功能
    V2.5.1: 升级为时间精度到分钟+联赛多选筛选
    按时间范围和联赛筛选matches和snapshots，导出到指定SQLite文件

    参数:
        date_start: 起始时间 (14位紧凑格式 YYYYMMDDHHMMSS)
        date_end: 结束时间 (14位紧凑格式 YYYYMMDDHHMMSS)
        output_path: 输出SQLite文件路径
        sclass_names: 联赛名称列表（多选），None或空列表表示全部

    返回: dict {match_count, snapshot_count}
    """
    import shutil
    conn = get_conn()
    c = conn.cursor()

    # 1. 按时间范围+联赛筛选查询matches
    # V2.5.1: 使用14位match_time字段精确匹配，走idx_matches_time_state索引
    if sclass_names:
        placeholders = ','.join(['?'] * len(sclass_names))
        sql = f"""
            SELECT * FROM matches
            WHERE match_time >= ? AND match_time <= ?
            AND sclass_name IN ({placeholders})
            ORDER BY match_time ASC
        """
        params = [date_start, date_end] + list(sclass_names)
        matches = c.execute(sql, params).fetchall()
    else:
        matches = c.execute(
            "SELECT * FROM matches WHERE match_time >= ? AND match_time <= ? ORDER BY match_time ASC",
            (date_start, date_end)
        ).fetchall()
    match_ids = [m['id'] for m in matches]

    # 2. 关联查询snapshots（受联赛筛选条件限制，通过match_id关联）
    snapshots = []
    if match_ids:
        placeholders = ','.join(['?'] * len(match_ids))
        snapshots = c.execute(
            f"SELECT * FROM snapshots WHERE match_id IN ({placeholders}) ORDER BY match_id, created_at",
            match_ids
        ).fetchall()

    conn.close()

    # 3. 创建全新的SQLite文件（结构与主库完全一致）
    if os.path.exists(output_path):
        os.remove(output_path)

    out_conn = sqlite3.connect(output_path)
    out_c = out_conn.cursor()

    # 创建matches表（结构与db.py init_db一致）
    out_c.execute("""
        CREATE TABLE matches (
            id INTEGER PRIMARY KEY,
            sclass_id INTEGER,
            sclass_name TEXT,
            sclass_color TEXT,
            match_time TEXT,
            match_date TEXT,
            home_team TEXT,
            away_team TEXT,
            home_rank INTEGER,
            away_rank INTEGER,
            weather TEXT,
            round_info TEXT,
            is_neutrality INTEGER DEFAULT 0,
            latest_state_code INTEGER,
            latest_state_text TEXT,
            latest_state_display TEXT,
            latest_home_score INTEGER,
            latest_away_score INTEGER,
            latest_home_half_score INTEGER,
            latest_away_half_score INTEGER,
            latest_home_red INTEGER,
            latest_away_red INTEGER,
            latest_home_yellow INTEGER,
            latest_away_yellow INTEGER,
            latest_elapsed_min INTEGER,
            latest_updated_at TEXT,
            created_at TEXT,
            first_seen_state INTEGER,
            halftime_snapshot_id INTEGER,
            min60_snapshot_id INTEGER,
            fulltime_snapshot_id INTEGER
        )
    """)

    # 创建snapshots表（结构与db.py init_db一致）
    out_c.execute("""
        CREATE TABLE snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER NOT NULL,
            snapshot_type TEXT,
            state_code INTEGER,
            state_text TEXT,
            home_score INTEGER,
            away_score INTEGER,
            home_half_score INTEGER,
            away_half_score INTEGER,
            elapsed_min INTEGER,
            shijian_json TEXT,
            analysis_json TEXT,
            created_at TEXT,
            FOREIGN KEY (match_id) REFERENCES matches(id)
        )
    """)

    # 创建索引
    out_c.execute("CREATE INDEX idx_snapshots_match ON snapshots(match_id)")
    out_c.execute("CREATE INDEX idx_snapshots_type ON snapshots(match_id, snapshot_type)")

    # 4. 写入matches数据
    match_count = 0
    for m in matches:
        m_dict = dict(m)
        cols = ', '.join(m_dict.keys())
        placeholders = ', '.join(['?'] * len(m_dict))
        out_c.execute(f"INSERT INTO matches ({cols}) VALUES ({placeholders})", list(m_dict.values()))
        match_count += 1

    # 5. 写入snapshots数据
    snapshot_count = 0
    for s in snapshots:
        s_dict = dict(s)
        # 丢弃原id，让新库自增
        if 'id' in s_dict:
            del s_dict['id']
        cols = ', '.join(s_dict.keys())
        placeholders = ', '.join(['?'] * len(s_dict))
        out_c.execute(f"INSERT INTO snapshots ({cols}) VALUES ({placeholders})", list(s_dict.values()))
        snapshot_count += 1

    out_conn.commit()
    out_conn.close()

    return {'match_count': match_count, 'snapshot_count': snapshot_count}


def import_database(input_path):
    """
    V2.5.2: 数据库导入功能（极简导入 - 阶段一）
    ============================================================
    架构师定稿：放弃V2.5.1的"实时映射+实时外键修复"复杂逻辑，
    改为"极简导入 + 后置清理与重建"两阶段方案。

    阶段一（本函数）：只管数据入库，不处理外键关联
        - 快照：丢弃原ID自增新ID，保留防重机制（match_id+snapshot_type+created_at）
        - 比赛：复用V2.5.1冲突策略（完场优先>时间新旧，保留本地created_at）
        - 关键变更：三个外键字段强制置NULL，彻底切断导入时外键修复

    阶段二（cleanup_and_rebuild_foreign_keys）：导入后清理重复快照+重建外键

    返回: dict {matches_inserted, matches_updated, matches_skipped, snapshots_inserted, snapshots_skipped}
    """
    in_conn = sqlite3.connect(input_path)
    in_conn.row_factory = sqlite3.Row
    in_c = in_conn.cursor()

    # 1. 读取导入文件的snapshots
    try:
        in_snapshots = in_c.execute("SELECT * FROM snapshots").fetchall()
    except sqlite3.OperationalError:
        in_snapshots = []

    # 2. 读取导入文件的matches
    try:
        in_matches = in_c.execute("SELECT * FROM matches").fetchall()
    except sqlite3.OperationalError:
        in_matches = []

    in_conn.close()

    # 3. [V2.5.2] 极简导入matches：复用冲突策略，三个外键强制置NULL
    # 必须先导入matches，再导入snapshots（snapshots外键依赖matches表）
    conn = get_conn()
    c = conn.cursor()
    matches_inserted = 0
    matches_updated = 0
    matches_skipped = 0

    for m in in_matches:
        m_dict = dict(m)
        match_id = m_dict.get('id')

        # [V2.5.2] 关键变更：三个外键字段强制置NULL，彻底切断导入时外键修复
        m_dict['halftime_snapshot_id'] = None
        m_dict['min60_snapshot_id'] = None
        m_dict['fulltime_snapshot_id'] = None

        # 查询本地是否已存在该match
        local = c.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()

        if not local:
            # 新插入
            cols = ', '.join(m_dict.keys())
            placeholders = ', '.join(['?'] * len(m_dict))
            c.execute(f"INSERT OR IGNORE INTO matches ({cols}) VALUES ({placeholders})", list(m_dict.values()))
            matches_inserted += 1
        else:
            # 冲突策略（复用V2.5.1）
            local_dict = dict(local)
            local_state = local_dict.get('latest_state_code')
            import_state = m_dict.get('latest_state_code')
            local_updated = local_dict.get('latest_updated_at') or ''
            import_updated = m_dict.get('latest_updated_at') or ''

            should_update = False
            if import_state == -1 and local_state != -1:
                # 规则1：导入已完场而本地未完场 → 用导入数据覆盖
                should_update = True
            elif local_state == -1 and import_state != -1:
                # 规则3：本地已完场而导入未完场 → 保留本地
                should_update = False
            else:
                # 规则2：两边状态相同 → 对比latest_updated_at，谁新留谁
                should_update = import_updated > local_updated

            if should_update:
                # 保留本地created_at
                m_dict['created_at'] = local_dict.get('created_at')
                # 更新（排除id）
                update_cols = [k for k in m_dict.keys() if k != 'id']
                set_clause = ', '.join([f"{k} = ?" for k in update_cols])
                params = [m_dict[k] for k in update_cols] + [match_id]
                c.execute(f"UPDATE matches SET {set_clause} WHERE id = ?", params)
                matches_updated += 1
            else:
                matches_skipped += 1

    # 4. [V2.5.2] 极简导入snapshots：丢弃原ID，保留防重，不建映射字典
    snapshots_inserted = 0
    snapshots_skipped = 0

    for s in in_snapshots:
        s_dict = dict(s)
        match_id = s_dict.get('match_id')

        # 检查match_id是否存在于本地（外键约束）
        local_match = c.execute("SELECT id FROM matches WHERE id = ?", (match_id,)).fetchone()
        if not local_match:
            snapshots_skipped += 1
            continue

        # [V2.5.2] 强制丢弃原id，让本地自增
        if 'id' in s_dict:
            del s_dict['id']

        # 保留防重机制：基于match_id+snapshot_type+created_at
        existing = c.execute(
            "SELECT id FROM snapshots WHERE match_id = ? AND snapshot_type = ? AND created_at = ?",
            (match_id, s_dict.get('snapshot_type'), s_dict.get('created_at'))
        ).fetchone()
        if existing:
            snapshots_skipped += 1
            continue

        cols = ', '.join(s_dict.keys())
        placeholders = ', '.join(['?'] * len(s_dict))
        c.execute(f"INSERT OR IGNORE INTO snapshots ({cols}) VALUES ({placeholders})", list(s_dict.values()))
        snapshots_inserted += 1

    conn.commit()
    conn.close()

    return {
        'matches_inserted': matches_inserted,
        'matches_updated': matches_updated,
        'matches_skipped': matches_skipped,
        'snapshots_inserted': snapshots_inserted,
        'snapshots_skipped': snapshots_skipped,
    }


def cleanup_and_rebuild_foreign_keys():
    """
    V2.5.2: 阶段二 - 定向清理与外键重建（架构师定稿核心）
    ============================================================
    在导入事务提交后立即执行，利用数据库索引保障性能，
    一次性解决数据一致性问题。

    [V2.6.0] 变更：manual 类型纳入清理范围
    步骤1：清理重复快照（严格限制范围）
        - 清理范围：snapshot_type IN ('halftime', 'fulltime', 'manual')
        - 严禁触碰 min60、min75 等其他状态快照
        - 规则：同match_id+同类型多条记录，只保留created_at最新的一条

    步骤2：重建外键关联（修复空值与悬空指针）
        - 修复目标：halftime_snapshot_id 和 fulltime_snapshot_id
        - 触发条件：外键为NULL，或指向的ID在snapshots表中不存在（悬空指针）
        - 重建动作：查找该比赛对应类型、created_at最新的快照ID填入

    步骤3：修复reports表的悬空snapshot_id引用
        - [V2.5.2修复] 清理重复快照后，reports表可能引用了被删除的快照
        - 需将reports.snapshot_id更新为同比赛同类型的保留快照ID，或置NULL

    性能保障：纯SQL批量UPDATE，禁止Python逐行循环
    事务保障：清理和重建在同一事务中完成
    外键约束处理：临时关闭foreign_keys，避免DELETE被reports表引用阻断
    """
    conn = get_conn()
    c = conn.cursor()

    # [V2.5.2修复] 临时关闭外键检查，避免清理重复快照时
    # 因reports表引用被删快照而触发 FOREIGN KEY constraint failed
    # SQLite官方推荐：批量数据迁移时临时关闭外键检查
    c.execute("PRAGMA foreign_keys=OFF")
    try:
        # 开启事务（确保原子性）
        c.execute("BEGIN")

        # ============ 步骤1：清理重复快照 ============
        # [V2.6.0] 清理范围从 ('halftime', 'fulltime') 扩大为 ('halftime', 'fulltime', 'manual')
        # 保留每组(match_id, snapshot_type)中created_at最新的一条（id最大作为平局决胜）
        cleanup_sql = """
            DELETE FROM snapshots
            WHERE snapshot_type IN ('halftime', 'fulltime', 'manual')
            AND id NOT IN (
                SELECT s1.id FROM snapshots s1
                WHERE s1.snapshot_type IN ('halftime', 'fulltime', 'manual')
                AND NOT EXISTS (
                    SELECT 1 FROM snapshots s2
                    WHERE s2.match_id = s1.match_id
                    AND s2.snapshot_type = s1.snapshot_type
                    AND (s2.created_at > s1.created_at
                         OR (s2.created_at = s1.created_at AND s2.id > s1.id))
                )
            )
        """
        c.execute(cleanup_sql)
        deleted_count = c.rowcount

        # ============ 步骤2：重建外键关联 ============
        # [V2.5.2] 纯SQL批量UPDATE，利用子查询一次性完成匹配和更新
        # 修复 halftime_snapshot_id（NULL或悬空指针）
        rebuild_halftime_sql = """
            UPDATE matches
            SET halftime_snapshot_id = (
                SELECT s.id FROM snapshots s
                WHERE s.match_id = matches.id
                AND s.snapshot_type = 'halftime'
                ORDER BY s.created_at DESC LIMIT 1
            )
            WHERE halftime_snapshot_id IS NULL
               OR halftime_snapshot_id NOT IN (SELECT id FROM snapshots)
        """
        c.execute(rebuild_halftime_sql)
        halftime_fixed = c.rowcount

        # 修复 fulltime_snapshot_id（NULL或悬空指针）
        rebuild_fulltime_sql = """
            UPDATE matches
            SET fulltime_snapshot_id = (
                SELECT s.id FROM snapshots s
                WHERE s.match_id = matches.id
                AND s.snapshot_type = 'fulltime'
                ORDER BY s.created_at DESC LIMIT 1
            )
            WHERE fulltime_snapshot_id IS NULL
               OR fulltime_snapshot_id NOT IN (SELECT id FROM snapshots)
        """
        c.execute(rebuild_fulltime_sql)
        fulltime_fixed = c.rowcount

        # ============ 步骤3：修复reports表悬空snapshot_id引用 ============
        # [V2.5.2修复] 清理重复快照后，reports.snapshot_id可能指向已删除的快照
        # 使用reports.report_type作为快照类型依据（避免依赖已删除的快照记录）
        # 将其更新为同比赛同类型的保留快照ID，找不到则置NULL
        fix_reports_sql = """
            UPDATE reports
            SET snapshot_id = (
                SELECT s.id FROM snapshots s
                WHERE s.match_id = reports.match_id
                AND s.snapshot_type = reports.report_type
                ORDER BY s.created_at DESC LIMIT 1
            )
            WHERE snapshot_id IS NOT NULL
              AND snapshot_id NOT IN (SELECT id FROM snapshots)
        """
        c.execute(fix_reports_sql)
        reports_fixed = c.rowcount

        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"[V2.5.2] 清理重建失败，已回滚: {e}")
        raise
    finally:
        # 恢复外键检查
        c.execute("PRAGMA foreign_keys=ON")
        conn.close()

    logger.info(f"[V2.5.2] 清理重建完成: 删除重复快照{deleted_count}条, "
                f"修复halftime外键{halftime_fixed}条, 修复fulltime外键{fulltime_fixed}条, "
                f"修复reports悬空引用{reports_fixed}条")

    return {
        'duplicates_deleted': deleted_count,
        'halftime_fixed': halftime_fixed,
        'fulltime_fixed': fulltime_fixed,
        'reports_fixed': reports_fixed,
    }


if __name__ == '__main__':
    init_db()
    print(f"数据库已初始化: {DB_PATH}")
