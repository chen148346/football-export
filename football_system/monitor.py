#!/usr/bin/env python3
"""
足球比赛数据文档分析系统 V2.6.3 - 定时快照监控模块
====================================================
模块名称：monitor
版本号：V2.5.5
作者：系统开发人员
日期：2026-07-29

[V2.5.5] 变更说明：
- 防爬延迟参数改用 config.MONITOR_CRAWL_DELAY_MIN/MAX（统一收口）
- shijian_json 空值统一为空字典{}（与 scheduler.py 一致）

功能：
    新增"定时快照监控"功能。用户输入一维比赛ID列表，系统后台自动轮询这些
    比赛的状态，在达到指定时间节点（中场、60分钟、75分钟、完场）时自动抓取
    详情并创建对应类型的快照，为ML"赛中预测"提供非完场训练数据。

V2.5.3 监控拥堵优化（核心变更）：
    1. 批量状态刷新：用refresh_match_status_batch替代逐场refresh_match_status
       一次抓取赛程列表，批量更新所有监控比赛状态（10场从10次抓取降为1次）
    2. 优先级队列：急需快照的比赛优先处理（按elapsed_min接近窗口排序）
    3. 缩短轮询间隔：5分钟→2分钟，避免错过6分钟的快照窗口
    4. 减少防爬延迟：2-5秒→1-2秒（监控场景下可接受）
    5. 比赛间延迟：1-2秒→0.5-1秒

核心设计：
    1. 后台守护线程每2分钟轮询一次监控队列
    2. 4个监控节点：halftime(中场) / min60(60分) / min75(75分) / fulltime(完场)
    3. 防重机制：创建快照前先查snapshots表
    4. 错过即放弃：超出目标区间上限则放弃，不重试
    5. 单线程串行处理，严禁多线程并发

架构师确认的3个设计决策：
    1. 已完场比赛拒绝添加监控（add_monitor_task中校验）
    2. min75快照仅存snapshots表，不在matches表新增字段
    3. 监控完成后保留monitor_tasks记录（ft_status=1），不删除
"""

import time
import random
import json
import logging
import threading
from datetime import datetime

from db import (
    init_db, get_match, update_match, get_active_monitor_tasks,
    update_monitor_task_status, get_snapshot_by_match, create_snapshot
)
from scraper import fetch_match_detail, fetch_shijian_page
from scheduler import refresh_match_status, refresh_match_status_batch
from config import MONITOR_CRAWL_DELAY_MIN, MONITOR_CRAWL_DELAY_MAX

logger = logging.getLogger(__name__)

# ==================== 配置 ====================

# [V2.5.3] 轮询间隔从5分钟缩短为2分钟
# 原因：60分/75分快照窗口仅6分钟，5分钟轮询可能错过窗口
POLL_INTERVAL = 120

# [V2.5.5] 防爬随机延迟改用 config.py 统一参数（原 CRAWL_DELAY_MIN/MAX=1/2）
CRAWL_DELAY_MIN = MONITOR_CRAWL_DELAY_MIN
CRAWL_DELAY_MAX = MONITOR_CRAWL_DELAY_MAX

# 监控节点定义
# (节点名, 目标状态码, 分钟下限, 分钟上限, 放弃阈值, 快照类型)
# 注：中场(ht)节点只判断状态码==2，不判断比赛时间（无放弃阈值）
MONITOR_NODES = [
    ('ht',    2,  None, None, None, 'halftime'),  # 中场：仅判断state_code==2
    ('min60', 3,  57, 63, 63, 'min60'),      # 60分钟：57~63分钟
    ('min75', 3,  72, 78, 78, 'min75'),      # 75分钟：72~78分钟
    ('ft',   -1,   0,  0,  0, 'fulltime'),   # 完场：任意分钟
]

# 全局监控线程实例
_monitor_thread = None
_monitor_lock = threading.Lock()
# V2.5: 暂停标志（导入数据时暂停监控）
_paused = False
_pause_lock = threading.Lock()


# ==================== 核心逻辑 ====================

