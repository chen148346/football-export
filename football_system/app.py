"""
足球比赛数据文档分析系统 V2.6.3 - Web 应用

[V2.5.5] 变更说明：
- min60判断条件统一为 57（与 monitor.py 一致）
- api_export_pdf_batch 返回字段名 pdf_count 改为 report_count
- download_report 兼容模式（优先绝对路径，找不到按文件名查找）
- download_export_file 参数名 file 改为 filename（与 download_db_file 统一）
- 首页联赛筛选框改为从已查询的matches列表提取（任务1）

历史变更：
- V2.0: 移除自动刷新（所有刷新必须手动触发）；移除自动报告生成；报告生成前自动刷新比赛状态；新增主客队近期赛况报告API；新增批量ID导入API
"""
import os
import time
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for

from config import STATE_CODES, STATE_SORT_PRIORITY, REPORT_DIR
from db import (
    init_db, get_all_matches, get_match, update_match,
    get_snapshots_by_match, get_snapshot, create_report,
    get_reports, get_report, delete_report,
    get_fulltime_snapshots_with_match_info, get_snapshots_by_match_ids,
    get_finished_matches_in_time_window, get_matches_in_time_window
)
from scraper import fetch_schedule_list, fetch_match_detail
from scheduler import refresh_schedule, manual_snapshot, refresh_match_status, do_refresh_with_auto_monitor, start_auto_refresh_scheduler
from report_generator import generate_report
from team_report_generator import generate_team_recent_reports
from batch_import import batch_import_from_file
from match_time_calc import now_beijing_naive
# V2.4.15: 定时快照监控模块
from monitor import start_monitor_thread, is_monitor_running, run_monitor_once
from db import add_monitor_task, get_active_monitor_tasks, get_all_monitor_tasks, delete_monitor_task
# V2.5: 数据库同步模块
from db_sync import do_export, do_import
from db import get_monitor_task_by_match
# V2.5.1: 监控列表优化+纯读报告生成
from db import get_all_monitor_tasks_v251, get_monitor_sclass_list, get_snapshots_for_report
from db import get_auto_monitor_leagues, add_auto_monitor_league, remove_auto_monitor_league, get_unstarted_matches_by_league
from report_generator import generate_report_from_snapshot

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

# 初始化数据库
init_db()


def _format_match_time(match_time):
    """格式化比赛时间为 hh:mm"""
    if not match_time or len(match_time) < 12:
        return '--:--'
    try:
        dt = datetime.strptime(match_time[:12], '%Y%m%d%H%M%S')
        return dt.strftime('%H:%M')
    except ValueError:
        return '--:--'


def _format_match_date(match_time):
    """格式化比赛日期"""
    if not match_time or len(match_time) < 8:
        return '--'
    try:
        dt = datetime.strptime(match_time[:8], '%Y%m%d')
        return dt.strftime('%m-%d')
    except ValueError:
        return '--'


def _get_state_display(match):
    """获取状态显示文本"""
    state_display = match.get('latest_state_display')
    if state_display:
        return state_display
    return match.get('latest_state_text', '')


def _sort_matches(matches):
    """按规则排序比赛列表"""
    def sort_key(m):
        priority = STATE_SORT_PRIORITY.get(m.get('latest_state_code', 0), 99)
        match_time = m.get('match_time', '')
        return (priority, match_time)
    return sorted(matches, key=sort_key)


