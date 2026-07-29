#!/usr/bin/env python3
"""
export_cli.py - 命令行导出工具 (V1.5)
================================
用法：
    python export_cli.py --db /path/to/football.db --start 2024-01-01 --end 2024-12-31
    
    python export_cli.py --db /path/to/football.db --league 英超 西甲 --team 曼联
    
    python export_cli.py --db /path/to/football.db --limit 10
    
    python export_cli.py --info  # 查看数据库信息
    
    # V1.5新增: Sheet选择
    python export_cli.py --db /path/to/football.db --sheets match tech events
    
    # V1.5新增: 非完场快照导出
    python export_cli.py --db /path/to/football.db --match-mode halftime --include-fulltime
    python export_cli.py --db /path/to/football.db --match-mode custom --min-minute 60 --max-minute 70
"""

import argparse
import sys
import os

# 将当前目录加入路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from football_export import (
    export_matches, get_db_info, get_sclass_list, get_date_range,
    query_matches, query_non_fulltime_snapshots,
)
from football_export.excel_exporter import export_to_excel, generate_filename_v15
from football_export import config


def main():
    parser = argparse.ArgumentParser(
        description="足球比赛数据报表导出工具 V1.5",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 查看数据库信息
  python export_cli.py --db /path/to/football.db --info

  # 导出2024年所有完场比赛
  python export_cli.py --db /path/to/football.db --start 2024-01-01 --end 2024-12-31

  # 导出英超和西甲中含"曼联"的比赛
  python export_cli.py --db /path/to/football.db --league 英超 西甲 --team 曼联

  # V1.5: 导出指定Sheet（部分选择）
  python export_cli.py --db /path/to/football.db --sheets match tech events

  # V1.5: 导出半场快照（含关联完场标签）
  python export_cli.py --db /path/to/football.db --match-mode halftime --include-fulltime

  # V1.5: 导出60-70分钟区间快照
  python export_cli.py --db /path/to/football.db --match-mode custom --min-minute 60 --max-minute 70
        """,
    )
    
    parser.add_argument("--db", default=None, help="数据库路径（默认使用配置中的路径）")
    parser.add_argument("--start", default=None, help="开始日期 (YYYY-MM-DD)")
    parser.add_argument("--end", default=None, help="结束日期 (YYYY-MM-DD)")
    parser.add_argument("--league", nargs="*", default=None, help="联赛名称（可多选）")
    parser.add_argument("--team", default=None, help="球队名称（模糊搜索）")
    parser.add_argument("--output", default=None, help="输出文件路径")
    parser.add_argument("--limit", type=int, default=None, help="最多导出多少场比赛")
    
    # V1.5新增参数
    parser.add_argument("--sheets", nargs="*", default=None,
                        help="V1.5: 要导出的Sheet标识（如 match tech events），默认全选")
    parser.add_argument("--match-mode", default="fulltime",
                        choices=["fulltime", "halftime", "custom"],
                        help="V1.5: 比赛模式 fulltime(完场)/halftime(半场)/custom(自定义分钟区间)")
    parser.add_argument("--min-minute", type=int, default=None,
                        help="V1.5: 自定义分钟区间下限（match-mode=custom时有效）")
    parser.add_argument("--max-minute", type=int, default=None,
                        help="V1.5: 自定义分钟区间上限（match-mode=custom时有效）")
    parser.add_argument("--include-fulltime", action="store_true",
                        help="V1.5: 非完场导出时同时导出关联完场快照（训练标签）")
    
    parser.add_argument("--info", action="store_true", help="显示数据库信息后退出")
    parser.add_argument("--leagues", action="store_true", help="列出所有联赛后退出")
    parser.add_argument("--dates", action="store_true", help="显示日期范围后退出")
    
    args = parser.parse_args()
    
    db_path = args.db
    
    # 信息查询模式
    if args.info:
        info = get_db_info(db_path)
        print(f"数据库: {info['db_path']}")
        if "error" in info:
            print(f"错误: {info['error']}")
            return
        print(f"\n表结构:")
        for table_name, table_info in info["tables"].items():
            print(f"\n  [{table_name}] ({table_info['row_count']} 行)")
            for col in table_info["columns"]:
                nn = " NOT NULL" if col["notnull"] else ""
                print(f"    {col['name']:25s} {col['type']:15s}{nn}")
        return
    
    if args.leagues:
        leagues = get_sclass_list(db_path)
        print(f"共 {len(leagues)} 个联赛:")
        for lg in leagues:
            print(f"  {lg}")
        return
    
    if args.dates:
        dr = get_date_range(db_path)
        print(f"比赛日期范围: {dr['min_date']} ~ {dr['max_date']}")
        return
    
    # V1.5: 非完场快照导出模式
    if args.match_mode in ("halftime", "custom"):
        print(f"V1.5非完场快照导出模式: {args.match_mode}")
        
        # 参数校验
        if args.match_mode == "custom":
            if args.min_minute is None or args.max_minute is None:
                print("错误: custom模式需要指定 --min-minute 和 --max-minute")
                sys.exit(1)
            if args.min_minute >= args.max_minute:
                print("错误: --min-minute 必须小于 --max-minute")
                sys.exit(1)
        
        # 构建快照筛选条件
        if args.match_mode == "halftime":
            snapshot_filter = {"mode": "halftime"}
            snap_type = "halftime"
        else:
            snapshot_filter = {"mode": "custom", "min": args.min_minute, "max": args.max_minute}
            snap_type = "custom"
        
        # 查询非完场快照
        result = query_non_fulltime_snapshots(
            db_path=db_path,
            snapshot_filter=snapshot_filter,
            include_fulltime=args.include_fulltime,
            start_date=args.start,
            end_date=args.end,
            sclass_names=args.league,
            team_name=args.team,
            limit=args.limit,
        )
        
        prediction_snapshots = result["prediction_snapshots"]
        label_snapshots = result["label_snapshots"]
        
        print(f"找到 {len(prediction_snapshots)} 个非完场快照")
        if args.include_fulltime:
            print(f"找到 {len(label_snapshots)} 个关联完场快照")
        
        if not prediction_snapshots:
            print("未找到数据")
            sys.exit(1)
        
        # 生成prediction文件
        sheets = args.sheets if args.sheets else None
        pred_filename = generate_filename_v15(
            sclass_names=args.league,
            start_date=args.start,
            end_date=args.end,
            sheets_to_export=sheets,
            snapshot_type=snap_type,
            file_role="prediction",
        )
        pred_path = os.path.join(config.OUTPUT_DIR, pred_filename)
        
        export_to_excel(
            matches=prediction_snapshots,
            output_path=pred_path,
            sclass_names=args.league,
            start_date=args.start,
            end_date=args.end,
            sheets_to_export=sheets,
        )
        print(f"\nprediction文件: {pred_path}")
        
        # 生成label文件
        if args.include_fulltime and label_snapshots:
            label_filename = generate_filename_v15(
                sclass_names=args.league,
                start_date=args.start,
                end_date=args.end,
                sheets_to_export=sheets,
                snapshot_type="fulltime",
                file_role="label",
            )
            label_path = os.path.join(config.OUTPUT_DIR, label_filename)
            
            export_to_excel(
                matches=label_snapshots,
                output_path=label_path,
                sclass_names=args.league,
                start_date=args.start,
                end_date=args.end,
                sheets_to_export=sheets,
            )
            print(f"label文件: {label_path}")
        
        return
    
    # V1.5: 完场导出模式（支持Sheet选择）
    if args.sheets:
        # 使用Sheet选择功能
        print(f"V1.5 Sheet选择导出: {args.sheets}")
        
        matches = query_matches(
            db_path=db_path,
            start_date=args.start,
            end_date=args.end,
            sclass_names=args.league,
            team_name=args.team,
            limit=args.limit,
        )
        
        if not matches:
            print("未找到数据")
            sys.exit(1)
        
        filename = generate_filename_v15(
            sclass_names=args.league,
            start_date=args.start,
            end_date=args.end,
            sheets_to_export=args.sheets,
            snapshot_type="fulltime",
        )
        output_path = args.output or os.path.join(config.OUTPUT_DIR, filename)
        
        export_to_excel(
            matches=matches,
            output_path=output_path,
            sclass_names=args.league,
            start_date=args.start,
            end_date=args.end,
            sheets_to_export=args.sheets,
        )
        print(f"\n导出成功: {output_path}")
        return
    
    # 标准导出模式（向后兼容V1.0-V1.4）
    output_file = export_matches(
        db_path=db_path,
        start_date=args.start,
        end_date=args.end,
        sclass_names=args.league,
        team_name=args.team,
        output_path=args.output,
        limit=args.limit,
    )
    
    if output_file:
        print(f"\n导出成功: {output_file}")
    else:
        print("\n未导出任何数据")
        sys.exit(1)


if __name__ == "__main__":
    main()
    