def _check_and_create_snapshot(match_id, match, node_name, snapshot_type):
    """
    检查是否已有该类型快照，没有则创建
    返回: True=已创建/已存在, False=创建失败
    """
    # 防重：检查是否已存在该类型快照
    existing = get_snapshot_by_match(match_id, snapshot_type)
    if existing:
        logger.info(f"[V2.5.3] 比赛{match_id} 已存在{snapshot_type}快照，跳过")
        # 标记为成功
        update_monitor_task_status(match_id, node_name, 1)
        return True

    # [V2.5.3] 防爬延迟从2-5秒缩短为1-2秒
    delay = random.uniform(CRAWL_DELAY_MIN, CRAWL_DELAY_MAX)
    logger.info(f"[V2.5.3] 比赛{match_id} 准备抓取{snapshot_type}快照，防爬延迟{delay:.1f}秒")
    time.sleep(delay)

    try:
        # 抓取详情
        detail = fetch_match_detail(match_id)
        if not detail or not detail.get('shijian_json'):
            logger.error(f"[V2.5.3] 比赛{match_id} 抓取详情失败")
            return False

        # 创建快照
        state_code = match.get('latest_state_code', 0)
        state_text = match.get('latest_state_text', '')
        elapsed = match.get('latest_elapsed_min', 0) or 0

        home_score = match.get('latest_home_score', 0)
        away_score = match.get('latest_away_score', 0)
        home_half_score = match.get('latest_home_half_score', 0)
        away_half_score = match.get('latest_away_half_score', 0)

        # [V2.6.2] 从ShiJian页面提取准确的比分，覆盖赛程列表的缓存值
        # 赛程列表的fields[9]/fields[10]（半场比分）有缓存延迟，可能还是0-0
        # ShiJian页面的events.eventList中HalfTime/FullTime事件的matchProcess包含准确比分
        try:
            sj = detail.get('shijian_json', {})
            event_list = sj.get('events', {}).get('eventList', [])
            for e in event_list:
                if e.get('kind') == 'OTHER':
                    process = e.get('process', '')
                    mp = e.get('matchProcess', {})
                    if mp and isinstance(mp, dict):
                        mp_home = mp.get('homeScore', 0)
                        mp_away = mp.get('guestScore', 0)
                        if process == 'HalfTime':
                            home_half_score = mp_home
                            away_half_score = mp_away
                            logger.info(f"[V2.6.2] 比赛{match_id} 半场比分校准: {mp_home}-{mp_away}（来自ShiJian HalfTime事件）")
                        elif process == 'FullTime':
                            home_score = mp_home
                            away_score = mp_away
                            logger.info(f"[V2.6.2] 比赛{match_id} 全场比分校准: {mp_home}-{mp_away}（来自ShiJian FullTime事件）")
        except Exception as e:
            logger.warning(f"[V2.6.2] 比赛{match_id} 比分校准失败，使用赛程列表值: {e}")

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

        logger.info(f"[V2.5.3] 比赛{match_id} {snapshot_type}快照创建成功，snapshot_id={snapshot_id}")
        update_monitor_task_status(match_id, node_name, 1)  # 标记成功
        return True

    except Exception as e:
        logger.error(f"[V2.5.3] 比赛{match_id} 创建{snapshot_type}快照异常: {e}")
        update_monitor_task_status(match_id, node_name, 2)  # 标记失败
        return False


