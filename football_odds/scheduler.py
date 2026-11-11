"""
足球比赛数据文档分析系统 V2.6.3 - 调度器模块

[V2.5.5] 变更说明：
- min60窗口统一为 57-63（与 monitor.py 一致）
- 删除 update_match_min60_snapshot 死函数导入
- shijian_json/analysis_json 空值统一为空字典{}

历史变更：
- V2.0: 移除自动调度器（所有刷新和报告生成必须手动触发）；保留 refresh_schedule() 和 manual_snapshot()
"""
import os
import sys
import json
import logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import (
    init_db, get_all_matches, get_match, update_match, create_snapshot,
    get_snapshots_by_match, update_match_halftime_snapshot,
    update_match_fulltime_snapshot,
    update_first_seen_state, sync_matches
)
from scraper import fetch_schedule_list, fetch_match_detail, fetch_schedule_status_batch
from match_time_calc import estimate_elapsed_min, get_server_time

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# [V2.5.3] 赛程列表缓存（避免监控轮询时重复抓取）
_schedule_cache = {
    'data': None,       # 缓存的赛程列表
    'timestamp': 0,     # 缓存时间戳
}
_SCHEDULE_CACHE_TTL = 60  # 缓存有效期60秒（监控轮询间隔内复用）


def refresh_schedule(do_maintenance=False):
    """
    手动刷新比赛列表 - 全量同步，确保与 titan007 100% 一致
    V2.0: 仅由用户手动触发，不再自动执行
    [V2.6.0] 增加 do_maintenance 参数，控制是否执行VACUUM+ANALYZE
    """
    try:
        matches = fetch_schedule_list()

        # 为新比赛设置 first_seen_state
        from db import get_conn
        conn = get_conn()
        for m in matches:
            row = conn.execute(
                "SELECT first_seen_state FROM matches WHERE id = ?", (m['id'],)
            ).fetchone()
            if row is None:
                m['first_seen_state'] = m.get('latest_state_code')
            elif row['first_seen_state'] is None:
                conn.execute(
                    "UPDATE matches SET first_seen_state = ? WHERE id = ?",
                    (m.get('latest_state_code'), m['id'])
                )
        conn.commit()
        conn.close()

        # 使用 sync_matches 全量同步
        count = sync_matches(matches, do_maintenance=do_maintenance)
        logger.info(f"比赛列表全量同步完成: {count} 场比赛")
        return count
    except Exception as e:
        logger.error(f"比赛列表刷新失败: {e}")
        return 0


def refresh_match_status(match_id):
    """
    V2.0 新增：刷新单场比赛的状态
    V2.5.3 优化：使用赛程缓存，避免每次都抓取整个赛程列表

    参数: match_id - 比赛ID
    返回: 更新后的match dict
    """
    match = get_match(match_id)
    if not match:
        raise ValueError(f"比赛 {match_id} 不存在")

    # [V2.5.3] 使用带缓存的赛程获取，避免重复抓取
    matches = _get_schedule_with_cache()
    for m in matches:
        if m['id'] == match_id:
            # 更新比赛状态
            match_update = dict(match)
            match_update['latest_state_code'] = m.get('latest_state_code')
            match_update['latest_state_text'] = m.get('latest_state_text')
            match_update['latest_state_display'] = m.get('latest_state_display')
            match_update['latest_home_score'] = m.get('latest_home_score')
            match_update['latest_away_score'] = m.get('latest_away_score')
            match_update['latest_home_half_score'] = m.get('latest_home_half_score')
            match_update['latest_away_half_score'] = m.get('latest_away_half_score')
            match_update['latest_elapsed_min'] = m.get('latest_elapsed_min')
            update_match(match_update)
            logger.info(f"比赛 {match_id} 状态已刷新: {m.get('latest_state_display')}")
            return get_match(match_id)

    # 如果比赛不在当前列表中（可能是已完场的旧比赛），保持原状态
    logger.info(f"比赛 {match_id} 不在当前列表中，保持原状态")
    return match


def _get_schedule_with_cache():
    """
    [V2.5.3] 带缓存的赛程列表获取
    缓存有效期60秒，避免监控轮询时多场比赛重复抓取整个赛程列表
    """
    import time as _time
    now = _time.time()
    # 缓存有效期内直接返回缓存
    if _schedule_cache['data'] is not None and (now - _schedule_cache['timestamp']) < _SCHEDULE_CACHE_TTL:
        logger.debug(f"[V2.5.3] 使用赛程缓存（剩余{_SCHEDULE_CACHE_TTL - int(now - _schedule_cache['timestamp'])}秒）")
        return _schedule_cache['data']

    # 缓存过期，重新抓取
    try:
        matches = fetch_schedule_list()
        _schedule_cache['data'] = matches
        _schedule_cache['timestamp'] = now
        logger.info(f"[V2.5.3] 赛程列表已抓取并缓存（{len(matches)}场比赛）")
        return matches
    except Exception as e:
        logger.error(f"[V2.5.3] 赛程列表抓取失败: {e}")
        # 返回旧缓存（如果有），否则空列表
        return _schedule_cache['data'] if _schedule_cache['data'] is not None else []