@app.route('/')
def index():
    """首页 - 比赛列表（V2.0: 不自动刷新）
    V2.4.4: 使用get_matches_in_time_window应用±10小时时间窗口过滤
    V2.4.9: 确保时间窗口过滤不回退"""
    # V2.4.9: 使用时间窗口过滤，而非get_all_matches全量查询
    now = now_beijing_naive()
    from datetime import timedelta
    start_str = (now - timedelta(hours=10)).strftime('%Y%m%d%H%M%S')
    end_str = (now + timedelta(hours=10)).strftime('%Y%m%d%H%M%S')
    matches = get_matches_in_time_window(start_str, end_str)

    # [V2.5.5] 任务1：首页联赛筛选框改为从已查询的matches列表提取
    # 原逻辑：get_sclass_names_cached() 查询全量数据库联赛（含历史冗余）
    # 新逻辑：从当前±10小时窗口的matches列表中提取联赛名称（set推导），无额外DB查询
    sclass_set = set(m.get('sclass_name', '') for m in matches if m.get('sclass_name'))
    try:
        from xpinyin import Pinyin
        p = Pinyin()
        sclass_list = sorted(sclass_set, key=lambda x: p.get_pinyin(x, ''))
    except ImportError:
        sclass_list = sorted(sclass_set)

    # 筛选
    sclass_filter = request.args.get('sclass', '')
    state_filter = request.args.get('state', '')

    filtered = matches
    if sclass_filter:
        filtered = [m for m in filtered if m.get('sclass_name') == sclass_filter]
    if state_filter:
        if state_filter == 'live':
            filtered = [m for m in filtered if m.get('latest_state_code') in (1, 2, 3, 4)]
        elif state_filter == 'upcoming':
            filtered = [m for m in filtered if m.get('latest_state_code') == 0]
        elif state_filter == 'finished':
            filtered = [m for m in filtered if m.get('latest_state_code') == -1]
        elif state_filter == 'other':
            filtered = [m for m in filtered if m.get('latest_state_code') in (-10, -11, -12, -13, -14)]

    # 排序
    filtered = _sort_matches(filtered)

    # 格式化显示数据
    display_matches = []
    for m in filtered:
        display_matches.append({
            'id': m['id'],
            'sclass_name': m.get('sclass_name', ''),
            'sclass_color': m.get('sclass_color', ''),
            'match_date': _format_match_date(m.get('match_time', '')),
            'match_time': _format_match_time(m.get('match_time', '')),
            'home_team': m.get('home_team', ''),
            'away_team': m.get('away_team', ''),
            'home_rank': m.get('home_rank'),
            'away_rank': m.get('away_rank'),
            'home_score': m.get('latest_home_score'),
            'away_score': m.get('latest_away_score'),
            'home_half_score': m.get('latest_home_half_score'),
            'away_half_score': m.get('latest_away_half_score'),
            'home_red': m.get('latest_home_red', 0),
            'away_red': m.get('latest_away_red', 0),
            'home_yellow': m.get('latest_home_yellow', 0),
            'away_yellow': m.get('latest_away_yellow', 0),
            'state_code': m.get('latest_state_code'),
            'state_text': m.get('latest_state_text', ''),
            'state_display': _get_state_display(m),
            'weather': m.get('weather', ''),
            'round_info': m.get('round_info', ''),
            'has_halftime_report': m.get('halftime_snapshot_id') is not None,
            'has_min60_report': m.get('min60_snapshot_id') is not None,
            'has_fulltime_report': m.get('fulltime_snapshot_id') is not None,
        })

    return render_template('index.html',
                           matches=display_matches,
                           sclass_list=sclass_list,
                           current_sclass=sclass_filter,
                           current_state=state_filter)


@app.route('/match/<int:match_id>')
def match_detail(match_id):
    """比赛详情页"""
    match = get_match(match_id)
    if not match:
        return "比赛不存在", 404

    snapshots = get_snapshots_by_match(match_id)
    reports = get_reports(match_id)

    # 格式化快照
    display_snapshots = []
    for s in snapshots:
        display_snapshots.append({
            'id': s['id'],
            'snapshot_type': s['snapshot_type'],
            'state_text': s.get('state_text', ''),
            'home_score': s.get('home_score'),
            'away_score': s.get('away_score'),
            'elapsed_min': s.get('elapsed_min'),
            'created_at': s.get('created_at', ''),
        })

    # 格式化报告
    display_reports = []
    for r in reports:
        display_reports.append({
            'id': r['id'],
            'report_type': r['report_type'],
            'file_name': r['file_name'],
            'file_path': r['file_path'],
            'created_at': r.get('created_at', ''),
        })

    match_display = {
        'id': match['id'],
        'sclass_name': match.get('sclass_name', ''),
        'match_time': match.get('match_time', ''),
        'home_team': match.get('home_team', ''),
        'away_team': match.get('away_team', ''),
        'home_rank': match.get('home_rank'),
        'away_rank': match.get('away_rank'),
        'weather': match.get('weather', ''),
        'round_info': match.get('round_info', ''),
        'state_text': match.get('latest_state_text', ''),
        'state_display': _get_state_display(match),
        'home_score': match.get('latest_home_score'),
        'away_score': match.get('latest_away_score'),
    }

    return render_template('detail.html',
                           match=match_display,
                           snapshots=display_snapshots,
                           reports=display_reports)