def _process_match(task, match):
    """
    [V2.5.3] 处理单个监控任务（接收已刷新的match数据，避免重复抓取）
    [V2.6.1] 上半场elapsed>=43或==1时，请求ShiJian页面获取实时stateCode
    参数:
        task: 监控任务记录
        match: 已刷新的比赛数据（由批量刷新函数提供）
    """
    match_id = task['match_id']

    try:
        state_code = match.get('latest_state_code', 0)
        elapsed = match.get('latest_elapsed_min', 0) or 0

        logger.info(f"[V2.5.3] 比赛{match_id} 状态: state={state_code}, elapsed={elapsed}min")

        # [V2.6.1] 上半场状态校准：elapsed>=43（即将进入中场）或 elapsed==1（headStartTime已更新但状态码缓存延迟）
        # 请求ShiJian页面获取实时stateCode，解决赛程列表缓存导致的状态延迟和elapsed_min跳变问题
        if state_code == 1 and (elapsed >= 43 or elapsed == 1):
            try:
                html, sj_json, _, _ = fetch_shijian_page(match_id)
                if sj_json and sj_json.get('info', {}).get('stateCode') is not None:
                    realtime_state = sj_json['info']['stateCode']
                    if realtime_state != state_code:
                        logger.info(f"[V2.6.1] 比赛{match_id} 实时状态校准: {state_code}→{realtime_state}（赛程缓存延迟）")
                        state_code = realtime_state
                        # 更新数据库中的状态
                        match['latest_state_code'] = realtime_state
                        from config import STATE_CODES
                        match['latest_state_text'] = STATE_CODES.get(realtime_state, '')
                        update_match(match)
            except Exception as e:
                logger.warning(f"[V2.6.1] 比赛{match_id} ShiJian实时状态获取失败，使用缓存状态: {e}")

        # 逐节点判定
        for node_name, target_state, min_min, max_min, abandon_min, snapshot_type in MONITOR_NODES:
            # 跳过已处理的节点（status != 0）
            status_col = f"{node_name}_status"
            current_status = task.get(status_col, 0)
            if current_status != 0:
                continue

            # [V2.6.3] min60/min75 节点需要检查开关是否开启
            if node_name == 'min60' and not task.get('enable_min60', 0):
                continue
            if node_name == 'min75' and not task.get('enable_min75', 0):
                continue

            # 节点判定逻辑
            if node_name == 'ft':
                # 完场节点：state_code == -1
                if state_code == -1:
                    _check_and_create_snapshot(match_id, match, node_name, snapshot_type)
                # 完场节点不放弃，一直等待
            elif node_name == 'ht':
                # 中场节点：仅判断state_code == 2，不判断比赛时间，不放弃
                if state_code == 2:
                    _check_and_create_snapshot(match_id, match, node_name, snapshot_type)
            else:
                # 60分/75分节点：判断状态码+分钟区间
                if state_code == target_state and min_min <= elapsed <= max_min:
                    # 在目标区间内，抓取快照
                    _check_and_create_snapshot(match_id, match, node_name, snapshot_type)
                elif elapsed > abandon_min:
                    # 超出放弃阈值，放弃该节点
                    logger.warning(f"[V2.5.3] 比赛{match_id} {node_name}节点错过窗口(elapsed={elapsed}>{abandon_min})，放弃")
                    update_monitor_task_status(match_id, node_name, 2)  # 标记放弃

    except Exception as e:
        logger.error(f"[V2.5.3] 比赛{match_id} 监控处理异常: {e}")


def _prioritize_tasks(tasks, match_map):
    """
    [V2.5.3] 优先级排序：急需快照的比赛优先处理
    排序规则：
        1. 即将进入或已在快照窗口的比赛优先（elapsed接近57/72/完场）
        2. 已在窗口内的比赛最优先
        3. 未开始的比赛最后
    """
    def priority_key(task):
        match_id = task['match_id']
        match = match_map.get(match_id, {})
        elapsed = match.get('latest_elapsed_min', 0) or 0
        state_code = match.get('latest_state_code', 0)

        # 计算距离最近快照窗口的距离（越小越优先）
        if state_code == -1:
            # 完场，需要fulltime快照，最高优先级
            return 0
        elif state_code == 2:
            # 中场，需要halftime快照，高优先级
            return 1
        elif 57 <= elapsed <= 63:
            # 在60分窗口内，最高优先级
            return 0
        elif 72 <= elapsed <= 78:
            # 在75分窗口内，最高优先级
            return 0
        elif elapsed < 57:
            # 距离60分窗口的距离
            return 57 - elapsed
        elif elapsed < 72:
            # 距离75分窗口的距离
            return 72 - elapsed
        else:
            # 已过75分窗口但未完场
            return 100

    return sorted(tasks, key=priority_key)


