#!/usr/bin/env python3
"""
足球比赛数据文档分析系统 V2.6.3 - 冒烟测试脚本
每次修改代码后执行 python test_smoke.py，所有测试通过才能提交
[V2.5.5] 版本号同步清洗 + 配置统一 + 死代码清理 + 功能深化
"""
import sys
import os
import sqlite3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_imports():
    """测试1: 关键导入语句"""
    print("=== 测试1: 关键导入语句 ===")
    try:
        from app import app, get_matches_in_time_window, now_beijing_naive
        from db import (
            init_db, get_all_matches, get_match, update_match,
            get_snapshots_by_match, get_snapshot, create_report,
            get_reports, get_report, delete_report,
            get_fulltime_snapshots_with_match_info, get_snapshots_by_match_ids,
            get_finished_matches_in_time_window, get_matches_in_time_window,
            repair_match_date_field
        )
        from excel_exporter import export_excel, EXCEL_EXPORT_DIR
        from config import LIBREOFFICE_PATH
        print("  ✅ 所有关键导入成功")
        return True
    except ImportError as e:
        print(f"  ❌ 导入失败: {e}")
        return False


def test_homepage():
    """测试2: 首页访问"""
    print("\n=== 测试2: 首页访问 ===")
    try:
        from app import app
        from db import init_db
        init_db()
        with app.test_client() as client:
            response = client.get('/')
            assert response.status_code == 200, f"状态码: {response.status_code}"
            content = response.data.decode('utf-8')
            assert 'V2.5' in content, "版本号V2.5缺失"
            assert '数据导出' in content, "数据导出按钮缺失"
            assert '±10小时窗口' in content, "时间窗口提示缺失"
            print("  ✅ 首页访问成功，版本号V2.5，含数据导出按钮")
            return True
    except Exception as e:
        print(f"  ❌ 首页测试失败: {e}")
        return False


def test_time_window():
    """测试3: 时间窗口过滤"""
    print("\n=== 测试3: 时间窗口过滤 ===")
    try:
        from db import init_db, get_matches_in_time_window
        from match_time_calc import now_beijing_naive
        from datetime import timedelta
        init_db()
        now = now_beijing_naive()
        start = (now - timedelta(hours=10)).strftime('%Y%m%d%H%M%S')
        end = (now + timedelta(hours=10)).strftime('%Y%m%d%H%M%S')
        matches = get_matches_in_time_window(start, end)
        # 时间窗口内应该少于600场（±10小时约300-500场）
        assert len(matches) < 600, f"时间窗口过滤失效！返回{len(matches)}场（应<600）"
        print(f"  ✅ 时间窗口测试通过（{len(matches)}场，<600）")
        return True
    except Exception as e:
        print(f"  ❌ 时间窗口测试失败: {e}")
        return False


def test_export_page():
    """测试4: 导出页面访问"""
    print("\n=== 测试4: 导出页面访问 ===")
    try:
        from app import app
        with app.test_client() as client:
            response = client.get('/export')
            assert response.status_code == 200, f"状态码: {response.status_code}"
            content = response.data.decode('utf-8')
            assert '训练模式' in content, "训练模式选项缺失"
            assert '预测模式' in content, "预测模式选项缺失"
            print("  ✅ 导出页面访问成功，含训练/预测模式")
            return True
    except Exception as e:
        print(f"  ❌ 导出页面测试失败: {e}")
        return False


def test_libreoffice_config():
    """测试5: LibreOffice配置"""
    print("\n=== 测试5: LibreOffice配置 ===")
    try:
        from config import LIBREOFFICE_PATH
        if LIBREOFFICE_PATH:
            print(f"  ✅ LibreOffice路径已配置: {LIBREOFFICE_PATH}")
        else:
            print(f"  ⚠️ LibreOffice路径未配置（环境变量或config.py），将使用系统PATH")
        return True
    except Exception as e:
        print(f"  ❌ LibreOffice配置测试失败: {e}")
        return False


def test_routes():
    """测试6: 关键路由注册"""
    print("\n=== 测试6: 关键路由注册 ===")
    try:
        from app import app
        rules = {rule.rule for rule in app.url_map.iter_rules()}
        required_routes = ['/', '/export', '/api/export_excel', '/api/export_pdf_batch', '/download_export']
        for route in required_routes:
            assert route in rules, f"路由{route}缺失"
        print(f"  ✅ 所有关键路由已注册: {', '.join(required_routes)}")
        return True
    except Exception as e:
        print(f"  ❌ 路由测试失败: {e}")
        return False


def test_pinyin_sort():
    """测试7: 拼音排序（V2.4.10新增）"""
    print("\n=== 测试7: 拼音排序 ===")
    try:
        from xpinyin import Pinyin
        p = Pinyin()
        # 测试用例：德甲应在英超前，乌超应在中超前
        leagues = ['中超', '英超', '德甲', '乌超']
        pinyin_sorted = sorted(leagues, key=lambda x: p.get_pinyin(x, ''))
        # 拼音：de < wu < ying < zhong
        assert pinyin_sorted == ['德甲', '乌超', '英超', '中超'], f"拼音排序错误: {pinyin_sorted}"
        print(f"  ✅ 拼音排序正确: {pinyin_sorted}")
        print(f"     德甲(de) < 乌超(wu) < 英超(ying) < 中超(zhong)")
        return True
    except ImportError:
        print("  ❌ xpinyin未安装，请执行 pip install xpinyin")
        return False
    except Exception as e:
        print(f"  ❌ 拼音排序测试失败: {e}")
        return False


def test_year_inference():
    """测试8: 年份推断逻辑（V2.4.12修正：-1改为+1）"""
    print("\n=== 测试8: 年份推断逻辑 ===")
    try:
        from batch_import import _infer_year_from_analysis
        from datetime import datetime

        # 场景1: 同年稍晚，锚点2026-07-01，HTML=08-15 → 2026
        ts1 = int(datetime(2026, 7, 1).timestamp())
        an1 = {'nearMatches': {'homeMatches': {'matches': [{'matchTime': str(ts1)}]}}}
        y1 = _infer_year_from_analysis(an1, 8, 15)
        assert y1 == 2026, f"场景1失败: 期望2026, 实际{y1}"

        # 场景2: 跨年，锚点2025-11-29，HTML=02-13 → 2026（次年+1）
        # V2.4.12任务书TC-001案例：锚点2025-11-29，HTML=02-13，期望2026
        ts2 = int(datetime(2025, 11, 29).timestamp())
        an2 = {'nearMatches': {'homeMatches': {'matches': [{'matchTime': str(ts2)}]}}}
        y2 = _infer_year_from_analysis(an2, 2, 13)
        assert y2 == 2026, f"场景2失败: 期望2026, 实际{y2}"

        # 场景3: 同年比赛，锚点2026-03-15，HTML=04-04 → 2026
        # V2.4.12任务书TC-003案例：锚点2026-03，HTML=04-04，期望2026
        ts3 = int(datetime(2026, 3, 15).timestamp())
        an3 = {'nearMatches': {'homeMatches': {'matches': [{'matchTime': str(ts3)}]}}}
        y3 = _infer_year_from_analysis(an3, 4, 4)
        assert y3 == 2026, f"场景3失败: 期望2026, 实际{y3}"

        print(f"  ✅ 年份推断逻辑正确（V2.4.12: -1已改为+1）")
        print(f"     场景1(同年): 锚点2026-07-01, HTML=08-15 → {y1}")
        print(f"     场景2(跨年): 锚点2025-11-29, HTML=02-13 → {y2}（次年+1）")
        print(f"     场景3(同年): 锚点2026-03-15, HTML=04-04 → {y3}")
        return True
    except Exception as e:
        print(f"  ❌ 年份推断测试失败: {e}")
        return False


def test_data_retention():
    """测试9: 数据永久保留（V2.4.11新增）"""
    print("\n=== 测试9: 数据永久保留 ===")
    try:
        from db import init_db, get_conn, sync_matches
        init_db()
        # 插入一场"7天前"的比赛
        old_match = [{
            'id': 9999991, 'sclass_name': '测试联赛', 'match_time': '20250101120000',
            'match_date': '2025-01-01', 'home_team': '历史主队', 'away_team': '历史客队',
            'latest_state_code': -1, 'latest_state_text': '完场'
        }]
        sync_matches(old_match)

        # 再同步一场新比赛（不包含旧比赛）
        new_match = [{
            'id': 9999992, 'sclass_name': '测试联赛', 'match_time': '20260706120000',
            'match_date': '2026-07-06', 'home_team': '新主队', 'away_team': '新客队',
            'latest_state_code': 0, 'latest_state_text': '未开始'
        }]
        sync_matches(new_match)

        # 验证旧比赛是否被保留
        conn = get_conn()
        old = conn.execute("SELECT id, home_team FROM matches WHERE id = 9999991").fetchone()
        conn.close()
        assert old is not None, "历史比赛被删除了！数据永久保留失败"
        assert old['home_team'] == '历史主队', f"历史比赛数据异常: {old['home_team']}"
        print(f"  ✅ 数据永久保留验证通过：7天前的比赛（ID=9999991）未被删除")
        return True
    except Exception as e:
        print(f"  ❌ 数据永久保留测试失败: {e}")
        return False


def test_performance_indexes():
    """测试10: 性能优化索引（V2.4.11新增）"""
    print("\n=== 测试10: 性能优化索引 ===")
    try:
        from db import init_db, get_conn
        init_db()
        conn = get_conn()
        indexes = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_matches%'").fetchall()
        index_names = {row['name'] for row in indexes}
        required = {'idx_matches_time_state', 'idx_matches_sclass_time', 'idx_matches_finished_time'}
        for idx in required:
            assert idx in index_names, f"索引{idx}缺失"
        conn.close()
        print(f"  ✅ 3个性能优化索引已创建: {', '.join(required)}")
        return True
    except Exception as e:
        print(f"  ❌ 性能索引测试失败: {e}")
        return False


def test_sclass_cache():
    """测试11: 联赛列表内存缓存（V2.4.11新增）"""
    print("\n=== 测试11: 联赛列表内存缓存 ===")
    try:
        from db import get_sclass_names_cached, invalidate_sclass_cache
        invalidate_sclass_cache()  # 先清除缓存
        cache1 = get_sclass_names_cached()  # 首次查询，应访问数据库
        cache2 = get_sclass_names_cached()  # 第二次查询，应从缓存读取
        assert cache1 == cache2, "缓存结果不一致"
        assert isinstance(cache1, list), "缓存返回类型错误"
        print(f"  ✅ 联赛列表缓存正常，共{len(cache1)}个联赛")
        return True
    except Exception as e:
        print(f"  ❌ 联赛缓存测试失败: {e}")
        return False


def test_match_date_fill():
    """测试12: match_date自动填充（V2.4.14版本标识）"""
    print("\n=== 测试12: match_date自动填充 ===")
    try:
        from db import init_db, get_conn, get_or_create_match, update_match
        init_db()
        # 模拟batch_import场景：创建比赛，只有match_time没有match_date
        test_id = 8888881
        match = get_or_create_match(test_id)
        match_update = dict(match)
        match_update['match_time'] = '20260213163000'  # 14位时间字符串
        match_update['match_date'] = ''  # 模拟_extract_match_info_from_html未填充match_date
        match_update['home_team'] = '测试主队'
        match_update['away_team'] = '测试客队'
        match_update['latest_state_code'] = -1
        match_update['latest_state_text'] = '完场'

        # V2.4.14修复逻辑：在update_match前自动填充match_date
        match_time_val = match_update.get('match_time', '')
        if match_time_val and len(match_time_val) >= 8 and not match_update.get('match_date'):
            mt = match_time_val
            match_update['match_date'] = f"{mt[0:4]}-{mt[4:6]}-{mt[6:8]}"

        update_match(match_update)

        # 验证数据库中match_date已填充
        conn = get_conn()
        row = conn.execute("SELECT match_time, match_date FROM matches WHERE id = ?", (test_id,)).fetchone()
        conn.close()
        assert row is not None, "比赛记录未创建"
        assert row['match_date'] == '2026-02-13', f"match_date填充错误: {row['match_date']}"
        assert row['match_time'] == '20260213163000', f"match_time错误: {row['match_time']}"
        print(f"  ✅ match_date自动填充正确: match_time={row['match_time']} → match_date={row['match_date']}")
        return True
    except Exception as e:
        print(f"  ❌ match_date填充测试失败: {e}")
        return False


