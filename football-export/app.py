#!/usr/bin/env python3
"""
app.py - Flask Web应用 (V1.5 重构与优化)
================================
足球比赛数据报表导出模块 - Web界面后端

版本：V1.5
日期：2026-07-14

V1.5重构与优化变更说明：
- 任务1：文件命名规范升级（时间戳_联赛_日期_类型_字段选择.xlsx）
- 任务2：比分字段分离（current_home/away_score + label_home/away_score）
- 任务3：百分比字段小数化修复（扩展至8项kind）
- 任务4：数据字典枚举值规范化
"""

import os
import sys
import json
import time
import threading
import traceback
from datetime import datetime, timedelta

from flask import (
    Flask, render_template, request, jsonify, send_from_directory,
    redirect, url_for, abort
)

# ============================================================================
# 路径设置（基于__file__，跨平台兼容）
# ============================================================================
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_DIR = os.path.dirname(_MODULE_DIR)
_PROJECT_ROOT = os.path.dirname(_SCRIPTS_DIR)

sys.path.insert(0, _SCRIPTS_DIR)

# 导入V1.0核心模块
from football_export import (
    export_matches, query_matches, get_sclass_list, get_date_range,
    get_db_info, get_match_count_by_state, config
)

# ============================================================================
# 北京时间工具函数
# ============================================================================

def _beijing_now():
    """返回当前北京时间（UTC+8）"""
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    utc_now = _dt.now(_tz.utc)
    return utc_now + _td(hours=config.BEIJING_TZ_OFFSET_HOURS)


# ============================================================================
# Flask应用初始化
# ============================================================================

app = Flask(
    __name__,
    template_folder=os.path.join(_MODULE_DIR, "templates"),
    static_folder=os.path.join(_MODULE_DIR, "static"),
)
app.config['JSON_AS_ASCII'] = False  # 支持中文JSON响应
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

# 导出任务状态（内存存储，适合单进程）
_export_tasks = {}
_task_lock = threading.Lock()


# ============================================================================
# 页面路由
# ============================================================================

@app.route('/')
def index():
    """导出页面"""
    return render_template('export.html', version='V1.1')


# ============================================================================
# API路由
# ============================================================================