def refresh_match_status_batch(match_ids):
    """
    [V2.5.3] 批量刷新多场比赛状态（监控拥堵优化核心）
    ============================================================
    一次抓取赛程列表，批量更新所有指定比赛的状态。
    替代监控轮询中逐场调用refresh_match_status的低效模式。

    参数: match_ids - 需要刷新状态的match_id列表
    返回: dict {match_id: match_dict, ...}
    """
    if not match_ids:
        return {}

    # 一次抓取赛程列表（带缓存）
    matches = _get_schedule_with_cache()

    # 构建match_id到赛程数据的映射
    id_set = set(match_ids)
    schedule_map = {}
    for m in matches:
        if m['id'] in id_set:
            schedule_map[m['id']] = m

    # 批量更新数据库中的比赛状态
    result = {}
    for match_id in match_ids:
        match = get_match(match_id)
        if not match:
            continue

        m = schedule_map.get(match_id)
        if m:
            # 更新比赛状态
            match_update = dict(match)
            match_update['latest_state_code'] = m.get('latest_state_code')
            match_update['latest_state_text'] = m.get('latest_state_text')
            match_update['latest_state_display'] = m.get('latest_state_display')
            match_update['latest_home_score'] = m.get('latest_home_score')
            match_update['latest_away_score'] = m.get('latest_away_score')
            match_update['latest_home_half_score'] = m.get('latest_home_half_score')
            match_update['latest_away_half_score'] = m.get('latest_away_half_score')
            match_update['latest_elapsed_min'] = m.get('latest_elapsed_min')
            update_match(match_update)
            result[match_id] = get_match(match_id)
        else:
            # 比赛不在当前列表中，保持原状态
            result[match_id] = match

    logger.info(f"[V2.5.3] 批量刷新{len(match_ids)}场比赛状态完成，命中{len(schedule_map)}场")
    return result


def manual_snapshot(match_id, snapshot_type='manual'):
    """
    手动创建快照
    V2.0: 创建快照前先刷新比赛状态

    参数:
        match_id: 比赛ID
        snapshot_type: 快照类型 (manual/halftime/min60/fulltime)

    返回: (snapshot_id, detail)
    """
    # V2.0: 先刷新比赛状态
    match = refresh_match_status(match_id)

    state_code = match.get('latest_state_code', 0)
    state_text = match.get('latest_state_text', '')
    elapsed = match.get('latest_elapsed_min', 0)

    # 根据状态确定快照类型
    if snapshot_type == 'manual':
        if state_code == -1:
            snapshot_type = 'fulltime'
        elif state_code == 2:
            snapshot_type = 'halftime'
        elif state_code == 3 and 57 <= elapsed <= 63:
            snapshot_type = 'min60'

    detail = fetch_match_detail(match_id)

    # 更新比赛天气和轮次信息
    if detail.get('weather') or detail.get('round_info'):
        match_update = dict(match)
        if detail.get('weather'):
            match_update['weather'] = detail['weather']
        if detail.get('round_info'):
            match_update['round_info'] = detail['round_info']
        update_match(match_update)

    # [V2.6.3] 从ShiJian页面提取准确比分，覆盖赛程列表的缓存值
    home_score = match.get('latest_home_score', 0)
    away_score = match.get('latest_away_score', 0)
    home_half_score = match.get('latest_home_half_score', 0)
    away_half_score = match.get('latest_away_half_score', 0)
    try:
        sj = detail.get('shijian_json', {})
        event_list = sj.get('events', {}).get('eventList', [])
        for e in event_list:
            if e.get('kind') == 'OTHER':
                process = e.get('process', '')
                mp = e.get('matchProcess', {})
                if mp and isinstance(mp, dict):
                    if process == 'HalfTime':
                        home_half_score = mp.get('homeScore', home_half_score)
                        away_half_score = mp.get('guestScore', away_half_score)
                    elif process == 'FullTime':
                        home_score = mp.get('homeScore', home_score)
                        away_score = mp.get('guestScore', away_score)
    except Exception:
        pass

    # 创建快照
    snapshot_id = create_snapshot({
        'match_id': match_id,
        'snapshot_type': snapshot_type,
        'state_code': state_code,
        'state_text': state_text,
        'home_score': home_score,
        'away_score': away_score,
        'home_half_score': home_half_score,
        'away_half_score': away_half_score,
        'elapsed_min': elapsed,
        'shijian_json': json.dumps(detail.get('shijian_json', {}), ensure_ascii=False),
        'analysis_json': json.dumps(detail.get('analysis_json', {}), ensure_ascii=False),
    })

    return snapshot_id, detail