@app.route('/api/refresh', methods=['POST'])
def api_refresh():
    """手动刷新比赛列表
    [V2.5.7] 任务1：改用统一的 do_refresh_with_auto_monitor（含防冲突锁+自动监控触发）
    """
    try:
        result = do_refresh_with_auto_monitor(source='manual')
        if result.get('success'):
            return jsonify({
                'success': True,
                'count': result['count'],
                'repaired': result['repaired'],
                'auto_monitored': result['auto_monitored']
            })
        else:
            return jsonify({'success': False, 'error': result.get('error', '未知错误')}), 500
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/snapshot/<int:match_id>', methods=['POST'])
def api_snapshot(match_id):
    """手动创建快照"""
    try:
        snapshot_id, detail = manual_snapshot(match_id)
        return jsonify({'success': True, 'snapshot_id': snapshot_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/report/<int:match_id>/<int:snapshot_id>', methods=['POST'])
def api_generate_report(match_id, snapshot_id):
    """手动生成报告"""
    try:
        snapshot = get_snapshot(snapshot_id)
        if not snapshot:
            return jsonify({'success': False, 'error': '快照不存在'}), 404

        report_type = snapshot.get('snapshot_type', 'manual')
        report_id, filepath = generate_report(match_id, snapshot_id, report_type)
        return jsonify({'success': True, 'report_id': report_id, 'filepath': filepath})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/quick_report/<int:match_id>', methods=['POST'])
def api_quick_report(match_id):
    """一键生成报告 - V2.0: 先刷新状态，再创建快照和报告"""
    try:
        # 1. 先刷新比赛状态（V2.0新增）
        match = refresh_match_status(match_id)

        # 2. 创建快照
        snapshot_id, detail = manual_snapshot(match_id)

        # 3. 生成报告
        state_code = match.get('latest_state_code', 0)
        elapsed = match.get('latest_elapsed_min', 0)

        if state_code == -1:
            report_type = 'fulltime'
        elif state_code == 2:
            report_type = 'halftime'
        elif state_code == 3 and elapsed >= 57:
            report_type = 'min60'
        else:
            report_type = 'manual'

        report_id, filepath = generate_report(match_id, snapshot_id, report_type)
        return jsonify({
            'success': True,
            'report_id': report_id,
            'snapshot_id': snapshot_id,
            'filepath': filepath,
            'file_name': os.path.basename(filepath),
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/team_report/<int:match_id>', methods=['POST'])
def api_team_report(match_id):
    """V2.0 新增：生成主客队近期赛况报告"""
    try:
        result = generate_team_recent_reports(match_id)
        return jsonify({
            'success': True,
            'home_team': result['home_team'],
            'away_team': result['away_team'],
            'home_report': result['home_report'],
            'away_report': result['away_report'],
            'home_count': result['home_count'],
            'away_count': result['away_count'],
            'home_file_name': os.path.basename(result['home_report']) if result['home_report'] else None,
            'away_file_name': os.path.basename(result['away_report']) if result['away_report'] else None,
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/batch_import', methods=['POST'])
def api_batch_import():
    """V2.0 新增：批量导入比赛ID"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': '未上传文件'}), 400

        file = request.files['file']
        if not file.filename:
            return jsonify({'success': False, 'error': '未选择文件'}), 400

        import tempfile
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.txt', delete=False) as tmp:
            file.save(tmp.name)
            tmp_path = tmp.name

        result = batch_import_from_file(tmp_path)
        os.unlink(tmp_path)

        return jsonify({'success': True, 'result': result})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/download/<int:report_id>')
def download_report(report_id):
    """下载报告
    [V2.5.5] 兼容模式：优先按 file_path 绝对路径查找，找不到则按 file_name 在 download 目录查找
    确保历史报告（Windows路径）和新报告（文件名）均可下载
    """
    report = get_report(report_id)
    if not report:
        return "报告不存在", 404

    filepath = report['file_path']
    # [V2.5.5] 兼容模式：优先绝对路径
    if filepath and os.path.exists(filepath):
        return send_file(filepath, as_attachment=True, download_name=report['file_name'])

    # [V2.5.5] 兼容模式：绝对路径找不到，按 file_name 在 download 目录查找
    file_name = report.get('file_name', '')
    if file_name:
        fallback_path = os.path.join(REPORT_DIR, file_name)
        if os.path.exists(fallback_path):
            return send_file(fallback_path, as_attachment=True, download_name=file_name)

    return "文件不存在", 404


@app.route('/api/report/<int:report_id>', methods=['DELETE'])
def api_delete_report(report_id):
    """删除报告"""
    try:
        report = get_report(report_id)
        if report and os.path.exists(report['file_path']):
            os.remove(report['file_path'])
        delete_report(report_id)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ==================== V2.4.9: Excel批量导出功能 ====================
# ⚠️ V2.4.10代码冻结声明：以下导出路由已进入冻结状态，将交由新开发者重构。
# 任何修改必须经过架构师审批。新模块将独立为ml_data_pipeline。

@app.route('/export')
def export_page():
    """V2.4.9: 数据导出页面
    [V2.5.5] 任务2：联赛列表改用 get_sclass_list()（返回完整字典含sclass_color）
    原逻辑：get_sclass_names_cached() 只返回名称字符串列表，穿梭框无颜色
    新逻辑：get_sclass_list() 返回 [{sclass_id, sclass_name, sclass_color}, ...]，全量数据
    """
    from db import get_sclass_list
    sclass_raw = get_sclass_list()
    try:
        from xpinyin import Pinyin
        p = Pinyin()
        sclass_list = sorted(sclass_raw, key=lambda x: p.get_pinyin(x.get('sclass_name') or '', ''))
    except ImportError:
        sclass_list = sorted(sclass_raw, key=lambda x: x.get('sclass_name', ''))
    return render_template('export.html', sclass_list=sclass_list)


@app.route('/api/export_excel', methods=['POST'])
def api_export_excel():
    """V2.4.9: Excel批量导出接口"""
    try:
        from excel_exporter import export_excel, EXCEL_EXPORT_DIR
        import json as _json
        mode = request.form.get('mode', 'training')
        date_start = request.form.get('date_start', '')
        date_end = request.form.get('date_end', '')
        team_keyword = request.form.get('team_keyword', '')
        match_ids_str = request.form.get('match_ids', '')
        include_dict = request.form.get('include_dictionary') == 'on'

        # V2.4.9: 正确解析前端JSON.stringify的联赛名称
        sclass_names_raw = request.form.get('sclass_names', '')
        sclass_names = []
        if sclass_names_raw:
            try:
                parsed = _json.loads(sclass_names_raw)
                if isinstance(parsed, list):
                    sclass_names = [str(s).strip() for s in parsed if s and str(s).strip()]
            except _json.JSONDecodeError:
                sclass_names = [sclass_names_raw.strip()] if sclass_names_raw.strip() else []

        print(f"[V2.4.9导出] mode={mode}, date_start={date_start}, date_end={date_end}, sclass_names={sclass_names}")

        snapshots_data = []
        if mode == 'training':
            snapshots_data = get_fulltime_snapshots_with_match_info(
                date_start=date_start or None,
                date_end=date_end or None,
                sclass_names=sclass_names if sclass_names else None
            )
            if team_keyword:
                snapshots_data = [s for s in snapshots_data
                                  if team_keyword in (s.get('home_team', '') + s.get('away_team', ''))]
        else:
            if match_ids_str:
                match_ids = [int(x.strip()) for x in match_ids_str.split(',') if x.strip().isdigit()]
            else:
                now = now_beijing_naive()
                from datetime import timedelta
                start_str = (now - timedelta(hours=10)).strftime('%Y%m%d%H%M%S')
                end_str = (now + timedelta(hours=10)).strftime('%Y%m%d%H%M%S')
                matches_in_window = get_finished_matches_in_time_window(start_str, end_str)
                match_ids = [m['id'] for m in matches_in_window]
            snapshots_data = get_snapshots_by_match_ids(match_ids, ['halftime', 'min60', 'fulltime'])

        if not snapshots_data:
            from db import get_conn
            conn = get_conn()
            total_snapshots = conn.execute("SELECT COUNT(*) as c FROM snapshots WHERE snapshot_type='fulltime'").fetchone()['c']
            total_matches = conn.execute("SELECT COUNT(*) as c FROM matches").fetchone()['c']
            conn.close()
            if total_snapshots == 0:
                error_msg = f'数据库中暂无完场快照数据（共{total_matches}场比赛，但未生成过快照）。\n\n请先在首页对完场比赛点击"报告"按钮生成快照，\n或使用"批量导入"功能导入完场比赛ID自动生成快照，\n然后再使用Excel导出功能。'
            else:
                error_msg = f'未找到符合条件的比赛数据。\n\n查询条件：日期{date_start}~{date_end}，联赛：{sclass_names if sclass_names else "全部"}\n数据库中共有{total_snapshots}条完场快照，但无匹配结果。\n\n请检查筛选条件是否过于严格，或尝试放宽日期范围。'
            return jsonify({'success': False, 'error': error_msg}), 404

        filepath = export_excel(snapshots_data, mode=mode, include_dictionary=include_dict,
                                sclass_names=sclass_names, date_start=date_start, date_end=date_end)
        print(f"[V2.4.9导出] Excel导出成功: {filepath}")
        return jsonify({
            'success': True,
            'count': len(snapshots_data),
            'mode': mode,
            'excel_path': filepath,
            'excel_filename': os.path.basename(filepath),
            'dict_path': os.path.join(EXCEL_EXPORT_DIR, 'data_dictionary.xlsx') if include_dict else None,
            'dict_filename': 'data_dictionary.xlsx' if include_dict else None,
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'导出失败：{str(e)}'}), 500


@app.route('/api/export_pdf_batch', methods=['POST'])
def api_export_pdf_batch():
    """V2.4.9: PDF批量导出接口"""
    try:
        import json as _json
        mode = request.form.get('mode', 'training')
        date_start = request.form.get('date_start', '')
        date_end = request.form.get('date_end', '')
        team_keyword = request.form.get('team_keyword', '')
        match_ids_str = request.form.get('match_ids', '')

        sclass_names_raw = request.form.get('sclass_names', '')
        sclass_names = []
        if sclass_names_raw:
            try:
                parsed = _json.loads(sclass_names_raw)
                if isinstance(parsed, list):
                    sclass_names = [str(s).strip() for s in parsed if s and str(s).strip()]
            except _json.JSONDecodeError:
                sclass_names = [sclass_names_raw.strip()] if sclass_names_raw.strip() else []

        if mode == 'prediction' and match_ids_str:
            match_ids = [int(x.strip()) for x in match_ids_str.split(',') if x.strip().isdigit()]
        else:
            snapshots_data = get_fulltime_snapshots_with_match_info(
                date_start=date_start or None,
                date_end=date_end or None,
                sclass_names=sclass_names if sclass_names else None
            )
            if team_keyword:
                snapshots_data = [s for s in snapshots_data
                                  if team_keyword in (s.get('home_team', '') + s.get('away_team', ''))]
            match_ids = list(set(s['match_id'] for s in snapshots_data))

        if not match_ids:
            return jsonify({'success': False, 'error': '未找到符合条件的比赛'}), 404

        success_count = 0
        error_count = 0
        errors = []
        for mid in match_ids:
            try:
                snapshot = get_snapshots_by_match_ids([mid], ['fulltime', 'halftime', 'min60'])
                if not snapshot:
                    error_count += 1
                    errors.append(f'{mid}: 无快照')
                    continue
                snap = snapshot[0]
                report_type = snap.get('snapshot_type', 'fulltime')
                report_id, filepath = generate_report(mid, snap['id'], report_type)
                success_count += 1
            except Exception as e:
                error_count += 1
                errors.append(f'{mid}: {str(e)}')

        return jsonify({
            'success': True,
            'total': len(match_ids),
            'report_count': success_count,
            'error_count': error_count,
            'errors': errors[:10],
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/download_export')
def download_export_file():
    """V2.4.9: 下载导出文件
    [V2.5.5] 参数名统一为 filename（兼容旧参数名 file）
    """
    filename = request.args.get('filename', '') or request.args.get('file', '')
    if not filename:
        return "文件名不能为空", 400
    filename = os.path.basename(filename)
    filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'download', 'excel_export', filename)
    if not os.path.exists(filepath):
        return "文件不存在", 404
    return send_file(filepath, as_attachment=True, download_name=filename)


# ==================== V2.4.15: 定时快照监控路由 ====================

@app.route('/monitor')
def monitor_page():
    """V2.4.15: 定时监控页面 / V2.5.1: 增加联赛筛选 / [V2.5.5] 任务5：增加时间段筛选"""
    # V2.5.1: 使用新查询函数，按比赛时间倒序，支持联赛筛选
    sclass_filter = request.args.get('sclass', '')
    sclass_names = [s for s in sclass_filter.split(',') if s] if sclass_filter else None

    # [V2.5.5] 任务5：时间段筛选（date类型转14位格式）
    date_start_raw = request.args.get('date_start', '')
    date_end_raw = request.args.get('date_end', '')
    date_start = date_start_raw.replace('-', '') + '000000' if date_start_raw else None
    date_end = date_end_raw.replace('-', '') + '235959' if date_end_raw else None

    tasks = get_all_monitor_tasks_v251(sclass_names=sclass_names, limit=200,
                                       date_start=date_start, date_end=date_end)
    sclass_list = get_monitor_sclass_list()
    running = is_monitor_running()
    return render_template('monitor.html', tasks=tasks, monitor_running=running,
                           sclass_list=sclass_list, current_sclass=sclass_filter,
                           current_date_start=date_start_raw, current_date_end=date_end_raw)


@app.route('/api/monitor/add', methods=['POST'])
def api_monitor_add():
    """V2.4.15: 添加监控任务（支持多行/逗号分隔的ID列表）"""
    data = request.get_json()
    raw_ids = data.get('match_ids', '')

    # 解析ID列表（支持换行、逗号、空格分隔）
    import re
    id_strs = re.split(r'[\n,\s]+', raw_ids.strip())
    match_ids = []
    for s in id_strs:
        s = s.strip()
        if s and s.isdigit():
            match_ids.append(int(s))

    if not match_ids:
        return jsonify({'success': False, 'message': '未输入有效的比赛ID'})

    results = []
    success_count = 0
    for mid in match_ids:
        ok, msg = add_monitor_task(mid)
        results.append({'match_id': mid, 'success': ok, 'message': msg})
        if ok:
            success_count += 1

    # 确保监控线程已启动
    if success_count > 0 and not is_monitor_running():
        start_monitor_thread()

    return jsonify({
        'success': True,
        'message': f'成功添加{success_count}场，共{len(match_ids)}场',
        'details': results
    })


@app.route('/api/monitor/list')
def api_monitor_list():
    """V2.4.15: 获取监控任务列表 / V2.5.4: 支持联赛筛选参数 / [V2.5.5] 任务5：支持时间段筛选"""
    # [V2.5.4] 支持联赛筛选参数，修复删除后丢失筛选的Bug
    sclass_filter = request.args.get('sclass', '')
    sclass_names = [s for s in sclass_filter.split(',') if s] if sclass_filter else None

    # [V2.5.5] 任务5：时间段筛选
    date_start_raw = request.args.get('date_start', '')
    date_end_raw = request.args.get('date_end', '')
    date_start = date_start_raw.replace('-', '') + '000000' if date_start_raw else None
    date_end = date_end_raw.replace('-', '') + '235959' if date_end_raw else None

    tasks = get_all_monitor_tasks_v251(sclass_names=sclass_names, limit=200,
                                       date_start=date_start, date_end=date_end)
    running = is_monitor_running()
    return jsonify({
        'success': True,
        'tasks': tasks,
        'monitor_running': running,
        'count': len(tasks)
    })


@app.route('/api/monitor/delete/<int:match_id>', methods=['POST'])
def api_monitor_delete(match_id):
    """V2.4.15: 删除监控任务"""
    delete_monitor_task(match_id)
    return jsonify({'success': True, 'message': f'已删除比赛{match_id}的监控任务'})


@app.route('/api/monitor/batch_delete', methods=['POST'])
def api_monitor_batch_delete():
    """[V2.5.5] 任务4：批量删除监控任务
    请求：JSON {match_ids: [int, ...]}
    返回：{success: bool, message: str, deleted_count: int}
    """
    data = request.get_json()
    match_ids = data.get('match_ids', [])
    if not match_ids:
        return jsonify({'success': False, 'message': '未提供要删除的比赛ID'})

    deleted_count = 0
    for mid in match_ids:
        try:
            delete_monitor_task(int(mid))
            deleted_count += 1
        except Exception:
            pass

    return jsonify({
        'success': True,
        'message': f'批量删除完成，共删除{deleted_count}场监控任务',
        'deleted_count': deleted_count
    })


@app.route('/api/monitor/poll', methods=['POST'])
def api_monitor_poll():
    """V2.4.15: 手动触发一次监控轮询（测试用）"""
    count = run_monitor_once()
    return jsonify({'success': True, 'message': f'手动轮询完成，处理了{count}场比赛', 'count': count})


@app.route('/api/monitor/toggle_snapshot', methods=['POST'])
def api_monitor_toggle_snapshot():
    """[V2.6.3] 切换60/75分钟快照开关
    请求：JSON {match_id: int, node: 'min60'|'min75', enabled: bool}
    """
    data = request.get_json()
    match_id = data.get('match_id')
    node = data.get('node', '')
    enabled = 1 if data.get('enabled') else 0

    if not match_id or node not in ('min60', 'min75'):
        return jsonify({'success': False, 'message': '参数错误'})

    col = f'enable_{node}'
    from db import get_conn
    conn = get_conn()
    conn.execute(f"UPDATE monitor_tasks SET {col} = ?, updated_at = ? WHERE match_id = ? AND ft_status = 0",
                 (enabled, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), match_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': f'已{"开启" if enabled else "关闭"}{node}快照'})


# ==================== [V2.5.5] 任务6：自动监控联赛管理路由 ====================

@app.route('/api/auto_monitor/list')
def api_auto_monitor_list():
    """[V2.5.5] 获取自动监控联赛列表
    [V2.5.6] 任务2：增加 all_leagues 字段返回全量联赛（供穿梭框左侧可选列表）
    """
    leagues = get_auto_monitor_leagues()
    # [V2.5.6] 获取全量联赛列表（按拼音排序）
    from db import get_sclass_list
    all_sclass = get_sclass_list()
    try:
        from xpinyin import Pinyin
        p = Pinyin()
        all_sclass_sorted = sorted(all_sclass, key=lambda x: p.get_pinyin(x.get('sclass_name') or '', ''))
    except ImportError:
        all_sclass_sorted = sorted(all_sclass, key=lambda x: x.get('sclass_name', ''))
    all_league_names = [s['sclass_name'] for s in all_sclass_sorted if s.get('sclass_name')]
    return jsonify({
        'success': True,
        'leagues': leagues,
        'count': len(leagues),
        'all_leagues': all_league_names
    })


@app.route('/api/auto_monitor/add', methods=['POST'])
def api_auto_monitor_add():
    """[V2.5.5] 添加自动监控联赛"""
    data = request.get_json()
    sclass_name = data.get('sclass_name', '').strip()
    if not sclass_name:
        return jsonify({'success': False, 'message': '联赛名称不能为空'})
    add_auto_monitor_league(sclass_name)
    return jsonify({'success': True, 'message': f'已添加"{sclass_name}"到自动监控联赛列表'})


@app.route('/api/auto_monitor/remove', methods=['POST'])
def api_auto_monitor_remove():
    """[V2.5.5] 移除自动监控联赛"""
    data = request.get_json()
    sclass_name = data.get('sclass_name', '').strip()
    if not sclass_name:
        return jsonify({'success': False, 'message': '联赛名称不能为空'})
    remove_auto_monitor_league(sclass_name)
    return jsonify({'success': True, 'message': f'已从自动监控联赛列表移除"{sclass_name}"'})


# ==================== V2.5: 数据库同步路由 ====================

@app.route('/db_sync')
def db_sync_page():
    """V2.5: 数据库同步页面（独立于/export）"""
    return render_template('db_sync.html')


@app.route('/api/get_sclass_list')
def api_get_sclass_list():
    """V2.5.1: 获取联赛列表（按拼音排序，供db_sync页面多选筛选器使用）"""
    from db import get_sclass_list
    sclass_list = get_sclass_list()
    # 按拼音排序
    try:
        from xpinyin import Pinyin
        p = Pinyin()
        sclass_list = sorted(sclass_list, key=lambda x: p.get_pinyin(x.get('sclass_name') or '', ''))
    except ImportError:
        sclass_list = sorted(sclass_list, key=lambda x: x.get('sclass_name', ''))
    return jsonify({'success': True, 'sclass_list': sclass_list})


@app.route('/download_db')
def download_db_file():
    """V2.5.1: 下载导出的数据库文件"""
    filename = request.args.get('filename', '')
    if not filename or not filename.endswith('.db'):
        return "文件不存在", 404
    # 安全检查：防止路径遍历
    if '/' in filename or '\\' in filename or '..' in filename:
        return "非法文件名", 400
    download_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'download')
    filepath = os.path.join(download_dir, filename)
    if not os.path.exists(filepath):
        return "文件不存在", 404
    return send_file(filepath, as_attachment=True, download_name=filename)


@app.route('/api/export_database', methods=['POST'])
def api_export_database():
    """V2.5: 数据库导出API / V2.5.1: 时间精度到分钟+联赛多选"""
    data = request.get_json()
    datetime_start = data.get('datetime_start', '')
    datetime_end = data.get('datetime_end', '')
    sclass_names = data.get('sclass_names', [])

    if not datetime_start or not datetime_end:
        return jsonify({'success': False, 'message': '请选择时间范围'})

    # V2.5.1: 时间格式转换 datetime-local格式(YYYY-MM-DDTHH:MM) → 14位紧凑格式(YYYYMMDDHHMM00)
    # 防御性处理：如果用户只选了日期没选时间，默认补00:00:00
    def _to_14digit(dt_str):
        # 去掉T，替换为空
        dt_str = dt_str.replace('T', ' ')
        parts = dt_str.split(' ')
        date_part = parts[0].replace('-', '')
        time_part = parts[1] if len(parts) > 1 else '00:00'
        # 补全为HHMM00
        time_parts = time_part.split(':')
        hh = time_parts[0] if len(time_parts) > 0 else '00'
        mm = time_parts[1] if len(time_parts) > 1 else '00'
        return f"{date_part}{hh}{mm}00"

    date_start_14 = _to_14digit(datetime_start)
    date_end_14 = _to_14digit(datetime_end)

    # V2.5.1: 联赛多选，空列表表示全部
    sclass_list = [s for s in sclass_names if s] if sclass_names else None

    result = do_export(date_start_14, date_end_14, sclass_list)
    if result['success']:
        return jsonify(result)
    else:
        return jsonify(result), 400


@app.route('/api/import_database', methods=['POST'])
def api_import_database():
    """V2.5: 数据库导入API"""
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': '请选择.db文件'})

    file = request.files['file']
    if not file.filename or not file.filename.endswith('.db'):
        return jsonify({'success': False, 'message': '仅支持.db文件'})

    # 保存上传文件到临时路径
    import tempfile
    tmp_path = os.path.join(tempfile.gettempdir(), f'import_{int(time.time())}.db')
    file.save(tmp_path)

    result = do_import(tmp_path)

    # 清理临时文件
    try:
        os.remove(tmp_path)
    except OSError:
        pass

    if result['success']:
        return jsonify(result)
    else:
        return jsonify(result), 400


@app.route('/api/add_monitor_task', methods=['POST'])
def api_add_monitor_task():
    """V2.5: 快捷加入监控API"""
    data = request.get_json()
    match_id = data.get('match_id')
    if not match_id:
        return jsonify({'success': False, 'message': '缺少match_id'})

    ok, msg = add_monitor_task(match_id)
    return jsonify({'success': ok, 'message': msg})


@app.route('/api/check_monitor_status/<int:match_id>')
def api_check_monitor_status(match_id):
    """V2.5: 检查比赛是否已在监控列表（前端按钮状态用）"""
    task = get_monitor_task_by_match(match_id)
    if task and task.get('ft_status') == 0:
        return jsonify({'success': True, 'is_monitoring': True})
    return jsonify({'success': True, 'is_monitoring': False})


# ==================== V2.5.1: 监控列表生成报告API ====================

@app.route('/api/monitor/generate_reports/<int:match_id>', methods=['POST'])
def api_monitor_generate_reports(match_id):
    """
    V2.5.1: 监控列表"生成报告"快捷操作
    纯读操作：仅读取已有快照生成Word报告，不刷新状态、不创建新快照、不写数据库

    异常隔离：遍历生成时单份报错不中断，继续下一份，最后汇总返回
    """
    # 1. 获取该比赛的所有快照
    snapshots = get_snapshots_for_report(match_id)
    if not snapshots:
        return jsonify({'success': False, 'message': f'比赛{match_id}暂无快照，无法生成报告'})

    # 2. 遍历快照，纯读生成报告（异常隔离）
    success_files = []
    errors = []
    for snap in snapshots:
        try:
            filepath = generate_report_from_snapshot(match_id, snap['id'])
            success_files.append(os.path.basename(filepath))
        except Exception as e:
            errors.append(f"快照{snap['id']}({snap.get('snapshot_type', 'unknown')}): {str(e)}")

    # 3. 汇总返回
    if success_files:
        msg = f"成功生成{len(success_files)}份报告"
        if errors:
            msg += f"，{len(errors)}份失败"
        return jsonify({
            'success': True,
            'message': msg,
            'files': success_files,
            'errors': errors,
            'count': len(success_files)
        })
    else:
        return jsonify({
            'success': False,
            'message': f'全部{len(errors)}份报告生成失败',
            'errors': errors
        }), 500


if __name__ == '__main__':
    # V2.0: 不再启动调度器
    # V2.4.15: 启动定时监控线程
    start_monitor_thread()
    # [V2.5.7] 任务1：启动定时自动刷新调度器（每天04:00和16:00北京时间）
    start_auto_refresh_scheduler()
    from waitress import serve
    print("服务器启动: http://0.0.0.0:5000")
    print("V2.0: 自动报告已禁用，所有报告需手动触发")
    print("V2.4.15: 定时快照监控线程已启动")
    print("[V2.5.7] 定时自动刷新调度器已启动（每天04:00和16:00北京时间）")
    serve(app, host='0.0.0.0', port=5000, threads=8)