@app.route('/api/sclass_list')
def api_sclass_list():
    """获取联赛列表（用于前端多选框）"""
    try:
        db_path = request.args.get('db_path') or config.DEFAULT_DB_PATH
        leagues = get_sclass_list(db_path)
        return jsonify({
            'success': True,
            'data': leagues,
            'count': len(leagues)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/date_range')
def api_date_range():
    """获取日期范围（用于前端默认值）"""
    try:
        db_path = request.args.get('db_path') or config.DEFAULT_DB_PATH
        dr = get_date_range(db_path)
        
        # 计算默认日期范围（最近一个月）
        today = _beijing_now()
        default_end = today.strftime('%Y-%m-%d')
        default_start = (today - timedelta(days=30)).strftime('%Y-%m-%d')
        
        return jsonify({
            'success': True,
            'data': {
                'min_date': dr['min_date'],
                'max_date': dr['max_date'],
                'default_start': default_start,
                'default_end': default_end,
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/db_info')
def api_db_info():
    """获取数据库统计信息（用于前端显示）"""
    try:
        db_path = request.args.get('db_path') or config.DEFAULT_DB_PATH
        info = get_db_info(db_path)
        states = get_match_count_by_state(db_path)
        
        # 提取关键统计
        table_counts = {k: v['row_count'] for k, v in info.get('tables', {}).items()}
        finished_count = states.get('-1', {}).get('count', 0)
        
        return jsonify({
            'success': True,
            'data': {
                'tables': table_counts,
                'finished_matches': finished_count,
                'state_stats': states,
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/export_excel', methods=['POST'])
def api_export_excel():
    """
    导出Excel文件接口 (V1.5)
    
    请求参数（JSON）：
        date_start: str       开始日期 YYYY-MM-DD（可选）
        date_end: str         结束日期 YYYY-MM-DD（可选）
        sclass_names: list    联赛名称列表（可选）
        team_keyword: str     球队名称模糊搜索（可选）
        limit: int            数量限制（可选）
        sheets: list          V1.2新增 - 要导出的Sheet标识列表（可选，默认全选）
        max_per_file: int     V1.2新增 - 单文件最大比赛数（可选，默认50）
        save_path: str        V1.2新增 - 自定义保存路径（可选）
        match_mode: str       V1.5新增 - 比赛模式（可选，默认'fulltime'）
                              'fulltime'=完场导出（V1.4行为）
                              'halftime'=半场快照导出
                              'custom'=自定义分钟区间
        min_minute: int       V1.5新增 - 自定义区间下限（match_mode='custom'时有效）
        max_minute: int       V1.5新增 - 自定义区间上限（match_mode='custom'时有效）
        include_fulltime: bool V1.5新增 - 是否同时导出完场快照（用于训练标签）
    
    返回：
        success: bool
        task_id: str          任务ID（用于查询进度）
        message: str          提示信息
    """
    try:
        data = request.get_json(force=True, silent=True) or {}
        
        # 解析参数
        date_start = data.get('date_start') or None
        date_end = data.get('date_end') or None
        sclass_names = data.get('sclass_names') or None
        team_keyword = data.get('team_keyword') or None
        limit = data.get('limit')
        
        # V1.6新增: 时间精度筛选（datetime-local 格式: "2026-07-26T09:00"）
        start_datetime = data.get('start_datetime') or None
        end_datetime = data.get('end_datetime') or None
        
        # V1.6新增: 按球队拆分导出
        split_by_team = bool(data.get('split_by_team', False))
        
        # V1.7新增: 每队比赛数量上限
        max_matches_per_team = data.get('max_matches_per_team')
        if max_matches_per_team is not None:
            try:
                max_matches_per_team = int(max_matches_per_team)
                if max_matches_per_team <= 0:
                    max_matches_per_team = None
            except (ValueError, TypeError):
                max_matches_per_team = None
        if limit:
            try:
                limit = int(limit)
            except (ValueError, TypeError):
                limit = None
        
        # V1.2新增: Sheet选择
        sheets_to_export = data.get('sheets') or None
        if sheets_to_export is not None and not isinstance(sheets_to_export, list):
            sheets_to_export = None
        
        # V1.2新增: 单文件最大比赛数
        max_per_file = data.get('max_per_file')
        if max_per_file:
            try:
                max_per_file = int(max_per_file)
                if max_per_file < 1:
                    max_per_file = None
            except (ValueError, TypeError):
                max_per_file = None
        if max_per_file is None:
            max_per_file = config.DEFAULT_MAX_MATCHES_PER_FILE
        
        # V1.2新增: 自定义保存路径
        save_path = data.get('save_path') or None
        # 安全校验：禁止路径遍历
        if save_path:
            save_path = os.path.abspath(save_path)
            # 跨平台禁止目录列表（Linux + Windows）
            forbidden = [
                # Linux 系统目录
                '/etc', '/var', '/usr', '/bin', '/sbin', '/root', '/proc', '/sys',
                # Windows 系统目录（os.path.normcase 统一处理大小写和分隔符）
            ]
            # Windows 系统目录（仅在 Windows 上生效）
            if os.name == 'nt':
                windir = os.environ.get('WINDIR', r'C:\Windows')
                program_files = os.environ.get('ProgramFiles', r'C:\Program Files')
                program_files_x86 = os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')
                system_drive = os.environ.get('SystemDrive', 'C:')
                forbidden.extend([
                    windir,
                    program_files,
                    program_files_x86,
                    os.path.join(system_drive + os.sep, 'Windows'),
                    os.path.join(system_drive + os.sep, 'Program Files'),
                ])
            # 统一规范化后比较
            norm_save = os.path.normcase(os.path.normpath(save_path))
            for fb in forbidden:
                norm_fb = os.path.normcase(os.path.normpath(fb))
                if norm_save.startswith(norm_fb):
                    return jsonify({
                        'success': False,
                        'error': f'禁止保存到系统目录: {fb}'
                    }), 400
            # 自动创建目录
            try:
                os.makedirs(save_path, exist_ok=True)
            except Exception as e:
                return jsonify({
                    'success': False,
                    'error': f'无法创建保存目录: {save_path} ({str(e)})'
                }), 400
        
        output_dir = save_path if save_path else config.OUTPUT_DIR
        
        # 参数校验
        if date_start and date_end and date_start > date_end:
            return jsonify({
                'success': False,
                'error': '开始日期不能晚于结束日期'
            }), 400
        
        # V1.5新增: 解析比赛模式
        match_mode = data.get('match_mode', 'fulltime')
        include_fulltime = bool(data.get('include_fulltime', False))
        min_minute = data.get('min_minute')
        max_minute = data.get('max_minute')
        
        # V1.5: 自定义分钟区间校验
        if match_mode == 'custom':
            try:
                min_minute = int(min_minute) if min_minute is not None else 0
                max_minute = int(max_minute) if max_minute is not None else 90
            except (ValueError, TypeError):
                return jsonify({
                    'success': False,
                    'error': '分钟区间必须为整数'
                }), 400
            if min_minute < 0 or max_minute > 120:
                return jsonify({
                    'success': False,
                    'error': '分钟区间必须在0-120范围内'
                }), 400
            if min_minute >= max_minute:
                return jsonify({
                    'success': False,
                    'error': '开始分钟必须小于结束分钟'
                }), 400
        
        # 生成任务ID
        task_id = f"export_{int(time.time() * 1000)}"
        
        # V1.5: 使用新文件名生成函数
        from football_export.excel_exporter import generate_filename_v15
        filename = generate_filename_v15(
            sclass_names=sclass_names,
            start_date=date_start,
            end_date=date_end,
            sheets_to_export=sheets_to_export,
            snapshot_type="fulltime",
        )
        output_path = os.path.join(output_dir, filename)
        
        # 初始化任务状态
        with _task_lock:
            _export_tasks[task_id] = {
                'status': 'running',
                'progress': 0,
                'message': '正在查询比赛数据...',
                'output_path': output_path,
                'output_dir': output_dir,
                'filename': filename,
                'start_time': time.time(),
                'error': None,
                'files': [],  # V1.2: 分片导出可能有多个文件
                'match_mode': match_mode,  # V1.5: 记录模式
            }
        
        # 启动后台导出线程
        # V1.6: 根据split_by_team选择按球队拆分导出
        if split_by_team:
            # V1.6: 按球队拆分导出
            thread = threading.Thread(
                target=_run_team_export_task,
                args=(task_id, date_start, date_end, start_datetime, end_datetime,
                      sclass_names, team_keyword, limit,
                      sheets_to_export, output_dir, max_matches_per_team),
                daemon=True
            )
        elif match_mode in ('halftime', 'custom'):
            # V1.5: 非完场快照导出
            thread = threading.Thread(
                target=_run_non_fulltime_export_task,
                args=(task_id, date_start, date_end, start_datetime, end_datetime,
                      sclass_names, team_keyword, limit,
                      match_mode, min_minute, max_minute, include_fulltime,
                      sheets_to_export, output_dir, sclass_names),
                daemon=True
            )
        else:
            # V1.4: 完场导出（保持原有行为）
            thread = threading.Thread(
                target=_run_export_task,
                args=(task_id, date_start, date_end, start_datetime, end_datetime,
                      sclass_names, team_keyword, limit,
                      output_path, sheets_to_export, max_per_file, output_dir),
                daemon=True
            )
        thread.start()
        
        return jsonify({
            'success': True,
            'task_id': task_id,
            'message': '导出任务已启动',
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'服务器错误: {str(e)}'
        }), 500


@app.route('/api/export_status/<task_id>')
def api_export_status(task_id):
    """查询导出任务状态 (V1.2: 支持分片多文件)"""
    with _task_lock:
        task = _export_tasks.get(task_id)
    
    if not task:
        return jsonify({
            'success': False,
            'error': '任务不存在'
        }), 404
    
    # 计算耗时
    elapsed = time.time() - task['start_time']
    
    result = {
        'success': True,
        'status': task['status'],
        'progress': task['progress'],
        'message': task['message'],
        'elapsed': round(elapsed, 2),
    }
    
    if task['status'] == 'completed':
        # V1.2: 支持分片多文件下载
        files = task.get('files', [])
        if files:
            # 分片导出：返回多个文件
            result['files'] = files
            result['file_count'] = len(files)
            result['download_urls'] = [f['download_url'] for f in files]
        else:
            # 单文件导出
            result['filename'] = task['filename']
            result['download_url'] = f"/download/{task['filename']}"
            if os.path.exists(task['output_path']):
                size_kb = os.path.getsize(task['output_path']) / 1024
                result['file_size_kb'] = round(size_kb, 1)
    elif task['status'] == 'failed':
        result['error'] = task['error']
    
    return jsonify(result)


@app.route('/download/<path:filename>')
def download_file(filename):
    """下载导出的Excel文件 (V1.2: 支持自定义保存路径)"""
    # 安全检查：防止路径遍历
    if '..' in filename:
        abort(404)
    
    # V1.2: 文件可能在自定义路径或默认路径
    # 先检查默认输出目录
    file_path = os.path.join(config.OUTPUT_DIR, filename)
    if os.path.exists(file_path):
        return send_from_directory(
            config.OUTPUT_DIR,
            filename,
            as_attachment=True,
            download_name=os.path.basename(filename)
        )
    
    # 再检查download目录下的子目录
    full_path = os.path.join(config.OUTPUT_DIR, filename)
    if os.path.exists(full_path):
        directory = os.path.dirname(full_path)
        basename = os.path.basename(full_path)
        return send_from_directory(
            directory,
            basename,
            as_attachment=True,
            download_name=basename
        )
    
    abort(404)


# ============================================================================
# 后台导出任务
# ============================================================================

def _run_export_task(task_id, date_start, date_end, start_datetime, end_datetime,
                     sclass_names, team_keyword, limit,
                     output_path, sheets_to_export, max_per_file, output_dir):
    """
    后台执行导出任务 (V1.6)
    
    V1.6新增：
    - start_datetime/end_datetime: 时间精度筛选
    """
    try:
        with _task_lock:
            _export_tasks[task_id]['progress'] = 10
            _export_tasks[task_id]['message'] = '正在查询比赛数据...'
        
        # 调用V1.0核心逻辑查询比赛（V1.6: 传入datetime参数）
        matches = query_matches(
            db_path=config.DEFAULT_DB_PATH,
            start_date=date_start,
            end_date=date_end,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            sclass_names=sclass_names,
            team_name=team_keyword,
            limit=limit,
        )
        
        with _task_lock:
            _export_tasks[task_id]['progress'] = 30
            _export_tasks[task_id]['message'] = f'找到 {len(matches)} 场比赛，正在生成Excel...'
        
        if not matches:
            with _task_lock:
                _export_tasks[task_id]['status'] = 'failed'
                _export_tasks[task_id]['error'] = '没有找到符合条件的完场比赛数据'
                _export_tasks[task_id]['message'] = '未找到数据'
            return
        
        # V1.5: 判断是否需要分片导出
        from football_export.excel_exporter import export_to_excel, generate_filename_v15
        
        total_matches = len(matches)
        if total_matches <= max_per_file:
            # 不分片：单文件导出
            output_file = export_to_excel(
                matches=matches,
                output_path=output_path,
                sclass_names=sclass_names,
                start_date=date_start,
                end_date=date_end,
                sheets_to_export=sheets_to_export,
            )
            
            # V1.3修复: 处理跨盘符下载路径
            download_filename = os.path.basename(output_file)
            try:
                rel_path = os.path.relpath(output_file, config.OUTPUT_DIR)
                if rel_path.startswith('..'):
                    raise ValueError("跨盘符路径")
            except ValueError:
                # V1.3: 跨盘符时复制文件到默认输出目录
                import shutil
                dest_path = os.path.join(config.OUTPUT_DIR, download_filename)
                if os.path.exists(dest_path):
                    dest_path = os.path.join(config.OUTPUT_DIR, f"cross_{download_filename}")
                    download_filename = f"cross_{download_filename}"
                shutil.copy2(output_file, dest_path)
            
            with _task_lock:
                _export_tasks[task_id]['progress'] = 100
                _export_tasks[task_id]['status'] = 'completed'
                _export_tasks[task_id]['message'] = f'导出完成：{total_matches}场比赛'
                _export_tasks[task_id]['output_path'] = output_file
                _export_tasks[task_id]['filename'] = download_filename
        else:
            # V1.2: 分片导出
            import math
            num_parts = math.ceil(total_matches / max_per_file)
            files_info = []
            
            for i in range(num_parts):
                start_idx = i * max_per_file
                end_idx = min((i + 1) * max_per_file, total_matches)
                part_matches = matches[start_idx:end_idx]
                
                # V1.5: 生成分片文件名
                part_filename = generate_filename_v15(
                    sclass_names=sclass_names,
                    start_date=date_start,
                    end_date=date_end,
                    sheets_to_export=sheets_to_export,
                    snapshot_type="fulltime",
                    part_index=i + 1,
                )
                part_output_path = os.path.join(output_dir, part_filename)
                
                # 更新进度
                progress = 30 + int((i / num_parts) * 60)
                with _task_lock:
                    _export_tasks[task_id]['progress'] = progress
                    _export_tasks[task_id]['message'] = f'正在生成分片 {i+1}/{num_parts}（第{start_idx+1}-{end_idx}场）...'
                
                # 导出分片
                export_to_excel(
                    matches=part_matches,
                    output_path=part_output_path,
                    sclass_names=sclass_names,
                    start_date=date_start,
                    end_date=date_end,
                    sheets_to_export=sheets_to_export,
                )
                
                # V1.3修复: 计算相对路径用于下载（处理跨盘符场景）
                # 问题根因：os.path.relpath()在跨盘符（跨挂载点）时会抛出ValueError
                #   Windows: C盘和D盘是不同挂载点，relpath无法计算
                #   错误信息: ValueError: path is on mount 'D:', start on mount 'C:'
                # 解决方案A：try-except捕获ValueError，跨盘符时复制文件到默认目录
                download_filename = part_filename
                try:
                    rel_path = os.path.relpath(part_output_path, config.OUTPUT_DIR)
                    # 检查是否跨盘符（relpath结果以..开头说明不在默认目录下）
                    if rel_path.startswith('..'):
                        raise ValueError("跨盘符路径")
                    download_url = f"/download/{rel_path}"
                except ValueError:
                    # V1.3: 跨盘符时复制文件到默认输出目录
                    import shutil
                    dest_path = os.path.join(config.OUTPUT_DIR, part_filename)
                    # 避免文件名冲突：跨盘符文件加前缀
                    if os.path.exists(dest_path):
                        dest_path = os.path.join(config.OUTPUT_DIR, f"cross_{part_filename}")
                        download_filename = f"cross_{part_filename}"
                    shutil.copy2(part_output_path, dest_path)
                    download_url = f"/download/{download_filename}"
                
                files_info.append({
                    'filename': part_filename,
                    'download_url': download_url,
                    'file_size_kb': round(os.path.getsize(part_output_path) / 1024, 1),
                    'match_count': len(part_matches),
                    'part_index': i + 1,
                })
            
            with _task_lock:
                _export_tasks[task_id]['progress'] = 100
                _export_tasks[task_id]['status'] = 'completed'
                _export_tasks[task_id]['message'] = f'导出完成：{total_matches}场比赛，分{num_parts}个文件'
                _export_tasks[task_id]['files'] = files_info
    
    except Exception as e:
        traceback.print_exc()
        with _task_lock:
            _export_tasks[task_id]['status'] = 'failed'
            _export_tasks[task_id]['error'] = str(e)
            _export_tasks[task_id]['message'] = f'导出失败: {str(e)}'


def _run_team_export_task(task_id, date_start, date_end, start_datetime, end_datetime,
                          sclass_names, team_keyword, limit,
                          sheets_to_export, output_dir, max_matches_per_team=None):
    """
    V1.6: 按球队拆分导出任务
    V1.7: 新增子目录保存 + 每队比赛数量上限
    
    查询所有符合条件的比赛，按球队维度拆分为多个Excel文件。
    每个球队生成一个独立文件，包含该球队参与的所有比赛（主队+客队）。
    
    V1.7变更：
    1. 文件保存到子目录：{联赛名称}_{yymmdd}_{yymmdd}/
       单选联赛用联赛名，多选/全选用 'multi'
       日期为空时用 '000000'
    2. 每队比赛数量上限：按 match_time 降序取最近 N 场
    """
    try:
        with _task_lock:
            _export_tasks[task_id]['progress'] = 10
            _export_tasks[task_id]['message'] = '正在查询比赛数据...'
        
        # 查询所有符合条件的比赛（V1.6: 传入datetime参数）
        matches = query_matches(
            db_path=config.DEFAULT_DB_PATH,
            start_date=date_start,
            end_date=date_end,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            sclass_names=sclass_names,
            team_name=team_keyword,
            limit=limit,
        )
        
        with _task_lock:
            _export_tasks[task_id]['progress'] = 20
            _export_tasks[task_id]['message'] = f'找到 {len(matches)} 场比赛，正在按球队拆分...'
        
        if not matches:
            with _task_lock:
                _export_tasks[task_id]['status'] = 'failed'
                _export_tasks[task_id]['error'] = '没有找到符合条件的完场比赛数据'
                _export_tasks[task_id]['message'] = '未找到数据'
            return
        
        # ========== V1.7: 计算子目录名 ==========
        # 联赛名称：单选用联赛名，多选/全选用 'multi'
        if sclass_names and len(sclass_names) == 1:
            dir_league_name = sclass_names[0]
        else:
            dir_league_name = 'multi'
        # 替换非法字符
        for char, replacement in config.ILLEGAL_CHAR_REPLACE.items():
            dir_league_name = dir_league_name.replace(char, replacement)
        
        # 日期格式：yymmdd（6位），空值用 '000000'
        def _to_yymmdd(d):
            if not d:
                return '000000'
            # 处理 YYYY-MM-DD 或 datetime-local 格式
            d_clean = d.split('T')[0] if 'T' in d else d
            parts = d_clean.split('-')
            if len(parts) == 3:
                return parts[0][2:] + parts[1] + parts[2]  # '2026' → '26'
            return '000000'
        
        subdir_name = f"{dir_league_name}_{_to_yymmdd(date_start)}_{_to_yymmdd(date_end)}"
        team_output_dir = os.path.join(output_dir, subdir_name)
        os.makedirs(team_output_dir, exist_ok=True)
        
        # 提取所有唯一球队名称（主队+客队）
        all_teams = set()
        for m in matches:
            if m.home_team:
                all_teams.add(m.home_team)
            if m.away_team:
                all_teams.add(m.away_team)
        
        all_teams = sorted(all_teams)
        total_teams = len(all_teams)
        
        with _task_lock:
            _export_tasks[task_id]['progress'] = 30
            _export_tasks[task_id]['message'] = f'共 {total_teams} 支球队，正在生成Excel...'
        
        # 生成日期后缀（yyyymmdd 格式）
        date_suffix = _beijing_now().strftime('%Y%m%d')
        
        from football_export.excel_exporter import export_to_excel
        
        files_info = []
        for idx, team_name in enumerate(all_teams):
            # 筛选该球队参与的比赛（主队或客队）
            team_matches = [
                m for m in matches
                if m.home_team == team_name or m.away_team == team_name
            ]
            
            if not team_matches:
                continue
            
            # V1.7: 按 match_time 降序排列，取最近 N 场
            if max_matches_per_team and max_matches_per_team > 0:
                team_matches.sort(key=lambda m: m.match_time or '', reverse=True)
                team_matches = team_matches[:max_matches_per_team]
            
            # 生成文件名：{球队名称}_{yyyymmdd}.xlsx
            # 使用 config.ILLEGAL_CHAR_REPLACE 替换非法字符
            safe_team_name = team_name
            for char, replacement in config.ILLEGAL_CHAR_REPLACE.items():
                safe_team_name = safe_team_name.replace(char, replacement)
            
            team_filename = f"{safe_team_name}_{date_suffix}.xlsx"
            team_output_path = os.path.join(team_output_dir, team_filename)
            
            # 更新进度
            progress = 30 + int((idx / total_teams) * 60)
            with _task_lock:
                _export_tasks[task_id]['progress'] = progress
                _export_tasks[task_id]['message'] = f'正在生成 {team_name} ({idx+1}/{total_teams})...'
            
            # 调用核心导出逻辑（不修改原有函数）
            export_to_excel(
                matches=team_matches,
                output_path=team_output_path,
                sclass_names=sclass_names,
                start_date=date_start,
                end_date=date_end,
                sheets_to_export=sheets_to_export,
            )
            
            # 计算下载路径（文件在子目录中）
            # 使用子目录下的相对路径
            download_rel = os.path.join(subdir_name, team_filename)
            download_filename = team_filename
            try:
                rel_path = os.path.relpath(team_output_path, config.OUTPUT_DIR)
                if rel_path.startswith('..'):
                    raise ValueError("跨盘符路径")
                download_url = f"/download/{rel_path}"
            except ValueError:
                import shutil
                dest_path = os.path.join(config.OUTPUT_DIR, team_filename)
                if os.path.exists(dest_path):
                    dest_path = os.path.join(config.OUTPUT_DIR, f"cross_{team_filename}")
                    download_filename = f"cross_{team_filename}"
                shutil.copy2(team_output_path, dest_path)
                download_url = f"/download/{download_filename}"
            
            files_info.append({
                'filename': team_filename,
                'download_url': download_url,
                'file_size_kb': round(os.path.getsize(team_output_path) / 1024, 1),
                'match_count': len(team_matches),
                'team_name': team_name,
            })
        
        with _task_lock:
            _export_tasks[task_id]['progress'] = 100
            _export_tasks[task_id]['status'] = 'completed'
            _export_tasks[task_id]['message'] = f'导出完成：{total_teams} 支球队，共 {len(files_info)} 个文件'
            _export_tasks[task_id]['files'] = files_info
    
    except Exception as e:
        traceback.print_exc()
        with _task_lock:
            _export_tasks[task_id]['status'] = 'failed'
            _export_tasks[task_id]['error'] = str(e)
            _export_tasks[task_id]['message'] = f'导出失败: {str(e)}'


# ============================================================================
# V1.5 新增 - 非完场快照导出任务
# ============================================================================

def _run_non_fulltime_export_task(task_id, date_start, date_end, start_datetime, end_datetime,
                                   sclass_names, team_keyword, limit,
                                   match_mode, min_minute, max_minute, include_fulltime,
                                   sheets_to_export, output_dir, sclass_names_for_filename):
    """
    V1.5新增 - 后台执行非完场快照导出任务。
    
    生成两个Excel文件：
    1. prediction文件：非完场快照数据（特征）
    2. label文件：完场快照数据（标签，仅include_fulltime=True时生成）
    
    文件命名：
    - {yymmdd}_{赛事}_{日期}_prediction.xlsx
    - {yymmdd}_{赛事}_{日期}_label.xlsx
    """
    try:
        from football_export.db_reader import query_non_fulltime_snapshots
        from football_export.excel_exporter import export_to_excel, generate_filename_v15
        
        with _task_lock:
            _export_tasks[task_id]['progress'] = 10
            _export_tasks[task_id]['message'] = '正在查询非完场快照数据...'
        
        # 构建快照筛选条件
        if match_mode == 'halftime':
            snapshot_filter = {'mode': 'halftime'}
            snap_type = 'halftime'
        else:
            snapshot_filter = {'mode': 'custom', 'min': min_minute, 'max': max_minute}
            snap_type = 'custom'
        
        # 查询非完场快照
        result = query_non_fulltime_snapshots(
            db_path=config.DEFAULT_DB_PATH,
            snapshot_filter=snapshot_filter,
            include_fulltime=include_fulltime,
            start_date=date_start,
            end_date=date_end,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            sclass_names=sclass_names,
            team_name=team_keyword,
            limit=limit,
        )
        
        prediction_snapshots = result['prediction_snapshots']
        label_snapshots = result['label_snapshots']
        
        with _task_lock:
            _export_tasks[task_id]['progress'] = 30
            _export_tasks[task_id]['message'] = f'找到 {len(prediction_snapshots)} 个非完场快照，正在生成Excel...'
        
        if not prediction_snapshots:
            with _task_lock:
                _export_tasks[task_id]['status'] = 'failed'
                _export_tasks[task_id]['error'] = '没有找到符合条件的非完场快照数据'
                _export_tasks[task_id]['message'] = '未找到数据'
            return
        
        files_info = []
        
        # V1.5: 生成prediction文件（使用新命名规则）
        pred_filename = generate_filename_v15(
            sclass_names=sclass_names_for_filename,
            start_date=date_start,
            end_date=date_end,
            sheets_to_export=sheets_to_export,
            snapshot_type=snap_type,
            file_role="prediction",
        )
        pred_output_path = os.path.join(output_dir, pred_filename)
        
        with _task_lock:
            _export_tasks[task_id]['progress'] = 50
            _export_tasks[task_id]['message'] = '正在生成prediction文件...'
        
        export_to_excel(
            matches=prediction_snapshots,
            output_path=pred_output_path,
            sclass_names=sclass_names,
            start_date=date_start,
            end_date=date_end,
            sheets_to_export=sheets_to_export,
        )
        
        # 处理跨盘符下载路径
        pred_download_filename = _handle_cross_drive_path(pred_output_path, pred_filename)
        files_info.append({
            'filename': pred_filename,
            'download_url': f"/download/{pred_download_filename}",
            'file_size_kb': round(os.path.getsize(pred_output_path) / 1024, 1),
            'match_count': len(prediction_snapshots),
            'file_type': 'prediction',
        })
        
        # V1.5: 生成label文件（使用新命名规则，类型为FT完场）
        if include_fulltime and label_snapshots:
            with _task_lock:
                _export_tasks[task_id]['progress'] = 70
                _export_tasks[task_id]['message'] = '正在生成label文件...'
            
            label_filename = generate_filename_v15(
                sclass_names=sclass_names_for_filename,
                start_date=date_start,
                end_date=date_end,
                sheets_to_export=sheets_to_export,
                snapshot_type="fulltime",  # label文件是完场快照
                file_role="label",
            )
            label_output_path = os.path.join(output_dir, label_filename)
            
            export_to_excel(
                matches=label_snapshots,
                output_path=label_output_path,
                sclass_names=sclass_names,
                start_date=date_start,
                end_date=date_end,
                sheets_to_export=sheets_to_export,
            )
            
            label_download_filename = _handle_cross_drive_path(label_output_path, label_filename)
            files_info.append({
                'filename': label_filename,
                'download_url': f"/download/{label_download_filename}",
                'file_size_kb': round(os.path.getsize(label_output_path) / 1024, 1),
                'match_count': len(label_snapshots),
                'file_type': 'label',
            })
        
        with _task_lock:
            _export_tasks[task_id]['progress'] = 100
            _export_tasks[task_id]['status'] = 'completed'
            msg = f'导出完成：{len(prediction_snapshots)}个非完场快照'
            if include_fulltime and label_snapshots:
                msg += f'，{len(label_snapshots)}个完场快照'
            _export_tasks[task_id]['message'] = msg
            _export_tasks[task_id]['files'] = files_info
    
    except Exception as e:
        traceback.print_exc()
        with _task_lock:
            _export_tasks[task_id]['status'] = 'failed'
            _export_tasks[task_id]['error'] = str(e)
            _export_tasks[task_id]['message'] = f'导出失败: {str(e)}'


def _handle_cross_drive_path(file_path, filename):
    """
    V1.5新增 - 处理跨盘符下载路径（复用V1.3的跨盘符修复逻辑）。
    
    返回用于/download/接口的相对路径或文件名。
    """
    try:
        rel_path = os.path.relpath(file_path, config.OUTPUT_DIR)
        if rel_path.startswith('..'):
            raise ValueError("跨盘符路径")
        return rel_path
    except ValueError:
        # 跨盘符时复制文件到默认输出目录
        import shutil
        dest_path = os.path.join(config.OUTPUT_DIR, filename)
        if os.path.exists(dest_path):
            dest_path = os.path.join(config.OUTPUT_DIR, f"cross_{filename}")
            filename = f"cross_{filename}"
        shutil.copy2(file_path, dest_path)
        return filename


# ============================================================================
# 启动入口
# ============================================================================

def main():
    """启动Flask Web应用"""
    import argparse
    # 跨平台端口配置：优先读取环境变量 DEPLOY_RUN_PORT（沙箱环境），
    # 其次 FOOTBALL_PORT，最后默认 5000
    default_port = int(os.environ.get('DEPLOY_RUN_PORT',
                         os.environ.get('FOOTBALL_PORT', '5000')))
    parser = argparse.ArgumentParser(description='足球比赛数据报表导出模块 - Web应用 V1.5 重构与优化')
    parser.add_argument('--host', default='0.0.0.0', help='监听地址')
    parser.add_argument('--port', type=int, default=default_port, help='监听端口')
    parser.add_argument('--debug', action='store_true', help='调试模式')
    args = parser.parse_args()
    
    print("=" * 60)
    print("足球比赛数据报表导出模块 - Web应用 V1.5 重构与优化")
    print("=" * 60)
    print(f"数据库: {config.DEFAULT_DB_PATH}")
    print(f"输出目录: {config.OUTPUT_DIR}")
    print(f"访问地址: http://localhost:{args.port}")
    print(f"运行平台: {'Windows' if os.name == 'nt' else 'Linux/macOS'}")
    print("=" * 60)
    
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == '__main__':
    main()
