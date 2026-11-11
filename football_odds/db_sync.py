#!/usr/bin/env python3
"""
足球比赛数据文档分析系统 V2.6.3 - 数据库同步模块
====================================================
模块名称：db_sync
版本号：V2.5.5
作者：系统开发人员
日期：2026-07-29

[V2.5.5] 变更说明：
- 修复测试块日期格式（10位改为14位）

功能：
    数据库级别的导入/导出功能，与已冻结的/export页面物理隔离。
    提供全局锁机制，确保导入期间暂停monitor线程，保证数据一致性。

核心设计：
    1. 全局锁：使用threading.Lock保证线程安全
    2. 导出：按日期范围筛选matches+snapshots，生成独立SQLite文件
    3. 导入：ID重映射 + 外键修复 + 冲突策略（完场优先 > 时间新旧）
    4. 文件命名：db_export_{起始日期}_{结束日期}_{导出时间戳}.db

架构师确认的设计决策：
    1. 导出文件不自动删除，保存到download目录由用户管理
    2. 冲突策略：完场优先 > 时间新旧；本地已完场而导入未完场→保留本地
    3. 导入期间暂停monitor线程，完成后恢复
"""

import os
import threading
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ==================== 全局锁机制 ====================

# 全局导入锁：导入期间持有，阻止并发导入和monitor线程
_import_lock = threading.Lock()
# 导入状态标志：供monitor线程检查
_is_importing = False
_state_lock = threading.Lock()


def is_importing():
    """检查当前是否正在导入数据"""
    with _state_lock:
        return _is_importing


def _set_importing(value):
    """设置导入状态（内部函数）"""
    global _is_importing
    with _state_lock:
        _is_importing = value


def acquire_import_lock():
    """
    获取导入锁，暂停monitor线程
    返回: True如果成功获取锁，False如果已有导入在进行
    """
    if not _import_lock.acquire(blocking=False):
        logger.warning("[V2.5] 已有数据库导入操作正在进行，请稍后再试")
        return False
    _set_importing(True)
    logger.info("[V2.5] 数据库导入锁已获取，monitor线程将暂停")
    return True


def release_import_lock():
    """释放导入锁，恢复monitor线程"""
    _set_importing(False)
    _import_lock.release()
    logger.info("[V2.5] 数据库导入锁已释放，monitor线程恢复运行")


# ==================== 导出功能 ====================

def do_export(date_start, date_end, sclass_names=None):
    """
    V2.5: 执行数据库导出
    V2.5.1: 升级为14位时间格式+联赛多选

    参数:
        date_start: 起始时间 (14位紧凑格式 YYYYMMDDHHMMSS)
        date_end: 结束时间 (14位紧凑格式 YYYYMMDDHHMMSS)
        sclass_names: 联赛名称列表（多选），None或空列表表示全部

    返回: dict {
        success: bool,
        filepath: str,  # 导出文件路径
        export_stats: {match_count, snapshot_count},
        message: str
    }
    """
    from db import export_database

    # V2.5.1: 文件名使用14位时间格式的前8位（日期部分）
    date_start_compact = date_start[:8]  # YYYYMMDD
    date_end_compact = date_end[:8]
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    filename = f"db_export_{date_start_compact}_{date_end_compact}_{timestamp}.db"

    # 保存到download目录
    download_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'download')
    os.makedirs(download_dir, exist_ok=True)
    filepath = os.path.join(download_dir, filename)

    try:
        stats = export_database(date_start, date_end, filepath, sclass_names)
        logger.info(f"[V2.5.1] 数据库导出成功: {filename}, 比赛{stats['match_count']}场, 快照{stats['snapshot_count']}条")
        return {
            'success': True,
            'filepath': filepath,
            'filename': filename,
            'export_stats': stats,
            'message': f"成功导出 {stats['match_count']} 场比赛，{stats['snapshot_count']} 条快照数据。"
        }
    except Exception as e:
        logger.error(f"[V2.5] 数据库导出失败: {e}")
        return {
            'success': False,
            'filepath': None,
            'export_stats': {'match_count': 0, 'snapshot_count': 0},
            'message': f"导出失败: {str(e)}"
        }


# ==================== 导入功能 ====================

def do_import(filepath):
    """
    V2.5: 执行数据库导入
    导入期间获取全局锁，暂停monitor线程

    参数:
        filepath: 导入的SQLite文件路径

    返回: dict {
        success: bool,
        import_stats: {matches_inserted, matches_updated, matches_skipped,
                       snapshots_inserted, snapshots_skipped},
        message: str
    }
    """
    from db import import_database
    from monitor import pause_monitor, resume_monitor

    # 检查文件是否存在
    if not os.path.exists(filepath):
        return {
            'success': False,
            'import_stats': {},
            'message': f"文件不存在: {filepath}"
        }

    # 获取导入锁
    if not acquire_import_lock():
        return {
            'success': False,
            'import_stats': {},
            'message': "已有导入操作正在进行，请稍后再试"
        }

    try:
        # 暂停monitor线程
        pause_monitor()
        logger.info("[V2.5.2] monitor线程已暂停，开始导入数据")

        # [V2.5.2] 阶段一：极简导入（不处理外键）
        stats = import_database(filepath)
        logger.info(f"[V2.5.2] 阶段一导入完成: 新增{stats['matches_inserted']}场, 更新{stats['matches_updated']}场, 跳过{stats['matches_skipped']}场")

        # [V2.5.2] 阶段二：后置清理与外键重建
        from db import cleanup_and_rebuild_foreign_keys
        cleanup_stats = cleanup_and_rebuild_foreign_keys()
        logger.info(f"[V2.5.2] 阶段二清理重建完成: 删除重复快照{cleanup_stats['duplicates_deleted']}条, "
                    f"修复halftime外键{cleanup_stats['halftime_fixed']}条, "
                    f"修复fulltime外键{cleanup_stats['fulltime_fixed']}条")

        message = (f"导入完成：新增 {stats['matches_inserted']} 场比赛，更新 {stats['matches_updated']} 场，"
                   f"跳过 {stats['matches_skipped']} 场；新增 {stats['snapshots_inserted']} 条快照，"
                   f"跳过 {stats['snapshots_skipped']} 条快照。"
                   f"清理重复快照 {cleanup_stats['duplicates_deleted']} 条，"
                   f"修复外键 {cleanup_stats['halftime_fixed'] + cleanup_stats['fulltime_fixed']} 条。")

        return {
            'success': True,
            'import_stats': stats,
            'cleanup_stats': cleanup_stats,
            'message': message
        }
    except Exception as e:
        logger.error(f"[V2.5.2] 数据库导入失败: {e}")
        return {
            'success': False,
            'import_stats': {},
            'message': f"导入失败: {str(e)}"
        }
    finally:
        # 恢复monitor线程
        resume_monitor()
        logger.info("[V2.5.2] monitor线程已恢复")
        # 释放导入锁
        release_import_lock()


if __name__ == '__main__':
    # 测试用例
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    print("=== 测试导出功能 ===")
    # [V2.5.5] 修复：10位日期改为14位格式（YYYYMMDDHHMMSS）
    result = do_export('20260701000000', '20260715235959')
    print(f"导出结果: {result}")