def _monitor_loop():
    """[V2.5.3] 后台监控线程主循环（批量轮询架构）"""
    logger.info("[V2.5.3] 定时快照监控线程已启动，轮询间隔2分钟（拥堵优化版）")

    while True:
        try:
            # V2.5: 检查是否被暂停（数据库导入期间）
            if _paused:
                logger.info("[V2.5.3] 监控线程已暂停（数据库导入中），10秒后重试")
                time.sleep(10)
                continue

            # 获取所有进行中的监控任务
            tasks = get_active_monitor_tasks()
            if tasks:
                logger.info(f"[V2.5.3] 本轮轮询：{len(tasks)}场比赛待监控")

            if not tasks:
                time.sleep(POLL_INTERVAL)
                continue

            # [V2.5.3] 批量刷新所有比赛状态（一次抓取赛程列表）
            match_ids = [t['match_id'] for t in tasks]
            match_map = refresh_match_status_batch(match_ids)

            # [V2.5.3] 优先级排序：急需快照的比赛优先处理
            sorted_tasks = _prioritize_tasks(tasks, match_map)

            # 统计急需快照的比赛数量
            urgent_count = 0
            for t in sorted_tasks:
                m = match_map.get(t['match_id'], {})
                sc = m.get('latest_state_code', 0)
                el = m.get('latest_elapsed_min', 0) or 0
                if sc == -1 or sc == 2 or (57 <= el <= 63) or (72 <= el <= 78):
                    urgent_count += 1
            if urgent_count > 0:
                logger.info(f"[V2.5.3] 检测到{urgent_count}场急需快照的比赛，优先处理")

            # 单线程串行处理每场比赛（按优先级顺序）
            for task in sorted_tasks:
                # V2.5: 处理过程中也检查暂停状态
                if _paused:
                    logger.info("[V2.5.3] 监控线程被暂停，中断本轮处理")
                    break

                match = match_map.get(task['match_id'])
                if match:
                    # [V2.5.8] 任务1：未开始比赛跳过逐场处理和延迟，提升监控线程性能
                    # 未开始比赛已在批量状态刷新中更新状态，无需逐场处理
                    # 进行中比赛（state_code in 1,2,3,4）正常执行节点判定和快照抓取
                    state_code = match.get('latest_state_code', 0)
                    if state_code == 0:
                        continue  # 未开始比赛跳过_process_match()和比赛间延迟

                    _process_match(task, match)
                    # [V2.5.3] 比赛间延迟从1-2秒缩短为0.5-1秒
                    time.sleep(random.uniform(0.5, 1.0))

        except Exception as e:
            logger.error(f"[V2.5.3] 监控线程异常: {e}")

        # 等待下一轮轮询
        time.sleep(POLL_INTERVAL)


# ==================== V2.5: 暂停/恢复接口 ====================

def pause_monitor():
    """V2.5: 暂停监控线程（数据库导入前调用）"""
    global _paused
    with _pause_lock:
        _paused = True
    logger.info("[V2.5.3] 监控线程暂停信号已发送")


def resume_monitor():
    """V2.5: 恢复监控线程（数据库导入完成后调用）"""
    global _paused
    with _pause_lock:
        _paused = False
    logger.info("[V2.5.3] 监控线程已恢复")


def is_paused():
    """V2.5: 检查监控线程是否被暂停"""
    return _paused


# ==================== 对外接口 ====================

def start_monitor_thread():
    """启动后台监控线程（如果尚未启动）"""
    global _monitor_thread
    with _monitor_lock:
        if _monitor_thread is None or not _monitor_thread.is_alive():
            _monitor_thread = threading.Thread(target=_monitor_loop, daemon=True, name='V253-Monitor')
            _monitor_thread.start()
            logger.info("[V2.5.3] 监控线程已启动")
        else:
            logger.info("[V2.5.3] 监控线程已在运行中")


def is_monitor_running():
    """检查监控线程是否在运行"""
    return _monitor_thread is not None and _monitor_thread.is_alive()


def run_monitor_once():
    """
    手动触发一次监控轮询（用于测试，不启动后台线程）
    [V2.5.3] 使用批量刷新架构
    """
    tasks = get_active_monitor_tasks()
    logger.info(f"[V2.5.3] 手动触发监控：{len(tasks)}场比赛")

    if not tasks:
        return 0

    # 批量刷新状态
    match_ids = [t['match_id'] for t in tasks]
    match_map = refresh_match_status_batch(match_ids)

    # 优先级排序
    sorted_tasks = _prioritize_tasks(tasks, match_map)

    for task in sorted_tasks:
        match = match_map.get(task['match_id'])
        if match:
            _process_match(task, match)
            time.sleep(random.uniform(0.5, 1.0))
    return len(tasks)


if __name__ == '__main__':
    # 直接运行此模块时，执行一次监控轮询（测试用）
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    init_db()
    count = run_monitor_once()
    print(f"监控轮询完成，处理了{count}场比赛")
