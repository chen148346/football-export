"""
football_export - 足球比赛数据报表导出模块
============================================
独立的Python模块，从SQLite数据库读取完场比赛数据，导出为7-Sheet Excel文件。

主要接口：
    from football_export import export_matches
    
    # 导出比赛数据
    output_file = export_matches(
        db_path="/path/to/football.db",
        start_date="2024-01-01",
        end_date="2024-12-31",
        sclass_names=["英超", "西甲"],
        team_name="曼联",
    )
"""

from . import config
from . import json_parser
from . import db_reader
from . import excel_exporter

# 导出主要接口函数
from .db_reader import (
    query_matches, get_sclass_list, get_date_range, get_db_info,
    get_match_count_by_state, query_non_fulltime_snapshots, MatchRecord,
)
from .excel_exporter import (
    export_to_excel, generate_filename, generate_filename_v12,
    generate_filename_v15,
)


def export_matches(
    db_path: str = None,
    start_date: str = None,
    end_date: str = None,
    sclass_names: list = None,
    team_name: str = None,
    output_path: str = None,
    limit: int = None,
) -> str:
    """
    一站式导出接口：查询比赛数据并导出为Excel。
    
    参数：
        db_path: 数据库路径（None使用默认路径）
        start_date: 开始日期 YYYY-MM-DD
        end_date: 结束日期 YYYY-MM-DD
        sclass_names: 联赛名称列表（多选）
        team_name: 球队名称（模糊搜索）
        output_path: 输出文件路径（None自动生成）
        limit: 最多导出多少场比赛
    
    返回：
        生成的Excel文件路径
    """
    print("=" * 60)
    print("足球比赛数据导出")
    print("=" * 60)
    print(f"数据库: {db_path or config.DEFAULT_DB_PATH}")
    print(f"日期范围: {start_date or '不限'} ~ {end_date or '不限'}")
    print(f"联赛: {sclass_names or '不限'}")
    print(f"球队: {team_name or '不限'}")
    print(f"数量限制: {limit or '不限'}")
    print("-" * 60)
    
    # 1. 查询比赛数据
    print("正在查询比赛数据...")
    matches = query_matches(
        db_path=db_path,
        start_date=start_date,
        end_date=end_date,
        sclass_names=sclass_names,
        team_name=team_name,
        limit=limit,
    )
    print(f"找到 {len(matches)} 场完场比赛")
    
    if not matches:
        print("[WARNING] 没有找到符合条件的比赛数据")
        return ""
    
    # 2. 导出Excel
    print("\n正在生成Excel文件...")
    output_file = export_to_excel(
        matches=matches,
        output_path=output_path,
        sclass_names=sclass_names,
        start_date=start_date,
        end_date=end_date,
    )
    
    return output_file


__all__ = [
    "config",
    "json_parser",
    "db_reader",
    "excel_exporter",
    "export_matches",
    "query_matches",
    "get_sclass_list",
    "get_date_range",
    "get_db_info",
    "get_match_count_by_state",
    "query_non_fulltime_snapshots",
    "export_to_excel",
    "generate_filename",
    "generate_filename_v12",
    "generate_filename_v15",
    "MatchRecord",
]