# ==================== [V2.5.7] 任务1：定时自动刷新功能 ====================

import threading

# [V2.5.7] 刷新防冲突锁（手动刷新优先，自动刷新跳过）
_refresh_lock = threading.Lock()


def do_refresh_with_auto_monitor(source='manual'):
    """
    [V2.5.7] 统一的刷新+自动监控触发逻辑（手动/自动共用）
    参数:
        source: 'manual'（手动刷新，阻塞等待锁）或 'auto'（自动刷新，获取不到锁则跳过）
    返回: dict {success, count, repaired, auto_monitored, message}
    """
    # 防冲突：手动刷新阻塞等待，自动刷新非阻塞跳过
    if source == 'auto':
        if not _refresh_lock.acquire(blocking=False):
            logger.info("[自动刷新] 手动刷新进行中，跳过本轮")
            return {'success': False, 'message': '手动刷新进行中，跳过本轮'}
    else:
        _refresh_lock.acquire()

    try:
        # [V2.6.0] 自动刷新时执行VACUUM+ANALYZE，手动刷新时不执行
        count = refresh_schedule(do_maintenance=(source == 'auto'))
        from db import repair_match_date_field, invalidate_sclass_cache
        repaired = repair_match_date_field()
        invalidate_sclass_cache()

        # 自动监控触发：将配置联赛中未结束的比赛加入监控队列
        auto_added = 0
        try:
            from db import get_auto_monitor_leagues, get_unstarted_matches_by_league, add_monitor_task
            auto_leagues = get_auto_monitor_leagues()
            if auto_leagues:
                for league in auto_leagues:
                    candidate_ids = get_unstarted_matches_by_league(league)
                    for mid in candidate_ids:
                        ok, _ = add_monitor_task(mid)
                        if ok:
                            auto_added += 1
        except Exception as e:
            logger.error(f"[V2.5.7] 自动监控触发异常: {e}")

        tag = "自动刷新" if source == 'auto' else "手动刷新"
        logger.info(f"[{tag}] 刷新完成，共{count}场比赛，自动添加{auto_added}场监控")
        return {
            'success': True, 'count': count, 'repaired': repaired,
            'auto_monitored': auto_added,
            'message': f'{tag}完成，共{count}场比赛，自动添加{auto_added}场监控'
        }
    except Exception as e:
        logger.error(f"[V2.5.7] 刷新异常: {e}")
        return {'success': False, 'error': str(e)}
    finally:
        _refresh_lock.release()


def start_auto_refresh_scheduler():
    """
    [V2.5.7] 启动定时自动刷新调度器（APScheduler BackgroundScheduler）
    每天北京时间 AUTO_REFRESH_TIMES 配置的时间点自动刷新
    """
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        from config import AUTO_REFRESH_TIMES, AUTO_REFRESH_TIMEZONE
    except ImportError:
        logger.error("[V2.5.7] APScheduler未安装，定时自动刷新功能不可用")
        return None

    scheduler = BackgroundScheduler(daemon=True, timezone=AUTO_REFRESH_TIMEZONE)

    # 为每个时间点注册定时任务
    for time_str in AUTO_REFRESH_TIMES:
        hour, minute = time_str.split(':')
        trigger = CronTrigger(hour=int(hour), minute=int(minute), timezone=AUTO_REFRESH_TIMEZONE)
        scheduler.add_job(
            func=lambda: do_refresh_with_auto_monitor(source='auto'),
            trigger=trigger,
            id=f'auto_refresh_{time_str}',
            name=f'定时自动刷新 {time_str}',
            replace_existing=True
        )
        logger.info(f"[V2.5.7] 已注册定时刷新任务: 每天 {time_str}（北京时间）")

    scheduler.start()
    logger.info(f"[V2.5.7] 定时自动刷新调度器已启动，共{len(AUTO_REFRESH_TIMES)}个定时任务")
    return scheduler


if __name__ == '__main__':
    init_db()
    print("=== 手动刷新比赛列表 ===")
    result = do_refresh_with_auto_monitor(source='manual')
    print(f"刷新结果: {result}")