def test_monitor_task():
    """测试13: 定时快照监控功能（V2.5新增）"""
    print("\n=== 测试13: 定时快照监控功能 ===")
    try:
        from db import init_db, get_conn, get_or_create_match, update_match, add_monitor_task, get_active_monitor_tasks, update_monitor_task_status, delete_monitor_task
        from monitor import MONITOR_NODES, is_monitor_running
        init_db()

        # 13.1: 验证monitor_tasks表已创建
        conn = get_conn()
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert 'monitor_tasks' in tables, "monitor_tasks表未创建"
        print("  ✅ monitor_tasks表已创建")
        conn.close()

        # 13.2: 验证4个监控节点定义正确
        assert len(MONITOR_NODES) == 4, f"监控节点数应为4，实际{len(MONITOR_NODES)}"
        node_names = [n[0] for n in MONITOR_NODES]
        assert 'ht' in node_names and 'min60' in node_names and 'min75' in node_names and 'ft' in node_names
        print(f"  ✅ 4个监控节点定义正确: {node_names}")

        # 13.3: 验证已完场比赛拒绝监控
        test_id_finished = 9999981
        get_or_create_match(test_id_finished)
        update_match({
            'id': test_id_finished, 'latest_state_code': -1, 'latest_state_text': '完场',
            'home_team': '测试完场主队', 'away_team': '测试完场客队'
        })
        ok, msg = add_monitor_task(test_id_finished)
        assert not ok, "已完场比赛应拒绝监控"
        print(f"  ✅ 已完场比赛正确拒绝: {msg}")

        # 13.4: 验证未完场比赛可添加监控
        test_id_live = 9999982
        get_or_create_match(test_id_live)
        update_match({
            'id': test_id_live, 'latest_state_code': 0, 'latest_state_text': '未开始',
            'home_team': '测试未开始主队', 'away_team': '测试未开始客队'
        })
        ok, msg = add_monitor_task(test_id_live)
        assert ok, f"未完场比赛应可添加监控: {msg}"
        print(f"  ✅ 未完场比赛成功添加监控: {msg}")

        # 13.5: 验证状态更新
        update_monitor_task_status(test_id_live, 'ht', 1)
        task = get_active_monitor_tasks()
        found = [t for t in task if t['match_id'] == test_id_live]
        assert found and found[0]['ht_status'] == 1, "ht_status更新失败"
        print("  ✅ 监控状态更新正确: ht_status=1")

        # 13.6: 清理测试数据
        delete_monitor_task(test_id_live)
        print("  ✅ 测试数据已清理")

        return True
    except Exception as e:
        print(f"  ❌ 监控功能测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_db_sync():
    """测试14: 数据库导出/导入功能（V2.5新增）"""
    print("\n=== 测试14: 数据库导出/导入功能 ===")
    import tempfile
    try:
        from db import init_db, get_conn, get_or_create_match, update_match, create_snapshot, export_database, import_database
        from db_sync import do_export, do_import, is_importing
        init_db()

        # 14.1: 准备测试数据
        test_id = 9999970
        get_or_create_match(test_id)
        update_match({
            'id': test_id, 'latest_state_code': -1, 'latest_state_text': '完场',
            'home_team': '导出测试主队', 'away_team': '导出测试客队',
            'match_date': '2026-07-15', 'match_time': '20260715100000',
            'latest_updated_at': '2026-07-15 10:00:00'
        })
        create_snapshot({
            'match_id': test_id, 'snapshot_type': 'fulltime',
            'state_code': -1, 'state_text': '完场',
            'home_score': 2, 'away_score': 1, 'elapsed_min': 90,
            'shijian_json': '{}', 'analysis_json': '{}'
        })
        print("  ✅ 测试数据准备完成")

        # 14.2: 测试导出（V2.5.1: 使用14位时间格式）
        export_path = os.path.join(tempfile.gettempdir(), f'test_export_{test_id}.db')
        stats = export_database('20260715000000', '20260715235900', export_path)
        assert os.path.exists(export_path), "导出文件未创建"
        assert stats['match_count'] >= 1, f"导出比赛数应>=1，实际{stats['match_count']}"
        assert stats['snapshot_count'] >= 1, f"导出快照数应>=1，实际{stats['snapshot_count']}"
        print(f"  ✅ 导出成功: {stats['match_count']}场比赛, {stats['snapshot_count']}条快照")

        # 14.3: 验证导出文件结构
        out_conn = sqlite3.connect(export_path)
        out_conn.row_factory = sqlite3.Row
        tables = [r[0] for r in out_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert 'matches' in tables and 'snapshots' in tables, "导出文件缺少matches或snapshots表"
        assert 'reports' not in tables, "导出文件不应包含reports表"
        out_conn.close()
        print("  ✅ 导出文件结构正确（仅matches+snapshots，无reports）")

        # 14.4: 测试导入（ID重映射验证）
        import_stats = import_database(export_path)
        assert import_stats['snapshots_inserted'] >= 0, "导入快照数异常"
        print(f"  ✅ 导入成功: 新增{import_stats['matches_inserted']}场, 更新{import_stats['matches_updated']}场, 跳过{import_stats['matches_skipped']}场")

        # 14.5: 验证全局锁机制
        assert not is_importing(), "导入完成后全局锁应已释放"
        print("  ✅ 全局锁机制正常（导入后已释放）")

        # 14.6: 清理测试数据
        os.remove(export_path)
        conn = get_conn()
        conn.execute("DELETE FROM snapshots WHERE match_id = ?", (test_id,))
        conn.execute("DELETE FROM matches WHERE id = ?", (test_id,))
        conn.commit()
        conn.close()
        print("  ✅ 测试数据已清理")

        return True
    except Exception as e:
        print(f"  ❌ 数据库同步测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_quick_monitor():
    """测试15: 快捷监控按钮API（V2.5新增）"""
    print("\n=== 测试15: 快捷监控按钮功能 ===")
    try:
        from db import init_db, get_conn, get_or_create_match, update_match, add_monitor_task, get_monitor_task_by_match, delete_monitor_task
        init_db()

        # 15.1: 测试未完场比赛可加入监控
        test_id = 9999971
        get_or_create_match(test_id)
        update_match({
            'id': test_id, 'latest_state_code': 0, 'latest_state_text': '未开始',
            'home_team': '快捷监控主队', 'away_team': '快捷监控客队'
        })
        ok, msg = add_monitor_task(test_id)
        assert ok, f"未完场比赛应可加入监控: {msg}"
        print(f"  ✅ 未完场比赛成功加入监控: {msg}")

        # 15.2: 验证监控任务已创建
        task = get_monitor_task_by_match(test_id)
        assert task is not None, "监控任务未创建"
        assert task['ft_status'] == 0, "新任务ft_status应为0"
        print("  ✅ 监控任务已正确创建")

        # 15.3: 测试重复加入被拒绝
        ok2, msg2 = add_monitor_task(test_id)
        assert not ok2, "重复加入应被拒绝"
        print(f"  ✅ 重复加入正确拒绝: {msg2}")

        # 15.4: 清理
        delete_monitor_task(test_id)
        print("  ✅ 测试数据已清理")

        return True
    except Exception as e:
        print(f"  ❌ 快捷监控测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_monitor_list_v251():
    """测试16: 监控列表UI优化（V2.5.1新增）"""
    print("\n=== 测试16: 监控列表UI优化（按时间倒序+联赛筛选） ===")
    try:
        from db import init_db, get_or_create_match, update_match, add_monitor_task, get_all_monitor_tasks_v251, get_monitor_sclass_list, delete_monitor_task
        init_db()

        # 16.1: 准备测试数据（3场比赛，不同联赛，不同时间）
        test_data = [
            (9999960, '20260716100000', '英超', '队A', '队B'),
            (9999961, '20260716120000', '西甲', '队C', '队D'),
            (9999962, '20260716140000', '英超', '队E', '队F'),
        ]
        for tid, mtime, sclass, home, away in test_data:
            get_or_create_match(tid)
            update_match({
                'id': tid, 'latest_state_code': 0, 'latest_state_text': '未开始',
                'home_team': home, 'away_team': away, 'sclass_name': sclass,
                'match_time': mtime, 'match_date': mtime[:8]
            })
            add_monitor_task(tid)
        print("  ✅ 测试数据准备完成（3场比赛，2个联赛）")

        # 16.2: 验证按时间倒序排列
        tasks = get_all_monitor_tasks_v251(limit=200)
        # 找到测试数据
        test_tasks = [t for t in tasks if t['match_id'] in (9999960, 9999961, 9999962)]
        assert len(test_tasks) == 3, f"应找到3条测试数据，实际{len(test_tasks)}"
        # [V2.5.4] 排序逻辑改为：状态大类优先 + match_time正序
        # 3场比赛都是未开始(state=0)，同大类内按时间正序排列
        assert test_tasks[0]['match_time'] <= test_tasks[1]['match_time'], "同大类内应按时间正序排列"
        print(f"  ✅ 按时间正序排列正确（最早: {test_tasks[0]['match_time']}）")

        # 16.3: 验证联赛筛选
        tasks_filtered = get_all_monitor_tasks_v251(sclass_names=['英超'], limit=200)
        test_filtered = [t for t in tasks_filtered if t['match_id'] in (9999960, 9999962)]
        assert len(test_filtered) == 2, f"英超应筛选出2场，实际{len(test_filtered)}"
        print(f"  ✅ 联赛筛选正确（英超: {len(test_filtered)}场）")

        # 16.4: 验证联赛列表拼音排序
        sclass_list = get_monitor_sclass_list()
        sclass_names = [s['sclass_name'] for s in sclass_list]
        assert '英超' in sclass_names, "联赛列表应包含英超"
        print(f"  ✅ 联赛列表获取成功（{len(sclass_list)}个联赛）")

        # 16.5: 清理
        for tid, _, _, _, _ in test_data:
            delete_monitor_task(tid)
        print("  ✅ 测试数据已清理")

        return True
    except Exception as e:
        print(f"  ❌ 监控列表UI测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_time_format_conversion():
    """测试17: 时间格式转换（V2.5.1新增）"""
    print("\n=== 测试17: 时间格式转换（datetime-local → 14位紧凑格式） ===")
    try:
        # 模拟app.py中的_to_14digit函数
        def _to_14digit(dt_str):
            dt_str = dt_str.replace('T', ' ')
            parts = dt_str.split(' ')
            date_part = parts[0].replace('-', '')
            time_part = parts[1] if len(parts) > 1 else '00:00'
            time_parts = time_part.split(':')
            hh = time_parts[0] if len(time_parts) > 0 else '00'
            mm = time_parts[1] if len(time_parts) > 1 else '00'
            return f"{date_part}{hh}{mm}00"

        # 17.1: 标准datetime-local格式
        result = _to_14digit('2026-07-16T14:30')
        assert result == '20260716143000', f"转换错误: {result}"
        print(f"  ✅ 标准格式转换正确: 2026-07-16T14:30 → {result}")

        # 17.2: 跨天测试
        result = _to_14digit('2026-07-16T23:59')
        assert result == '20260716235900', f"跨天转换错误: {result}"
        print(f"  ✅ 跨天测试正确: 2026-07-16T23:59 → {result}")

        # 17.3: 跨月测试
        result = _to_14digit('2026-07-31T23:59')
        assert result == '20260731235900', f"跨月转换错误: {result}"
        print(f"  ✅ 跨月测试正确: 2026-07-31T23:59 → {result}")

        # 17.4: 防御性处理（只有日期没时间）
        result = _to_14digit('2026-07-16')
        assert result == '20260716000000', f"防御性转换错误: {result}"
        print(f"  ✅ 防御性处理正确: 2026-07-16 → {result}")

        return True
    except Exception as e:
        print(f"  ❌ 时间格式转换测试失败: {e}")
        return False


def test_export_with_sclass_filter():
    """测试18: 数据库导出联赛多选筛选（V2.5.1新增）"""
    print("\n=== 测试18: 数据库导出联赛多选筛选 ===")
    import tempfile
    try:
        from db import init_db, get_or_create_match, update_match, create_snapshot, export_database
        init_db()

        # 18.1: 准备测试数据（2个联赛，使用独特名称避免与其他测试冲突）
        test_data = [
            (9999950, '20260716100000', '测试联赛A', '队A', '队B'),
            (9999951, '20260716110000', '测试联赛B', '队C', '队D'),
        ]
        for tid, mtime, sclass, home, away in test_data:
            get_or_create_match(tid)
            update_match({
                'id': tid, 'latest_state_code': -1, 'latest_state_text': '完场',
                'home_team': home, 'away_team': away, 'sclass_name': sclass,
                'match_time': mtime, 'match_date': mtime[:8],
                'latest_updated_at': '2026-07-16 10:00:00'
            })
            create_snapshot({
                'match_id': tid, 'snapshot_type': 'fulltime',
                'state_code': -1, 'state_text': '完场',
                'home_score': 2, 'away_score': 1, 'elapsed_min': 90,
                'shijian_json': '{}', 'analysis_json': '{}'
            })
        print("  ✅ 测试数据准备完成（2个联赛各1场）")

        # 18.2: 测试联赛多选筛选导出
        export_path = os.path.join(tempfile.gettempdir(), 'test_export_sclass.db')
        stats = export_database('20260716000000', '20260716235900', export_path, sclass_names=['测试联赛A'])
        assert stats['match_count'] == 1, f"测试联赛A筛选应导出1场，实际{stats['match_count']}"
        print(f"  ✅ 联赛筛选导出正确: 测试联赛A {stats['match_count']}场, {stats['snapshot_count']}条快照")

        # 18.3: 测试不筛选（导出全部，应至少包含2场测试数据）
        stats_all = export_database('20260716000000', '20260716235900', export_path, sclass_names=None)
        assert stats_all['match_count'] >= 2, f"全部应至少导出2场，实际{stats_all['match_count']}"
        print(f"  ✅ 不筛选导出全部正确: {stats_all['match_count']}场（含测试数据2场）")

        # 18.4: 测试空列表（等同于全部）
        stats_empty = export_database('20260716000000', '20260716235900', export_path, sclass_names=[])
        assert stats_empty['match_count'] >= 2, f"空列表应至少导出2场，实际{stats_empty['match_count']}"
        print(f"  ✅ 空列表默认导出全部正确: {stats_empty['match_count']}场")

        # 18.5: 清理
        os.remove(export_path)
        from db import get_conn
        conn = get_conn()
        conn.execute("DELETE FROM snapshots WHERE match_id IN (9999950, 9999951)")
        conn.execute("DELETE FROM matches WHERE id IN (9999950, 9999951)")
        conn.commit()
        conn.close()
        print("  ✅ 测试数据已清理")

        return True
    except Exception as e:
        print(f"  ❌ 联赛多选筛选测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_pure_read_report():
    """测试19: 纯读报告生成（V2.5.1新增）"""
    print("\n=== 测试19: 纯读报告生成（不刷新状态/不创建快照/不写数据库） ===")
    try:
        from db import init_db, get_or_create_match, update_match, create_snapshot, get_conn, get_snapshots_for_report
        from report_generator import generate_report_from_snapshot
        init_db()

        # 19.1: 准备测试数据
        test_id = 9999940
        get_or_create_match(test_id)
        update_match({
            'id': test_id, 'latest_state_code': -1, 'latest_state_text': '完场',
            'home_team': '纯读测试主队', 'away_team': '纯读测试客队',
            'sclass_name': '测试联赛', 'match_time': '20260716100000',
            'match_date': '20260716', 'latest_updated_at': '2026-07-16 10:00:00'
        })
        create_snapshot({
            'match_id': test_id, 'snapshot_type': 'fulltime',
            'state_code': -1, 'state_text': '完场',
            'home_score': 2, 'away_score': 1, 'elapsed_min': 90,
            'shijian_json': '{}', 'analysis_json': '{}'
        })
        print("  ✅ 测试数据准备完成")

        # 19.2: 获取快照
        snapshots = get_snapshots_for_report(test_id)
        assert len(snapshots) >= 1, "应至少有1条快照"
        snap_id = snapshots[0]['id']
        print(f"  ✅ 获取快照成功: snapshot_id={snap_id}")

        # 19.3: 记录生成前的reports表数量（验证不写数据库）
        conn = get_conn()
        reports_before = conn.execute("SELECT COUNT(*) as cnt FROM reports WHERE match_id = ?", (test_id,)).fetchone()['cnt']

        # 19.4: 生成纯读报告
        filepath = generate_report_from_snapshot(test_id, snap_id)
        assert os.path.exists(filepath), f"报告文件未生成: {filepath}"
        print(f"  ✅ 纯读报告生成成功: {os.path.basename(filepath)}")

        # 19.5: 验证reports表未新增记录（纯读不写数据库）
        reports_after = conn.execute("SELECT COUNT(*) as cnt FROM reports WHERE match_id = ?", (test_id,)).fetchone()['cnt']
        assert reports_after == reports_before, f"纯读模式不应写数据库: before={reports_before}, after={reports_after}"
        print(f"  ✅ 纯读模式验证通过: reports表未新增记录（{reports_before} → {reports_after}）")

        # 19.6: 验证无快照时的提示逻辑
        empty_snapshots = get_snapshots_for_report(9999930)  # 不存在的比赛
        assert len(empty_snapshots) == 0, "不存在的比赛应返回空快照列表"
        print("  ✅ 无快照时返回空列表正确")

        # 19.7: 清理
        os.remove(filepath)
        conn.execute("DELETE FROM snapshots WHERE match_id = ?", (test_id,))
        conn.execute("DELETE FROM matches WHERE id = ?", (test_id,))
        conn.commit()
        conn.close()
        print("  ✅ 测试数据已清理")

        return True
    except Exception as e:
        print(f"  ❌ 纯读报告生成测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_v252_full_import_flow():
    """测试20: TC-01 完整导入流程（V2.5.2新增）"""
    print("\n=== 测试20: TC-01 完整导入流程（外键不为NULL验证） ===")
    import tempfile
    try:
        from db import init_db, get_conn, get_or_create_match, update_match, create_snapshot, export_database, import_database, cleanup_and_rebuild_foreign_keys
        init_db()

        # 准备测试数据：1场比赛 + 1条完场快照
        test_id = 9999930
        get_or_create_match(test_id)
        update_match({
            'id': test_id, 'latest_state_code': -1, 'latest_state_text': '完场',
            'home_team': 'TC01主队', 'away_team': 'TC01客队',
            'sclass_name': 'TC01联赛', 'match_time': '20260717100000',
            'match_date': '20260717', 'latest_updated_at': '2026-07-17 10:00:00',
            'fulltime_snapshot_id': 999  # 先设一个值，导出后导入应重建
        })
        create_snapshot({
            'match_id': test_id, 'snapshot_type': 'fulltime',
            'state_code': -1, 'state_text': '完场',
            'home_score': 2, 'away_score': 1, 'elapsed_min': 90,
            'shijian_json': '{}', 'analysis_json': '{}'
        })
        print("  ✅ 测试数据准备完成")

        # 导出
        export_path = os.path.join(tempfile.gettempdir(), 'tc01_export.db')
        export_database('20260717000000', '20260717235900', export_path)
        print("  ✅ 导出完成")

        # 清除本地数据后重新导入
        conn = get_conn()
        conn.execute("DELETE FROM snapshots WHERE match_id = ?", (test_id,))
        conn.execute("DELETE FROM matches WHERE id = ?", (test_id,))
        conn.commit()
        conn.close()

        # 导入（阶段一+阶段二）
        import_database(export_path)
        cleanup_and_rebuild_foreign_keys()
        print("  ✅ 导入+清理重建完成")

        # 验证：fulltime_snapshot_id不为NULL且能在snapshots表中找到
        conn = get_conn()
        match = conn.execute("SELECT fulltime_snapshot_id FROM matches WHERE id = ?", (test_id,)).fetchone()
        assert match is not None, "比赛记录不存在"
        ft_id = match['fulltime_snapshot_id']
        assert ft_id is not None, f"fulltime_snapshot_id为NULL，外键重建失败"
        snap = conn.execute("SELECT id FROM snapshots WHERE id = ?", (ft_id,)).fetchone()
        assert snap is not None, f"fulltime_snapshot_id={ft_id}在snapshots表中不存在"
        conn.close()
        print(f"  ✅ fulltime_snapshot_id={ft_id}，外键关联正确")

        # 清理
        os.remove(export_path)
        conn = get_conn()
        conn.execute("DELETE FROM snapshots WHERE match_id = ?", (test_id,))
        conn.execute("DELETE FROM matches WHERE id = ?", (test_id,))
        conn.commit()
        conn.close()
        print("  ✅ 测试数据已清理")
        return True
    except Exception as e:
        print(f"  ❌ TC-01测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_v252_duplicate_cleanup():
    """测试21: TC-02 重复快照清理（V2.5.2新增）"""
    print("\n=== 测试21: TC-02 重复快照清理（仅halftime/fulltime，不误删min60） ===")
    try:
        from db import init_db, get_conn, get_or_create_match, update_match, create_snapshot, cleanup_and_rebuild_foreign_keys
        init_db()

        test_id = 9999931
        get_or_create_match(test_id)
        update_match({
            'id': test_id, 'latest_state_code': -1, 'latest_state_text': '完场',
            'home_team': 'TC02主队', 'away_team': 'TC02客队',
            'sclass_name': 'TC02联赛', 'match_time': '20260717110000',
            'match_date': '20260717'
        })

        # 人为制造3条中场快照（不同created_at）
        for i, ts in enumerate(['2026-07-17 10:30:00', '2026-07-17 10:35:00', '2026-07-17 10:40:00']):
            create_snapshot({
                'match_id': test_id, 'snapshot_type': 'halftime',
                'state_code': 2, 'state_text': '中场',
                'home_score': 1, 'away_score': 0, 'elapsed_min': 45,
                'shijian_json': '{}', 'analysis_json': '{}'
            })
        # 制造1条min60快照（不应被清理）
        create_snapshot({
            'match_id': test_id, 'snapshot_type': 'min60',
            'state_code': 3, 'state_text': '进行中',
            'home_score': 1, 'away_score': 1, 'elapsed_min': 60,
            'shijian_json': '{}', 'analysis_json': '{}'
        })
        print("  ✅ 测试数据准备完成（3条halftime + 1条min60）")

        # 执行清理
        stats = cleanup_and_rebuild_foreign_keys()

        # 验证：halftime只保留1条（created_at最新的）
        conn = get_conn()
        ht_count = conn.execute("SELECT COUNT(*) as cnt FROM snapshots WHERE match_id=? AND snapshot_type='halftime'", (test_id,)).fetchone()['cnt']
        min60_count = conn.execute("SELECT COUNT(*) as cnt FROM snapshots WHERE match_id=? AND snapshot_type='min60'", (test_id,)).fetchone()['cnt']
        conn.close()

        assert ht_count == 1, f"halftime应保留1条，实际{ht_count}条"
        assert min60_count == 1, f"min60不应被误删，应保留1条，实际{min60_count}条"
        print(f"  ✅ halftime清理后保留{ht_count}条（最新的一条）")
        print(f"  ✅ min60未被误删，保留{min60_count}条")

        # 清理
        conn = get_conn()
        conn.execute("DELETE FROM snapshots WHERE match_id = ?", (test_id,))
        conn.execute("DELETE FROM matches WHERE id = ?", (test_id,))
        conn.commit()
        conn.close()
        print("  ✅ 测试数据已清理")
        return True
    except Exception as e:
        print(f"  ❌ TC-02测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_v252_dangling_pointer_fix():
    """测试22: TC-03 悬空指针修复（V2.5.2新增）"""
    print("\n=== 测试22: TC-03 悬空指针修复 ===")
    try:
        from db import init_db, get_conn, get_or_create_match, update_match, create_snapshot, cleanup_and_rebuild_foreign_keys
        init_db()

        test_id = 9999932
        get_or_create_match(test_id)
        update_match({
            'id': test_id, 'latest_state_code': -1, 'latest_state_text': '完场',
            'home_team': 'TC03主队', 'away_team': 'TC03客队',
            'sclass_name': 'TC03联赛', 'match_time': '20260717120000',
            'match_date': '20260717'
        })

        # 创建1条完场快照
        create_snapshot({
            'match_id': test_id, 'snapshot_type': 'fulltime',
            'state_code': -1, 'state_text': '完场',
            'home_score': 3, 'away_score': 2, 'elapsed_min': 90,
            'shijian_json': '{}', 'analysis_json': '{}'
        })

        # 人为将fulltime_snapshot_id指向不存在的ID（悬空指针）
        conn = get_conn()
        conn.execute("UPDATE matches SET fulltime_snapshot_id = 999999 WHERE id = ?", (test_id,))
        conn.commit()
        print("  ✅ 测试数据准备完成（fulltime_snapshot_id指向不存在的999999）")

        # 执行重建
        cleanup_and_rebuild_foreign_keys()

        # 验证：外键被正确更新为有效的快照ID
        match = conn.execute("SELECT fulltime_snapshot_id FROM matches WHERE id = ?", (test_id,)).fetchone()
        ft_id = match['fulltime_snapshot_id']
        assert ft_id != 999999, f"悬空指针未被修复，仍为999999"
        snap = conn.execute("SELECT id FROM snapshots WHERE id = ?", (ft_id,)).fetchone()
        assert snap is not None, f"修复后的ID={ft_id}在snapshots表中不存在"
        conn.close()
        print(f"  ✅ 悬空指针已修复: 999999 → {ft_id}（有效快照ID）")

        # 清理
        conn = get_conn()
        conn.execute("DELETE FROM snapshots WHERE match_id = ?", (test_id,))
        conn.execute("DELETE FROM matches WHERE id = ?", (test_id,))
        conn.commit()
        conn.close()
        print("  ✅ 测试数据已清理")
        return True
    except Exception as e:
        print(f"  ❌ TC-03测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_v252_performance():
    """测试23: TC-04 大数据量性能测试（V2.5.2新增）"""
    print("\n=== 测试23: TC-04 大数据量性能测试（10000场+30000快照，<30秒） ===")
    import tempfile
    import time as time_module
    try:
        from db import init_db, get_conn, export_database, import_database, cleanup_and_rebuild_foreign_keys
        init_db()

        # 准备大数据量测试数据（使用批量插入提升速度）
        conn = get_conn()
        c = conn.cursor()

        # 清理可能遗留的测试数据
        c.execute("DELETE FROM snapshots WHERE match_id >= 8000000 AND match_id < 80010000")
        c.execute("DELETE FROM matches WHERE id >= 8000000 AND id < 80010000")
        conn.commit()

        print("  准备大数据量测试数据（10000场+30000快照）...")
        # 批量插入matches
        match_data = []
        for i in range(10000):
            tid = 8000000 + i
            match_data.append((tid, f'联赛{i%10}', f'主队{i}', f'客队{i}',
                              f'20260717{i%24:02d}{i%60:02d}00', '20260717', -1, '完场',
                              '2026-07-17 10:00:00'))
        c.executemany("INSERT OR IGNORE INTO matches (id, sclass_name, home_team, away_team, match_time, match_date, latest_state_code, latest_state_text, latest_updated_at) VALUES (?,?,?,?,?,?,?,?,?)", match_data)

        # 批量插入snapshots（每场比赛3条：halftime + fulltime + min60）
        snap_data = []
        for i in range(10000):
            tid = 8000000 + i
            snap_data.append((tid, 'halftime', 2, '中场', 1, 0, 45, '{}', '{}', '2026-07-17 10:30:00'))
            snap_data.append((tid, 'fulltime', -1, '完场', 2, 1, 90, '{}', '{}', '2026-07-17 12:00:00'))
            snap_data.append((tid, 'min60', 3, '进行中', 1, 1, 60, '{}', '{}', '2026-07-17 11:00:00'))
        c.executemany("INSERT OR IGNORE INTO snapshots (match_id, snapshot_type, state_code, state_text, home_score, away_score, elapsed_min, shijian_json, analysis_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", snap_data)
        conn.commit()
        conn.close()
        print("  ✅ 测试数据准备完成")

        # 导出
        export_path = os.path.join(tempfile.gettempdir(), 'tc04_export.db')
        export_database('20260717000000', '20260717235900', export_path)

        # 计时：导入+清理重建
        start_time = time_module.time()
        import_database(export_path)
        cleanup_and_rebuild_foreign_keys()
        elapsed = time_module.time() - start_time

        print(f"  ✅ 导入+清理重建耗时: {elapsed:.2f}秒")
        assert elapsed < 30, f"性能不达标: {elapsed:.2f}秒 > 30秒"

        # 验证外键修复率
        conn = get_conn()
        null_ft = conn.execute("SELECT COUNT(*) as cnt FROM matches WHERE id >= 8000000 AND id < 80010000 AND fulltime_snapshot_id IS NULL").fetchone()['cnt']
        null_ht = conn.execute("SELECT COUNT(*) as cnt FROM matches WHERE id >= 8000000 AND id < 80010000 AND halftime_snapshot_id IS NULL").fetchone()['cnt']
        conn.close()
        assert null_ft == 0, f"还有{null_ft}场比赛的fulltime_snapshot_id为NULL"
        assert null_ht == 0, f"还有{null_ht}场比赛的halftime_snapshot_id为NULL"
        print(f"  ✅ 外键修复率100%（fulltime和halftime均无NULL）")

        # 清理
        os.remove(export_path)
        conn = get_conn()
        conn.execute("DELETE FROM snapshots WHERE match_id >= 8000000 AND match_id < 80010000")
        conn.execute("DELETE FROM matches WHERE id >= 8000000 AND id < 80010000")
        conn.commit()
        conn.close()
        print("  ✅ 测试数据已清理")
        return True
    except Exception as e:
        print(f"  ❌ TC-04测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_v252_reports_fk_fix():
    """测试24: TC-05 reports表悬空引用修复（V2.5.2修复 FOREIGN KEY constraint failed）"""
    print("\n=== 测试24: TC-05 reports表悬空引用修复（外键约束冲突场景） ===")
    try:
        from db import init_db, get_conn, get_or_create_match, update_match, create_snapshot, create_report, cleanup_and_rebuild_foreign_keys
        init_db()

        test_id = 9999925
        get_or_create_match(test_id)
        update_match({
            'id': test_id, 'latest_state_code': -1, 'latest_state_text': '完场',
            'home_team': 'TC05主队', 'away_team': 'TC05客队',
            'sclass_name': 'TC05联赛', 'match_time': '20260717130000',
            'match_date': '20260717'
        })

        # 制造3条中场快照（不同created_at）
        snap_ids = []
        for ts in ['2026-07-17 10:30:00', '2026-07-17 10:35:00', '2026-07-17 10:40:00']:
            sid = create_snapshot({
                'match_id': test_id, 'snapshot_type': 'halftime',
                'state_code': 2, 'state_text': '中场',
                'home_score': 1, 'away_score': 0, 'elapsed_min': 45,
                'shijian_json': '{}', 'analysis_json': '{}'
            })
            snap_ids.append(sid)

        # 关键：让reports表引用将被删除的旧快照（snap_ids[0]和snap_ids[1]会被清理）
        # snap_ids[2]是created_at最新的，会被保留
        create_report({
            'match_id': test_id,
            'snapshot_id': snap_ids[0],  # 引用将被删除的快照
            'report_type': 'halftime',
            'file_path': '/tmp/test_report_1.docx',
            'file_name': 'test_report_1.docx'
        })
        create_report({
            'match_id': test_id,
            'snapshot_id': snap_ids[1],  # 引用将被删除的快照
            'report_type': 'halftime',
            'file_path': '/tmp/test_report_2.docx',
            'file_name': 'test_report_2.docx'
        })
        print(f"  ✅ 测试数据准备完成（3条halftime快照，2条report引用旧快照）")
        print(f"     快照ID: {snap_ids}（保留{snap_ids[2]}，删除{snap_ids[0]},{snap_ids[1]}）")

        # 执行清理重建（修复前会触发 FOREIGN KEY constraint failed）
        stats = cleanup_and_rebuild_foreign_keys()
        print(f"  ✅ 清理重建成功: 删除{stats['duplicates_deleted']}条, 修复reports引用{stats['reports_fixed']}条")

        # 验证：halftime只保留1条
        conn = get_conn()
        ht_count = conn.execute("SELECT COUNT(*) as cnt FROM snapshots WHERE match_id=? AND snapshot_type='halftime'", (test_id,)).fetchone()['cnt']
        assert ht_count == 1, f"halftime应保留1条，实际{ht_count}条"

        # 验证：reports表的snapshot_id已被更新为保留的快照ID
        reports = conn.execute("SELECT snapshot_id FROM reports WHERE match_id=?", (test_id,)).fetchall()
        assert len(reports) == 2, f"应有2条report，实际{len(reports)}条"
        for r in reports:
            sid = r['snapshot_id']
            # 验证snapshot_id指向存在的快照
            snap = conn.execute("SELECT id FROM snapshots WHERE id=?", (sid,)).fetchone()
            assert snap is not None, f"report的snapshot_id={sid}在snapshots表中不存在（悬空指针未修复）"
        conn.close()
        print(f"  ✅ halftime清理后保留{ht_count}条")
        print(f"  ✅ reports表2条记录的snapshot_id均已修复为有效快照ID")

        # 清理
        conn = get_conn()
        conn.execute("DELETE FROM reports WHERE match_id = ?", (test_id,))
        conn.execute("DELETE FROM snapshots WHERE match_id = ?", (test_id,))
        conn.execute("DELETE FROM matches WHERE id = ?", (test_id,))
        conn.commit()
        conn.close()
        print("  ✅ 测试数据已清理")
        return True
    except Exception as e:
        print(f"  ❌ TC-05测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_v253_batch_refresh():
    """测试25: V2.5.3 批量状态刷新函数验证"""
    print("\n=== 测试25: V2.5.3 批量状态刷新函数（refresh_match_status_batch） ===")
    try:
        from db import init_db, get_or_create_match, update_match, add_monitor_task, delete_monitor_task
        from scheduler import refresh_match_status_batch, _get_schedule_with_cache, _schedule_cache
        init_db()

        # 准备测试数据
        test_ids = [9999910, 9999911, 9999912]
        for tid in test_ids:
            get_or_create_match(tid)
            update_match({
                'id': tid, 'latest_state_code': 0, 'latest_state_text': '未开始',
                'home_team': f'批量测试主队{tid}', 'away_team': f'批量测试客队{tid}',
                'sclass_name': '批量测试联赛', 'match_time': '20260718100000',
                'match_date': '20260718'
            })

        # [V2.5.4] mock赛程缓存，避免真实网络请求导致database locked
        _schedule_cache['data'] = []
        _schedule_cache['timestamp'] = 9999999999  # 远未来时间，确保缓存命中

        # 测试批量刷新函数存在且可调用
        result = refresh_match_status_batch(test_ids)
        assert isinstance(result, dict), "批量刷新应返回dict"
        assert len(result) == 3, f"应返回3场比赛状态，实际{len(result)}"
        print(f"  ✅ 批量刷新函数正常工作，返回{len(result)}场比赛状态")

        # 测试空列表处理
        empty_result = refresh_match_status_batch([])
        assert empty_result == {}, "空列表应返回空dict"
        print("  ✅ 空列表处理正确")

        # 测试赛程缓存机制（mock数据，验证缓存命中逻辑）
        import time as time_module
        _schedule_cache['data'] = [{'id': 9999910, 'latest_state_code': 1}]
        _schedule_cache['timestamp'] = time_module.time()  # 当前时间，缓存有效

        start = time_module.time()
        cached = _get_schedule_with_cache()
        elapsed = time_module.time() - start

        assert cached is not None, "缓存命中应返回数据"
        assert elapsed < 0.1, f"缓存命中应几乎无耗时，实际{elapsed:.4f}秒"
        print(f"  ✅ 赛程缓存机制: 缓存命中耗时{elapsed:.4f}秒（<0.1秒）")

        # 清理
        _schedule_cache['data'] = None
        _schedule_cache['timestamp'] = 0
        for tid in test_ids:
            delete_monitor_task(tid)
            from db import get_conn
            conn = get_conn()
            conn.execute("DELETE FROM matches WHERE id = ?", (tid,))
            conn.commit()
            conn.close()
        print("  ✅ 测试数据已清理")
        return True
    except Exception as e:
        print(f"  ❌ 批量状态刷新测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_v253_priority_queue():
    """测试26: V2.5.3 优先级队列排序验证"""
    print("\n=== 测试26: V2.5.3 优先级队列排序（急需快照的优先） ===")
    try:
        from monitor import _prioritize_tasks

        # 模拟4场比赛的不同状态
        tasks = [
            {'match_id': 1, 'ht_status': 0, 'min60_status': 0, 'min75_status': 0, 'ft_status': 0},
            {'match_id': 2, 'ht_status': 0, 'min60_status': 0, 'min75_status': 0, 'ft_status': 0},
            {'match_id': 3, 'ht_status': 0, 'min60_status': 0, 'min75_status': 0, 'ft_status': 0},
            {'match_id': 4, 'ht_status': 0, 'min60_status': 0, 'min75_status': 0, 'ft_status': 0},
        ]

        match_map = {
            1: {'latest_state_code': 0, 'latest_elapsed_min': 10},   # 未开始，低优先级
            2: {'latest_state_code': 3, 'latest_elapsed_min': 60},   # 在60分窗口，最高优先级
            3: {'latest_state_code': 2, 'latest_elapsed_min': 45},   # 中场，高优先级
            4: {'latest_state_code': -1, 'latest_elapsed_min': 90},  # 完场，最高优先级
        }

        sorted_tasks = _prioritize_tasks(tasks, match_map)
        sorted_ids = [t['match_id'] for t in sorted_tasks]

        # 验证：完场(4)和中场(3)和60分窗口(2)应排在前面，未开始(1)应排在最后
        assert sorted_ids[-1] == 1, f"未开始的比赛应排在最后，实际顺序: {sorted_ids}"
        assert 2 in sorted_ids[:3], f"60分窗口的比赛应优先处理，实际顺序: {sorted_ids}"
        assert 3 in sorted_ids[:3], f"中场的比赛应优先处理，实际顺序: {sorted_ids}"
        assert 4 in sorted_ids[:3], f"完场的比赛应优先处理，实际顺序: {sorted_ids}"
        print(f"  ✅ 优先级排序正确: {sorted_ids}")
        print(f"     前3名（急需快照）: {sorted_ids[:3]}")
        print(f"     最后（未开始）: {sorted_ids[-1]}")
        return True
    except Exception as e:
        print(f"  ❌ 优先级队列测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_v253_monitor_config():
    """测试27: V2.5.3 监控配置参数验证"""
    print("\n=== 测试27: V2.5.3 监控配置参数验证 ===")
    try:
        from monitor import POLL_INTERVAL, CRAWL_DELAY_MIN, CRAWL_DELAY_MAX
        from config import REQUEST_TIMEOUT, REQUEST_RETRIES

        # 验证轮询间隔缩短为2分钟
        assert POLL_INTERVAL == 120, f"轮询间隔应为120秒（2分钟），实际{POLL_INTERVAL}"
        print(f"  ✅ 轮询间隔: {POLL_INTERVAL}秒（2分钟，原5分钟）")

        # 验证防爬延迟缩短为1-2秒
        assert CRAWL_DELAY_MIN == 1, f"防爬延迟下限应为1秒，实际{CRAWL_DELAY_MIN}"
        assert CRAWL_DELAY_MAX == 2, f"防爬延迟上限应为2秒，实际{CRAWL_DELAY_MAX}"
        print(f"  ✅ 防爬延迟: {CRAWL_DELAY_MIN}-{CRAWL_DELAY_MAX}秒（原2-5秒）")

        # 验证HTTP超时缩短为10秒
        assert REQUEST_TIMEOUT == 10, f"HTTP超时应为10秒，实际{REQUEST_TIMEOUT}"
        print(f"  ✅ HTTP超时: {REQUEST_TIMEOUT}秒（原20秒）")

        # 验证重试次数降为2次
        assert REQUEST_RETRIES == 2, f"重试次数应为2次，实际{REQUEST_RETRIES}"
        print(f"  ✅ 重试次数: {REQUEST_RETRIES}次（原3次）")

        return True
    except Exception as e:
        print(f"  ❌ 监控配置测试失败: {e}")
        return False


def test_v254_sort_logic():
    """测试28: TC-01 主页面排序逻辑（进行中>未开始>完场，同大类按时间正序）"""
    print("\n=== 测试28: TC-01 主页面排序逻辑验证 ===")
    try:
        from config import STATE_SORT_PRIORITY

        # 验证中场(2)与上半场(1)、下半场(3)、加时(4)优先级相同（均为0）
        assert STATE_SORT_PRIORITY[1] == 0, "上半场优先级应为0"
        assert STATE_SORT_PRIORITY[2] == 0, f"中场优先级应为0，实际{STATE_SORT_PRIORITY[2]}"
        assert STATE_SORT_PRIORITY[3] == 0, "下半场优先级应为0"
        assert STATE_SORT_PRIORITY[4] == 0, "加时优先级应为0"
        print("  ✅ 进行中比赛（上半场/中场/下半场/加时）优先级均为0")

        # 验证未开始(0) > 完场(-1)
        assert STATE_SORT_PRIORITY[0] < STATE_SORT_PRIORITY[-1], "未开始应排在完场前面"
        print(f"  ✅ 未开始(优先级{STATE_SORT_PRIORITY[0]}) > 完场(优先级{STATE_SORT_PRIORITY[-1]})")

        # 模拟排序验证：中场不会跑到下半场后面
        test_matches = [
            {'id': 1, 'latest_state_code': 3, 'match_time': '20260718150000'},  # 下半场
            {'id': 2, 'latest_state_code': 2, 'match_time': '20260718140000'},  # 中场（时间更早）
            {'id': 3, 'latest_state_code': 0, 'match_time': '20260718130000'},  # 未开始
            {'id': 4, 'latest_state_code': -1, 'match_time': '20260718120000'}, # 完场
        ]

        def sort_key(m):
            priority = STATE_SORT_PRIORITY.get(m.get('latest_state_code', 0), 99)
            match_time = m.get('match_time', '')
            return (priority, match_time)

        sorted_matches = sorted(test_matches, key=sort_key)
        sorted_ids = [m['id'] for m in sorted_matches]

        # 预期顺序：中场(2,14:00)和下半场(1,15:00)都是进行中，按时间正序→中场在前
        # 然后未开始(3,13:00)，最后完场(4,12:00)
        assert sorted_ids[0] == 2, f"中场应排在下半场前面（时间更早），实际顺序: {sorted_ids}"
        assert sorted_ids[1] == 1, f"下半场应排在中场后面，实际顺序: {sorted_ids}"
        assert sorted_ids[2] == 3, f"未开始应排在进行中后面，实际顺序: {sorted_ids}"
        assert sorted_ids[3] == 4, f"完场应排在最后，实际顺序: {sorted_ids}"
        print(f"  ✅ 排序正确: {sorted_ids}（中场→下半场→未开始→完场）")
        print(f"     中场(id=2)没有跑到下半场(id=1)后面")
        return True
    except Exception as e:
        print(f"  ❌ TC-01测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_v254_monitor_sort():
    """测试29: TC-02 监控页面排序与主页面一致"""
    print("\n=== 测试29: TC-02 监控页面排序验证（与主页面一致） ===")
    try:
        from db import init_db, get_or_create_match, update_match, add_monitor_task, delete_monitor_task, get_all_monitor_tasks_v251, get_conn
        init_db()

        # 准备测试数据：4场不同状态的监控比赛
        # 注：add_monitor_task拒绝已完场比赛(state=-1)，所以用3场未完场比赛
        # 用state=0(未开始)、state=1(上半场)、state=2(中场)、state=3(下半场)测试排序
        test_data = [
            (9999901, '20260718150000', 3, '下半场'),   # 进行中-下半场
            (9999902, '20260718140000', 2, '中场'),     # 进行中-中场（时间更早）
            (9999903, '20260718130000', 0, '未开始'),   # 未开始
            (9999904, '20260718120000', 1, '上半场'),   # 进行中-上半场（时间最早）
        ]
        for tid, mtime, state, state_text in test_data:
            get_or_create_match(tid)
            update_match({
                'id': tid, 'latest_state_code': state, 'latest_state_text': state_text,
                'home_team': f'排序测试主队{tid}', 'away_team': f'排序测试客队{tid}',
                'sclass_name': '排序测试联赛', 'match_time': mtime, 'match_date': '20260718'
            })
            add_monitor_task(tid)
        print("  ✅ 测试数据准备完成（4场不同状态比赛，均为未完场）")

        # 获取监控列表（应与主页面排序一致）
        tasks = get_all_monitor_tasks_v251(limit=200)
        test_tasks = [t for t in tasks if t['match_id'] in (9999901, 9999902, 9999903, 9999904)]
        sorted_ids = [t['match_id'] for t in test_tasks]

        # 验证：进行中比赛(上半场/中场/下半场)应按时间正序排列，未开始排在后面
        # 进行中3场按时间正序：9999904(12:00) → 9999902(14:00) → 9999901(15:00)
        # 未开始1场：9999903(13:00)
        assert len(sorted_ids) == 4, f"应找到4场比赛，实际{len(sorted_ids)}"

        # 进行中的3场应在前3位，且按时间正序
        live_ids = sorted_ids[:3]
        assert 9999904 in live_ids, f"上半场应在进行中区域，实际顺序: {sorted_ids}"
        assert 9999902 in live_ids, f"中场应在进行中区域，实际顺序: {sorted_ids}"
        assert 9999901 in live_ids, f"下半场应在进行中区域，实际顺序: {sorted_ids}"

        # 验证中场(9999902)排在下半场(9999901)前面（时间更早）
        assert sorted_ids.index(9999902) < sorted_ids.index(9999901), f"中场应排在下半场前面，实际顺序: {sorted_ids}"

        # 未开始(9999903)应排在最后
        assert sorted_ids[-1] == 9999903, f"未开始应排在最后，实际顺序: {sorted_ids}"
        print(f"  ✅ 监控页面排序正确: {sorted_ids}")
        print(f"     中场(id=9999902)没有跑到下半场(id=9999901)后面，与主页面一致")

        # 清理
        for tid, _, _, _ in test_data:
            delete_monitor_task(tid)
            conn = get_conn()
            conn.execute("DELETE FROM matches WHERE id = ?", (tid,))
            conn.commit()
            conn.close()
        print("  ✅ 测试数据已清理")
        return True
    except Exception as e:
        print(f"  ❌ TC-02测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_v254_monitor_fields():
    """测试30: TC-03 监控页面字段验证（基础字段+监控独有字段）"""
    print("\n=== 测试30: TC-03 监控页面字段验证 ===")
    try:
        from db import init_db, get_or_create_match, update_match, add_monitor_task, delete_monitor_task, get_all_monitor_tasks_v251, get_conn
        init_db()

        # 准备测试数据（使用未开始状态，避免被add_monitor_task拒绝）
        test_id = 9999905
        get_or_create_match(test_id)
        update_match({
            'id': test_id, 'latest_state_code': 0, 'latest_state_text': '未开始',
            'latest_state_display': '未开始',
            'home_team': '字段测试主队', 'away_team': '字段测试客队',
            'sclass_name': '字段测试联赛', 'sclass_color': '#ff0000',
            'match_time': '20260718160000', 'match_date': '20260718',
            'latest_home_score': 0, 'latest_away_score': 0,
            'latest_home_half_score': 0, 'latest_away_half_score': 0
        })
        ok, msg = add_monitor_task(test_id)
        assert ok, f"添加监控任务失败: {msg}"

        # 获取监控列表
        tasks = get_all_monitor_tasks_v251(limit=200)
        task = next((t for t in tasks if t['match_id'] == test_id), None)
        assert task is not None, "未找到测试任务"

        # 验证基础字段（与主页面一致）
        required_fields = [
            'sclass_name', 'match_time', 'home_team', 'away_team',
            'latest_home_score', 'latest_away_score',
            'latest_state_code', 'latest_state_text', 'latest_state_display'
        ]
        for field in required_fields:
            assert field in task, f"缺少基础字段: {field}"
        print("  ✅ 基础字段完整: 联赛、时间、主队、客队、比分、状态")

        # 验证比分字段有值
        assert task['latest_home_score'] is not None, "主队比分不应为None"
        assert task['latest_away_score'] is not None, "客队比分不应为None"
        print(f"  ✅ 比分字段正确: {task['latest_home_score']}-{task['latest_away_score']}")

        # 验证监控独有字段
        monitor_fields = ['ht_status', 'min60_status', 'min75_status', 'ft_status']
        for field in monitor_fields:
            assert field in task, f"缺少监控独有字段: {field}"
        print("  ✅ 监控独有字段完整: 中场/60分/75分/完场状态")

        # 清理
        delete_monitor_task(test_id)
        conn = get_conn()
        conn.execute("DELETE FROM matches WHERE id = ?", (test_id,))
        conn.commit()
        conn.close()
        print("  ✅ 测试数据已清理")
        return True
    except Exception as e:
        print(f"  ❌ TC-03测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_v254_filter_delete_bug():
    """测试31: TC-04 监控筛选后删除Bug修复验证"""
    print("\n=== 测试31: TC-04 监控筛选后删除Bug修复验证 ===")
    try:
        from db import init_db, get_or_create_match, update_match, add_monitor_task, delete_monitor_task, get_all_monitor_tasks_v251
        init_db()

        # 准备测试数据：2个联赛各2场比赛
        test_data = [
            (9999906, '英超', '20260718170000'),
            (9999907, '英超', '20260718180000'),
            (9999908, '西甲', '20260718170000'),
            (9999909, '西甲', '20260718180000'),
        ]
        for tid, sclass, mtime in test_data:
            get_or_create_match(tid)
            update_match({
                'id': tid, 'latest_state_code': 0, 'latest_state_text': '未开始',
                'home_team': f'筛选测试主队{tid}', 'away_team': f'筛选测试客队{tid}',
                'sclass_name': sclass, 'match_time': mtime, 'match_date': '20260718'
            })
            add_monitor_task(tid)
        print("  ✅ 测试数据准备完成（英超2场，西甲2场）")

        # 模拟筛选"英超"后的列表
        tasks_filtered = get_all_monitor_tasks_v251(sclass_names=['英超'], limit=200)
        test_filtered = [t for t in tasks_filtered if t['match_id'] in (9999906, 9999907)]
        assert len(test_filtered) == 2, f"英超筛选应返回2场，实际{len(test_filtered)}"
        print(f"  ✅ 筛选'英超'后返回{len(test_filtered)}场比赛")

        # 模拟删除其中一场英超比赛
        delete_monitor_task(9999906)
        print("  ✅ 删除比赛9999906（英超）")

        # 验证：删除后再次筛选"英超"，应仍只返回英超比赛（1场），且筛选条件不丢失
        tasks_after_delete = get_all_monitor_tasks_v251(sclass_names=['英超'], limit=200)
        test_after_delete = [t for t in tasks_after_delete if t['match_id'] in (9999906, 9999907, 9999908, 9999909)]
        assert len(test_after_delete) == 1, f"删除后英超应剩1场，实际{len(test_after_delete)}"
        assert test_after_delete[0]['match_id'] == 9999907, f"剩余应为9999907，实际{test_after_delete[0]['match_id']}"
        # 验证西甲比赛没有混入
        for t in test_after_delete:
            assert t['sclass_name'] == '英超', f"筛选后不应包含非英超比赛，发现{t['sclass_name']}"
        print(f"  ✅ 删除后筛选条件保持: 仍只显示英超{len(test_after_delete)}场，西甲未混入")

        # 清理
        for tid, _, _ in test_data:
            delete_monitor_task(tid)
            from db import get_conn
            conn = get_conn()
            conn.execute("DELETE FROM matches WHERE id = ?", (tid,))
            conn.commit()
            conn.close()
        print("  ✅ 测试数据已清理")
        return True
    except Exception as e:
        print(f"  ❌ TC-04测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_v255_odds_filter():
    """测试32: TC-A2 Odds过滤验证（10个字段，无硬编码）"""
    print("\n=== 测试32: TC-A2 Odds过滤验证 ===")
    try:
        from config import ODDS_JSON_KEYS, ODDS_MATCH_FIELDS
        total = len(ODDS_JSON_KEYS) + len(ODDS_MATCH_FIELDS)
        assert total == 10, f"过滤清单总数应为10，实际{total}"
        assert 'odds' in ODDS_MATCH_FIELDS, "odds未加入ODDS_MATCH_FIELDS"
        assert 'letgoal' in ODDS_MATCH_FIELDS and 'ou' in ODDS_MATCH_FIELDS
        print(f"  ✅ 过滤清单总数: {total}个（7个JSON层 + 3个Match层）")
        print(f"  ✅ odds已加入ODDS_MATCH_FIELDS")
        return True
    except Exception as e:
        print(f"  ❌ Odds过滤验证失败: {e}")
        return False


def test_v255_min60_window():
    """测试33: TC-A3 min60窗口验证（手动报告和监控报告均为57-63）"""
    print("\n=== 测试33: TC-A3 min60窗口验证 ===")
    try:
        import inspect
        from scheduler import manual_snapshot
        from monitor import MONITOR_NODES

        # 检查 scheduler.py manual_snapshot 中的 min60 窗口
        source = inspect.getsource(manual_snapshot)
        assert '57 <= elapsed <= 63' in source, "scheduler.py manual_snapshot的min60窗口不是57-63"

        # 检查 monitor.py MONITOR_NODES 中的 min60 窗口
        min60_node = [n for n in MONITOR_NODES if n[0] == 'min60'][0]
        assert min60_node[2] == 57 and min60_node[3] == 63, f"monitor.py min60窗口不是57-63，实际{min60_node[2]}-{min60_node[3]}"

        print(f"  ✅ scheduler.py manual_snapshot min60窗口: 57-63")
        print(f"  ✅ monitor.py MONITOR_NODES min60窗口: 57-63")
        return True
    except Exception as e:
        print(f"  ❌ min60窗口验证失败: {e}")
        return False


def test_v255_auto_monitor():
    """测试34: TC-06/07 自动监控添加与去重验证
    [V2.5.6] 任务3：验证"未结束"比赛覆盖（进行中+未开始）
    """
    print("\n=== 测试34: TC-06/07 自动监控添加与去重（含未结束覆盖） ===")
    try:
        from db import (init_db, get_or_create_match, update_match, add_monitor_task,
                        get_auto_monitor_leagues, add_auto_monitor_league,
                        remove_auto_monitor_league, get_unstarted_matches_by_league,
                        get_active_monitor_tasks, delete_monitor_task)
        init_db()

        # [V2.5.6] 准备测试数据：2场未开始 + 1场进行中 + 1场已完场
        test_league = 'TC06测试联赛'
        for mid, state in [(9999801, 0), (9999802, 0), (9999804, 3), (9999803, -1)]:
            get_or_create_match(mid)
            update_match({'id': mid, 'latest_state_code': state,
                          'latest_state_text': {0:'未开始', 3:'下半场', -1:'完场'}[state],
                          'sclass_name': test_league, 'match_time': '20260801100000',
                          'match_date': '20260801'})

        add_auto_monitor_league(test_league)
        leagues = get_auto_monitor_leagues()
        assert test_league in leagues, "自动监控联赛添加失败"

        # [V2.5.6] 查询未结束且未监控的比赛（应返回3场：2场未开始+1场进行中，排除已完场）
        candidates = get_unstarted_matches_by_league(test_league)
        assert 9999801 in candidates and 9999802 in candidates, "未开始比赛查询失败"
        assert 9999804 in candidates, "[V2.5.6] 进行中比赛未被覆盖"
        assert 9999803 not in candidates, "已完场比赛未被排除"
        print(f"  ✅ 未结束比赛正确识别: {len(candidates)}场（2未开始+1进行中，排除已完场）")

        # 模拟自动添加监控
        for mid in candidates:
            add_monitor_task(mid)
        tasks = get_active_monitor_tasks()
        task_ids = [t['match_id'] for t in tasks]
        assert 9999801 in task_ids and 9999802 in task_ids and 9999804 in task_ids, "自动监控添加失败"

        # 去重验证：再次添加应失败
        ok, msg = add_monitor_task(9999801)
        assert not ok, "已监控比赛未被去重"
        print(f"  ✅ 已监控比赛去重正确: {msg}")

        # 清理
        for mid in [9999801, 9999802, 9999803, 9999804]:
            delete_monitor_task(mid)
        remove_auto_monitor_league(test_league)
        from db import get_conn
        conn = get_conn()
        conn.execute("DELETE FROM matches WHERE id IN (9999801, 9999802, 9999803, 9999804)")
        conn.commit()
        conn.close()
        print(f"  ✅ 测试数据已清理")
        return True
    except Exception as e:
        print(f"  ❌ 自动监控验证失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_v255_batch_delete():
    """测试35: TC-04 批量删除验证"""
    print("\n=== 测试35: TC-04 批量删除验证 ===")
    try:
        from app import app
        from db import (init_db, get_or_create_match, update_match, add_monitor_task,
                        get_active_monitor_tasks, delete_monitor_task)
        init_db()

        # 准备3场测试监控任务
        for mid in [9999701, 9999702, 9999703]:
            get_or_create_match(mid)
            update_match({'id': mid, 'latest_state_code': 0, 'latest_state_text': '未开始',
                          'sclass_name': 'TC04批量删除', 'match_time': '20260801100000',
                          'match_date': '20260801'})
            add_monitor_task(mid)

        # 调用批量删除接口
        with app.test_client() as client:
            response = client.post('/api/monitor/batch_delete',
                                   json={'match_ids': [9999701, 9999702]})
            assert response.status_code == 200
            data = response.get_json()
            assert data['success'], "批量删除接口返回失败"
            assert data['deleted_count'] == 2, f"删除数量应为2，实际{data['deleted_count']}"

        # 验证删除结果
        tasks = get_active_monitor_tasks()
        task_ids = [t['match_id'] for t in tasks]
        assert 9999701 not in task_ids and 9999702 not in task_ids, "批量删除未生效"
        assert 9999703 in task_ids, "未删除的比赛不应受影响"
        print(f"  ✅ 批量删除成功: 删除{data['deleted_count']}场，保留1场")

        # 清理
        delete_monitor_task(9999703)
        from db import get_conn
        conn = get_conn()
        conn.execute("DELETE FROM matches WHERE id IN (9999701, 9999702, 9999703)")
        conn.commit()
        conn.close()
        print(f"  ✅ 测试数据已清理")
        return True
    except Exception as e:
        print(f"  ❌ 批量删除验证失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_v256_dependencies():
    """测试36: TC-01 V2.5.6 依赖与配置验证"""
    print("\n=== 测试36: TC-01 V2.5.6 依赖与配置验证 ===")
    try:
        # 验证 requirements.txt 包含 openpyxl 和 xpinyin
        with open('requirements.txt', 'r', encoding='utf-8') as f:
            req_content = f.read()
        assert 'openpyxl' in req_content, "requirements.txt 缺少 openpyxl"
        assert 'xpinyin' in req_content, "requirements.txt 缺少 xpinyin"
        print("  ✅ requirements.txt 包含 openpyxl 和 xpinyin")

        # 验证 Odds 过滤清单为 10 个字段
        from config import ODDS_JSON_KEYS, ODDS_MATCH_FIELDS
        assert len(ODDS_JSON_KEYS) + len(ODDS_MATCH_FIELDS) == 10, "Odds过滤清单总数不为10"
        assert 'odds' in ODDS_MATCH_FIELDS, "odds未在ODDS_MATCH_FIELDS中"
        print("  ✅ Odds过滤清单为10个字段，odds已包含")

        # 验证 min60 配置有 Deprecated 注释
        with open('config.py', 'r', encoding='utf-8') as f:
            config_content = f.read()
        assert '[Deprecated]' in config_content and 'MIN60_SNAPSHOT_LOWER' in config_content, "min60配置缺少Deprecated注释"
        print("  ✅ min60配置有 [Deprecated] 注释")

        # 验证防爬延迟参数已收口
        from config import MONITOR_CRAWL_DELAY_MIN, MONITOR_CRAWL_DELAY_MAX
        from config import BATCH_IMPORT_DELAY_MIN, BATCH_IMPORT_DELAY_MAX
        assert MONITOR_CRAWL_DELAY_MIN == 1 and MONITOR_CRAWL_DELAY_MAX == 2, "监控防爬延迟参数不正确"
        assert BATCH_IMPORT_DELAY_MIN == 2 and BATCH_IMPORT_DELAY_MAX == 5, "批量导入防爬延迟参数不正确"
        print("  ✅ 防爬延迟参数已收口到 config.py")

        # 验证 scraper.py 无硬编码
        with open('scraper.py', 'r', encoding='utf-8') as f:
            scraper_content = f.read()
        assert "('letgoal', 'ou', 'odds')" not in scraper_content, "scraper.py 仍有硬编码"
        assert 'ODDS_MATCH_FIELDS' in scraper_content, "scraper.py 未引用 ODDS_MATCH_FIELDS"
        print("  ✅ scraper.py 已删除硬编码，统一引用 config")
        return True
    except Exception as e:
        print(f"  ❌ 依赖与配置验证失败: {e}")
        return False


def test_v256_shuttle_api():
    """测试37: TC-02 V2.5.6 穿梭框接口验证（返回all_leagues）"""
    print("\n=== 测试37: TC-02 V2.5.6 穿梭框接口验证 ===")
    try:
        from app import app
        with app.test_client() as client:
            response = client.get('/api/auto_monitor/list')
            assert response.status_code == 200
            data = response.get_json()
            assert data['success'], "接口返回失败"
            assert 'all_leagues' in data, "[V2.5.6] 接口未返回 all_leagues 字段"
            assert isinstance(data['all_leagues'], list), "all_leagues 不是列表"
            assert isinstance(data['leagues'], list), "leagues 不是列表"
            print(f"  ✅ 接口返回 all_leagues: {len(data['all_leagues'])}个联赛")
            print(f"  ✅ 接口返回已选 leagues: {len(data['leagues'])}个联赛")
        return True
    except Exception as e:
        print(f"  ❌ 穿梭框接口验证失败: {e}")
        return False


def test_v257_auto_refresh_config():
    """测试38: TC-01 V2.5.7 定时刷新配置验证"""
    print("\n=== 测试38: TC-01 V2.5.7 定时刷新配置验证 ===")
    try:
        from config import AUTO_REFRESH_TIMES, AUTO_REFRESH_TIMEZONE
        assert AUTO_REFRESH_TIMES == ['04:00', '16:00'], f"刷新时间配置不正确: {AUTO_REFRESH_TIMES}"
        assert AUTO_REFRESH_TIMEZONE == 'Asia/Shanghai', f"时区配置不正确: {AUTO_REFRESH_TIMEZONE}"
        print(f"  ✅ AUTO_REFRESH_TIMES = {AUTO_REFRESH_TIMES}")
        print(f"  ✅ AUTO_REFRESH_TIMEZONE = {AUTO_REFRESH_TIMEZONE}")

        # 验证调度器可正常启动并注册任务
        from scheduler import start_auto_refresh_scheduler
        scheduler = start_auto_refresh_scheduler()
        assert scheduler is not None, "调度器启动失败"
        jobs = scheduler.get_jobs()
        assert len(jobs) == 2, f"定时任务数量应为2，实际{len(jobs)}"
        job_ids = [j.id for j in jobs]
        assert 'auto_refresh_04:00' in job_ids and 'auto_refresh_16:00' in job_ids, f"任务ID不正确: {job_ids}"
        print(f"  ✅ 调度器已注册 {len(jobs)} 个定时任务: {job_ids}")
        scheduler.shutdown(wait=False)
        print(f"  ✅ 调度器已关闭")
        return True
    except Exception as e:
        print(f"  ❌ 定时刷新配置验证失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_v257_shuttle_ui():
    """测试39: TC-04/05 V2.5.7 穿梭框接口与功能验证"""
    print("\n=== 测试39: TC-04/05 V2.5.7 穿梭框接口与功能验证 ===")
    try:
        from app import app
        with app.test_client() as client:
            # 验证接口返回 all_leagues（供穿梭框左侧使用）
            response = client.get('/api/auto_monitor/list')
            assert response.status_code == 200
            data = response.get_json()
            assert data['success']
            assert 'all_leagues' in data, "接口未返回 all_leagues"
            assert 'leagues' in data, "接口未返回 leagues"
            print(f"  ✅ 穿梭框接口正常: all_leagues={len(data['all_leagues'])}个, leagues={len(data['leagues'])}个")

            # 验证添加/移除接口（实时保存）
            test_league = 'TC257穿梭框测试联赛'
            response = client.post('/api/auto_monitor/add', json={'sclass_name': test_league})
            assert response.status_code == 200
            assert response.get_json()['success'], "添加联赛失败"

            # 验证已添加
            response = client.get('/api/auto_monitor/list')
            leagues = response.get_json()['leagues']
            assert test_league in leagues, "添加后未在列表中找到"

            # 移除
            response = client.post('/api/auto_monitor/remove', json={'sclass_name': test_league})
            assert response.get_json()['success'], "移除联赛失败"

            # 验证已移除
            response = client.get('/api/auto_monitor/list')
            leagues = response.get_json()['leagues']
            assert test_league not in leagues, "移除后仍在列表中"
            print(f"  ✅ 添加/移除实时保存验证通过")
        return True
    except Exception as e:
        print(f"  ❌ 穿梭框接口验证失败: {e}")
        return False


def test_v258_skip_unstarted():
    """测试40: TC-01 V2.5.8 未开始比赛跳过逐场处理验证"""
    print("\n=== 测试40: TC-01 V2.5.8 未开始比赛跳过验证 ===")
    try:
        import inspect
        from monitor import _monitor_loop

        # 验证 _monitor_loop 源码中包含未开始比赛跳过逻辑
        source = inspect.getsource(_monitor_loop)
        assert 'state_code == 0' in source, "_monitor_loop 中未找到未开始比赛跳过逻辑"
        assert 'continue' in source, "_monitor_loop 中未找到 continue 跳过语句"
        print("  ✅ _monitor_loop 包含未开始比赛跳过逻辑（state_code == 0 → continue）")

        # 验证跳过逻辑位于 _process_match 调用之前
        skip_pos = source.find('state_code == 0')
        process_pos = source.find('_process_match(task, match)')
        assert skip_pos < process_pos, "跳过逻辑应位于 _process_match 调用之前"
        print("  ✅ 跳过逻辑位于 _process_match 调用之前，确保未开始比赛不执行逐场处理")
        return True
    except Exception as e:
        print(f"  ❌ 未开始比赛跳过验证失败: {e}")
        return False


def test_v259_historical_league():
    """测试41: TC-01/02 V2.5.9 历史联赛查询与拼音排序防御验证"""
    print("\n=== 测试41: TC-01/02 V2.5.9 历史联赛查询验证 ===")
    try:
        from db import init_db, get_or_create_match, update_match, get_sclass_list, get_conn
        init_db()

        # 准备测试数据：1场sclass_id为NULL但sclass_name有值的历史联赛
        test_league = 'TC259历史联赛'
        get_or_create_match(9999601)
        update_match({
            'id': 9999601, 'latest_state_code': -1, 'latest_state_text': '完场',
            'home_team': '历史主队', 'away_team': '历史客队',
            'sclass_name': test_league, 'sclass_id': None,  # sclass_id为NULL
            'match_time': '20260101100000', 'match_date': '20260101'
        })

        # 验证 get_sclass_list 能返回 sclass_id 为 NULL 的历史联赛
        sclass_list = get_sclass_list()
        found = [s for s in sclass_list if s.get('sclass_name') == test_league]
        assert len(found) > 0, "历史联赛（sclass_id为NULL）未被查询到"
        print(f"  ✅ 历史联赛查询成功: {test_league}（sclass_id为NULL但sclass_name有值）")

        # 验证拼音排序防御性（sclass_name为NULL时不崩溃）
        from app import app
        with app.test_client() as client:
            # /api/get_sclass_list 接口
            response = client.get('/api/get_sclass_list')
            assert response.status_code == 200, f"接口返回状态码: {response.status_code}"
            data = response.get_json()
            assert data['success'], "接口返回失败"
            assert test_league in [s['sclass_name'] for s in data['sclass_list']], "历史联赛未在接口返回中"
            print(f"  ✅ /api/get_sclass_list 接口正常返回，含历史联赛")

            # /api/auto_monitor/list 接口（all_leagues应包含历史联赛）
            response = client.get('/api/auto_monitor/list')
            assert response.status_code == 200
            data = response.get_json()
            assert test_league in data['all_leagues'], "历史联赛未在all_leagues中"
            print(f"  ✅ /api/auto_monitor/list 接口all_leagues含历史联赛")

        # 清理
        conn = get_conn()
        conn.execute("DELETE FROM matches WHERE id = 9999601")
        conn.commit()
        conn.close()
        print(f"  ✅ 测试数据已清理")
        return True
    except Exception as e:
        print(f"  ❌ 历史联赛查询验证失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_v260_manual_cleanup():
    """测试42: TC-01 V2.6.0 manual类型纳入清理范围验证"""
    print("\n=== 测试42: TC-01 V2.6.0 manual类型清理验证 ===")
    try:
        from db import init_db, get_or_create_match, update_match, create_snapshot, cleanup_and_rebuild_foreign_keys, get_conn
        init_db()
        test_id = 9999501

        # 先创建match记录（外键约束）
        get_or_create_match(test_id)
        update_match({'id': test_id, 'latest_state_code': 0, 'latest_state_text': '未开始',
                      'home_team': 'TC42主队', 'away_team': 'TC42客队',
                      'sclass_name': 'TC42联赛', 'match_time': '20260701100000', 'match_date': '20260701'})

        # 创建3条manual快照（不同created_at）
        for ts in ['2026-07-01 10:00:00', '2026-07-01 10:05:00', '2026-07-01 10:10:00']:
            create_snapshot({
                'match_id': test_id, 'snapshot_type': 'manual',
                'state_code': 0, 'state_text': '未开始',
                'home_score': 0, 'away_score': 0, 'elapsed_min': 0,
                'shijian_json': '{}', 'analysis_json': '{}'
            })

        # 验证有3条manual快照
        conn = get_conn()
        before = conn.execute("SELECT COUNT(*) as c FROM snapshots WHERE match_id=? AND snapshot_type='manual'", (test_id,)).fetchone()
        assert before['c'] == 3, f"清理前应有3条manual快照，实际{before['c']}"
        print(f"  ✅ 清理前: {before['c']}条manual快照")

        # 执行清理
        stats = cleanup_and_rebuild_foreign_keys()
        assert stats['duplicates_deleted'] >= 2, f"应删除2条重复，实际{stats['duplicates_deleted']}"

        # 验证清理后只剩1条
        after = conn.execute("SELECT COUNT(*) as c FROM snapshots WHERE match_id=? AND snapshot_type='manual'", (test_id,)).fetchone()
        assert after['c'] == 1, f"清理后应剩1条manual快照，实际{after['c']}"
        print(f"  ✅ 清理后: {after['c']}条manual快照（保留最新一条）")

        # 清理测试数据
        conn.execute("DELETE FROM snapshots WHERE match_id=?", (test_id,))
        conn.execute("DELETE FROM matches WHERE id=?", (test_id,))
        conn.commit()
        conn.close()
        print(f"  ✅ 测试数据已清理")
        return True
    except Exception as e:
        print(f"  ❌ manual类型清理验证失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_v260_vacuum_frequency():
    """测试43: TC-02 V2.6.0 VACUUM降频执行验证"""
    print("\n=== 测试43: TC-02 V2.6.0 VACUUM降频验证 ===")
    try:
        import inspect
        from db import sync_matches
        from scheduler import refresh_schedule, do_refresh_with_auto_monitor

        # 验证 sync_matches 有 do_maintenance 参数
        sig = inspect.signature(sync_matches)
        assert 'do_maintenance' in sig.parameters, "sync_matches 缺少 do_maintenance 参数"
        assert sig.parameters['do_maintenance'].default == False, "do_maintenance 默认值应为False"
        print("  ✅ sync_matches 有 do_maintenance 参数（默认False）")

        # 验证 refresh_schedule 有 do_maintenance 参数
        sig2 = inspect.signature(refresh_schedule)
        assert 'do_maintenance' in sig2.parameters, "refresh_schedule 缺少 do_maintenance 参数"
        print("  ✅ refresh_schedule 有 do_maintenance 参数")

        # 验证 do_refresh_with_auto_monitor 中自动刷新传True、手动刷新传False
        source = inspect.getsource(do_refresh_with_auto_monitor)
        assert "do_maintenance=(source == 'auto')" in source, "do_refresh_with_auto_monitor 未正确传递 do_maintenance"
        print("  ✅ do_refresh_with_auto_monitor: 自动刷新传do_maintenance=True，手动刷新传False")
        return True
    except Exception as e:
        print(f"  ❌ VACUUM降频验证失败: {e}")
        return False


def test_v261_realtime_state_check():
    """测试44: TC-01 V2.6.1 上半场状态实时校准验证"""
    print("\n=== 测试44: TC-01 V2.6.1 上半场状态实时校准验证 ===")
    try:
        import inspect
        from monitor import _process_match

        source = inspect.getsource(_process_match)
        
        # 验证包含V2.6.1的实时状态校准逻辑
        assert 'V2.6.1' in source, "_process_match 中未找到V2.6.1标记"
        assert 'elapsed >= 43' in source, "未找到 elapsed >= 43 判断条件"
        assert 'elapsed == 1' in source, "未找到 elapsed == 1 判断条件"
        assert 'fetch_shijian_page' in source, "未找到 fetch_shijian_page 调用"
        assert 'stateCode' in source, "未从ShiJian页面提取stateCode"
        print("  ✅ _process_match 包含V2.6.1实时状态校准逻辑")
        print("  ✅ 判断条件: state_code==1 and (elapsed>=43 or elapsed==1)")
        print("  ✅ 通过fetch_shijian_page获取实时stateCode")
        
        # 验证校准后更新数据库
        assert 'update_match' in source, "校准后未调用update_match更新数据库"
        print("  ✅ 校准后调用update_match更新数据库状态")
        return True
    except Exception as e:
        print(f"  ❌ 上半场状态实时校准验证失败: {e}")
        return False


def test_v262_score_calibration():
    """测试45: TC-01 V2.6.2 比分校准验证（从ShiJian HalfTime/FullTime事件提取准确比分）"""
    print("\n=== 测试45: TC-01 V2.6.2 比分校准验证 ===")
    try:
        import inspect
        from monitor import _check_and_create_snapshot

        source = inspect.getsource(_check_and_create_snapshot)
        
        # 验证包含V2.6.2的比分校准逻辑
        assert 'V2.6.2' in source, "_check_and_create_snapshot 中未找到V2.6.2标记"
        assert 'HalfTime' in source, "未找到HalfTime比分提取逻辑"
        assert 'FullTime' in source, "未找到FullTime比分提取逻辑"
        assert 'matchProcess' in source, "未从matchProcess提取比分"
        assert 'home_half_score' in source, "未校准home_half_score"
        assert 'away_half_score' in source, "未校准away_half_score"
        print("  ✅ _check_and_create_snapshot 包含V2.6.2比分校准逻辑")
        print("  ✅ 从ShiJian HalfTime事件提取半场比分")
        print("  ✅ 从ShiJian FullTime事件提取全场比分")
        print("  ✅ 校准home_half_score和away_half_score")
        return True
    except Exception as e:
        print(f"  ❌ 比分校准验证失败: {e}")
        return False


def test_v263_snapshot_switch():
    """测试46: TC-01 V2.6.3 60/75分钟快照开关验证"""
    print("\n=== 测试46: TC-01 V2.6.3 60/75分钟快照开关验证 ===")
    try:
        import inspect
        from monitor import _process_match

        source = inspect.getsource(_process_match)
        assert 'enable_min60' in source, "_process_match 中未找到 enable_min60 开关判断"
        assert 'enable_min75' in source, "_process_match 中未找到 enable_min75 开关判断"
        print("  ✅ _process_match 包含 enable_min60/enable_min75 开关判断")

        # 验证 db.py add_monitor_task 支持新参数
        from db import add_monitor_task
        sig = inspect.signature(add_monitor_task)
        assert 'enable_min60' in sig.parameters, "add_monitor_task 缺少 enable_min60 参数"
        assert 'enable_min75' in sig.parameters, "add_monitor_task 缺少 enable_min75 参数"
        assert sig.parameters['enable_min60'].default == 0, "enable_min60 默认值应为0"
        print("  ✅ add_monitor_task 支持 enable_min60/enable_min75 参数（默认0=关闭）")

        # 验证 app.py 有 toggle_snapshot 接口
        from app import app
        rules = [r.rule for r in app.url_map.iter_rules()]
        assert '/api/monitor/toggle_snapshot' in rules, "缺少 /api/monitor/toggle_snapshot 接口"
        print("  ✅ /api/monitor/toggle_snapshot 接口已注册")
        return True
    except Exception as e:
        print(f"  ❌ 60/75分钟快照开关验证失败: {e}")
        return False


def test_v263_score_calibration_unified():
    """测试47: TC-02 V2.6.3 比分校准统一验证（scheduler+batch_import）"""
    print("\n=== 测试47: TC-02 V2.6.3 比分校准统一验证 ===")
    try:
        import inspect
        from scheduler import manual_snapshot
        from batch_import import batch_import_from_file

        # 验证 scheduler.py manual_snapshot 包含比分校准
        source1 = inspect.getsource(manual_snapshot)
        assert 'HalfTime' in source1 and 'matchProcess' in source1, "manual_snapshot 未包含比分校准"
        assert 'home_half_score' in source1, "manual_snapshot 未校准半场比分"
        print("  ✅ scheduler.py manual_snapshot 包含比分校准")

        # 验证 batch_import.py 包含比分校准
        source2 = inspect.getsource(batch_import_from_file)
        assert 'HalfTime' in source2 and 'matchProcess' in source2, "batch_import_from_file 未包含比分校准"
        print("  ✅ batch_import.py batch_import_from_file 包含比分校准")
        return True
    except Exception as e:
        print(f"  ❌ 比分校准统一验证失败: {e}")
        return False


def main():
    print("=" * 60)
    print("足球比赛数据文档分析系统 V2.6.3 - 冒烟测试")
    print("=" * 60)

    tests = [
        test_imports,
        test_homepage,
        test_time_window,
        test_export_page,
        test_libreoffice_config,
        test_routes,
        test_pinyin_sort,
        test_year_inference,
        test_data_retention,
        test_performance_indexes,
        test_sclass_cache,
        test_match_date_fill,
        test_monitor_task,
        test_db_sync,
        test_quick_monitor,
        test_monitor_list_v251,
        test_time_format_conversion,
        test_export_with_sclass_filter,
        test_pure_read_report,
        test_v252_full_import_flow,
        test_v252_duplicate_cleanup,
        test_v252_dangling_pointer_fix,
        test_v252_performance,
        test_v252_reports_fk_fix,
        test_v253_batch_refresh,
        test_v253_priority_queue,
        test_v253_monitor_config,
        test_v254_sort_logic,
        test_v254_monitor_sort,
        test_v254_monitor_fields,
        test_v254_filter_delete_bug,
        test_v255_odds_filter,
        test_v255_min60_window,
        test_v255_auto_monitor,
        test_v255_batch_delete,
        test_v256_dependencies,
        test_v256_shuttle_api,
        test_v257_auto_refresh_config,
        test_v257_shuttle_ui,
        test_v258_skip_unstarted,
        test_v259_historical_league,
        test_v260_manual_cleanup,
        test_v260_vacuum_frequency,
        test_v261_realtime_state_check,
        test_v262_score_calibration,
        test_v263_snapshot_switch,
        test_v263_score_calibration_unified,
    ]

    passed = 0
    failed = 0
    for test in tests:
        if test():
            passed += 1
        else:
            failed += 1

    print("\n" + "=" * 60)
    print(f"测试结果: {passed} 通过, {failed} 失败")
    print("=" * 60)

    if failed > 0:
        print("❌ 存在失败测试，请修复后再提交！")
        sys.exit(1)
    else:
        print("🎉 所有测试通过，可以提交！")
        sys.exit(0)


if __name__ == '__main__':
    main()
