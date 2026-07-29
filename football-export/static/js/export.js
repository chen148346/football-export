/* ============================================
   足球比赛数据报表导出模块 V1.1 - 交互逻辑
   ============================================ */

// 全局状态
let availableLeagues = [];   // 可选联赛列表
let selectedLeagues = [];    // 已选联赛列表
let pollTimer = null;        // 轮询定时器

// ========== 页面初始化 ==========
document.addEventListener('DOMContentLoaded', function() {
    initDateRange();
    loadSclassList();
    loadDbInfo();
});

// ========== V1.6: 日期时间范围初始化 ==========
function initDateRange() {
    // V1.6: 默认值为当前日期的 00:00 和 23:59
    const today = new Date();
    const yyyy = today.getFullYear();
    const mm = String(today.getMonth() + 1).padStart(2, '0');
    const dd = String(today.getDate()).padStart(2, '0');
    document.getElementById('date_start').value = `${yyyy}-${mm}-${dd}T00:00`;
    document.getElementById('date_end').value = `${yyyy}-${mm}-${dd}T23:59`;

    // 同时从后端获取数据库的日期范围，用于设置 min/max
    fetch('/api/date_range')
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                const d = data.data;
                // datetime-local 的 min/max 需要带时间
                document.getElementById('date_start').min = d.min_date + 'T00:00';
                document.getElementById('date_start').max = d.max_date + 'T23:59';
                document.getElementById('date_end').min = d.min_date + 'T00:00';
                document.getElementById('date_end').max = d.max_date + 'T23:59';
            }
        })
        .catch(err => console.error('日期范围加载失败:', err));
}

// V1.6: 快捷：最近一月（带时间）
function setLastMonth() {
    const today = new Date();
    const yyyy = today.getFullYear();
    const mm = String(today.getMonth() + 1).padStart(2, '0');
    const dd = String(today.getDate()).padStart(2, '0');
    const end = `${yyyy}-${mm}-${dd}T23:59`;
    const startDate = new Date(today.getTime() - 30*24*60*60*1000);
    const sy = startDate.getFullYear();
    const sm = String(startDate.getMonth() + 1).padStart(2, '0');
    const sd = String(startDate.getDate()).padStart(2, '0');
    const start = `${sy}-${sm}-${sd}T00:00`;
    document.getElementById('date_start').value = start;
    document.getElementById('date_end').value = end;
}

// V1.6: 快捷：全部日期（清空时间选择器）
function setAllDates() {
    document.getElementById('date_start').value = '';
    document.getElementById('date_end').value = '';
}

// ========== 联赛列表加载 ==========
function loadSclassList() {
    fetch('/api/sclass_list')
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                availableLeagues = data.data;
                renderLeagueLists();
            }
        })
        .catch(err => console.error('联赛列表加载失败:', err));
}

// 渲染联赛列表
function renderLeagueLists() {
    const selectedList = document.getElementById('selected_list');
    const availableList = document.getElementById('available_list');
    
    selectedList.innerHTML = selectedLeagues.map(l => 
        `<div class="league-item" onclick="toggleSelect(this, '${escapeStr(l)}', 'selected')" ondblclick="moveToAvailable()">${l}</div>`
    ).join('');
    
    availableList.innerHTML = availableLeagues.map(l => 
        `<div class="league-item" onclick="toggleSelect(this, '${escapeStr(l)}', 'available')" ondblclick="moveToSelected()">${l}</div>`
    ).join('');
    
    if (selectedLeagues.length === 0) {
        selectedList.innerHTML = '<div style="color:#999;text-align:center;padding:20px;">暂无已选联赛</div>';
    }
    if (availableLeagues.length === 0) {
        availableList.innerHTML = '<div style="color:#999;text-align:center;padding:20px;">暂无可选联赛</div>';
    }
}

function escapeStr(s) {
    return String(s).replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

// 切换选中状态
function toggleSelect(elem, league, side) {
    // 清除同组其他选中
    const list = elem.parentElement;
    list.querySelectorAll('.league-item').forEach(e => e.classList.remove('selected'));
    elem.classList.add('selected');
}

// 移动到已选
function moveToSelected() {
    const selected = document.querySelector('#available_list .selected');
    if (selected) {
        const league = selected.textContent;
        if (!selectedLeagues.includes(league)) {
            selectedLeagues.push(league);
            availableLeagues = availableLeagues.filter(l => l !== league);
            renderLeagueLists();
        }
    }
}

// 移动到可选
function moveToAvailable() {
    const selected = document.querySelector('#selected_list .selected');
    if (selected) {
        const league = selected.textContent;
        if (league && !availableLeagues.includes(league)) {
            availableLeagues.push(league);
            availableLeagues.sort();
            selectedLeagues = selectedLeagues.filter(l => l !== league);
            renderLeagueLists();
        }
    }
}

// 全选
function moveAllToSelected() {
    selectedLeagues = selectedLeagues.concat(availableLeagues);
    selectedLeagues.sort();
    availableLeagues = [];
    renderLeagueLists();
}

// 清空
function moveAllToAvailable() {
    availableLeagues = availableLeagues.concat(selectedLeagues);
    availableLeagues.sort();
    selectedLeagues = [];
    renderLeagueLists();
}

function clearSelectedLeagues() {
    moveAllToAvailable();
}

function selectAllLeagues() {
    moveAllToSelected();
}

// 搜索过滤
function filterSelected() {
    const keyword = document.getElementById('selected_search').value.toLowerCase();
    const items = document.querySelectorAll('#selected_list .league-item');
    items.forEach(item => {
        const text = item.textContent.toLowerCase();
        item.style.display = text.includes(keyword) ? '' : 'none';
    });
}

function filterAvailable() {
    const keyword = document.getElementById('available_search').value.toLowerCase();
    const items = document.querySelectorAll('#available_list .league-item');
    items.forEach(item => {
        const text = item.textContent.toLowerCase();
        item.style.display = text.includes(keyword) ? '' : 'none';
    });
}

// ========== 数据库信息加载 ==========
function loadDbInfo() {
    fetch('/api/db_info')
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                const d = data.data;
                const html = `
                    <div class="db-stat">
                        <div class="stat-label">总比赛数</div>
                        <div class="stat-value">${d.tables.matches || 0}</div>
                    </div>
                    <div class="db-stat">
                        <div class="stat-label">完场比赛</div>
                        <div class="stat-value">${d.finished_matches}</div>
                    </div>
                    <div class="db-stat">
                        <div class="stat-label">快照数据</div>
                        <div class="stat-value">${d.tables.snapshots || 0}</div>
                    </div>
                    <div class="db-stat">
                        <div class="stat-label">联赛数量</div>
                        <div class="stat-value">${availableLeagues.length}</div>
                    </div>
                `;
                document.getElementById('db_info').innerHTML = html;
            }
        })
        .catch(err => {
            document.getElementById('db_info').innerHTML = '<span style="color:red;">加载失败</span>';
        });
}

// ========== V1.5新增: 比赛模式切换 ==========
function onMatchModeChange() {
    const mode = document.getElementById('match_mode').value;
    const minuteRow = document.getElementById('minute_range_row');
    const fulltimeRow = document.getElementById('include_fulltime_row');
    
    if (mode === 'custom') {
        // 自定义分钟区间：显示分钟输入和完场复选框
        minuteRow.style.display = 'flex';
        fulltimeRow.style.display = 'flex';
    } else if (mode === 'halftime') {
        // 半场模式：隐藏分钟输入，显示完场复选框
        minuteRow.style.display = 'none';
        fulltimeRow.style.display = 'flex';
    } else {
        // 完场模式：隐藏所有V1.5控件
        minuteRow.style.display = 'none';
        fulltimeRow.style.display = 'none';
    }
}

// ========== 开始导出 ==========
function startExport() {
    // 收集参数
    const date_start = document.getElementById('date_start').value || null;
    const date_end = document.getElementById('date_end').value || null;
    const sclass_names = selectedLeagues.length > 0 ? selectedLeagues : null;
    const team_keyword = document.getElementById('team_keyword').value.trim() || null;
    const limit = document.getElementById('limit').value || null;
    
    // V1.2新增: 收集选中的Sheet
    const sheets = ['match']; // match必选
    document.querySelectorAll('.sheet-cb:checked').forEach(cb => {
        sheets.push(cb.value);
    });
    
    // V1.2新增: 单文件最大比赛数
    const max_per_file = document.getElementById('max_per_file').value || 50;
    
    // V1.2新增: 保存路径
    const save_path = document.getElementById('save_path').value.trim() || null;
    
    // V1.5新增: 比赛模式
    const match_mode = document.getElementById('match_mode').value;
    const include_fulltime = document.getElementById('include_fulltime').checked;
    const min_minute = document.getElementById('min_minute').value;
    const max_minute = document.getElementById('max_minute').value;
    
    // V1.6新增: 按球队拆分
    const split_by_team = document.getElementById('split_by_team').checked;
    
    // 参数校验
    if (date_start && date_end && date_start > date_end) {
        showResult('error', '日期错误', '开始日期不能晚于结束日期');
        return;
    }
    
    // V1.5: 自定义分钟区间校验
    if (match_mode === 'custom') {
        const minVal = parseInt(min_minute);
        const maxVal = parseInt(max_minute);
        if (isNaN(minVal) || isNaN(maxVal)) {
            showResult('error', '分钟区间错误', '分钟区间必须为整数');
            return;
        }
        if (minVal < 0 || maxVal > 120) {
            showResult('error', '分钟区间错误', '分钟区间必须在0-120范围内');
            return;
        }
        if (minVal >= maxVal) {
            showResult('error', '分钟区间错误', '开始分钟必须小于结束分钟');
            return;
        }
    }
    
    // 禁用按钮，显示Loading
    const btn = document.getElementById('btn_export');
    btn.disabled = true;
    btn.querySelector('.btn-text').style.display = 'none';
    btn.querySelector('.btn-loading').style.display = 'inline-flex';
    
    // 显示进度区
    document.getElementById('progress_area').style.display = 'block';
    document.getElementById('result_area').style.display = 'none';
    updateProgress(5, '正在提交导出请求...');
    
    // 构建请求参数
    const requestBody = {
        date_start, date_end, sclass_names, team_keyword, limit,
        sheets, max_per_file, save_path,  // V1.2参数
        split_by_team  // V1.6参数
    };
    
    // V1.5: 非完场模式参数
    if (match_mode !== 'fulltime') {
        requestBody.match_mode = match_mode;
        requestBody.include_fulltime = include_fulltime;
        if (match_mode === 'custom') {
            requestBody.min_minute = parseInt(min_minute);
            requestBody.max_minute = parseInt(max_minute);
        }
    }
    
    // 发送导出请求
    fetch('/api/export_excel', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(requestBody)
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            updateProgress(10, '导出任务已启动，正在处理...');
            startPolling(data.task_id);
        } else {
            resetExportButton();
            showResult('error', '导出失败', data.error || '未知错误');
        }
    })
    .catch(err => {
        resetExportButton();
        showResult('error', '网络错误', '请求失败: ' + err.message);
    });
}

// 轮询任务状态
function startPolling(taskId) {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(() => {
        fetch(`/api/export_status/${taskId}`)
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    updateProgress(data.progress, data.message);
                    if (data.status === 'completed') {
                        clearInterval(pollTimer);
                        resetExportButton();
                        
                        // V1.2: 支持分片多文件下载
                        if (data.files && data.files.length > 0) {
                            // 分片导出：显示多个下载链接
                            let fileListHtml = '';
                            data.files.forEach(f => {
                                fileListHtml += `<a href="${f.download_url}" class="download-link" download="${f.filename}" style="margin:5px 10px 5px 0;">📥 ${f.filename} (${f.file_size_kb}KB, ${f.match_count}场)</a>`;
                            });
                            showResultMulti('success', '导出完成（分片）',
                                `成功导出 ${data.file_count} 个文件，耗时 ${data.elapsed} 秒。`,
                                fileListHtml);
                        } else {
                            // 单文件导出
                            showResult('success', '导出完成', 
                                `成功导出数据，文件大小 ${data.file_size_kb} KB，耗时 ${data.elapsed} 秒。`,
                                data.download_url, data.filename);
                        }
                    } else if (data.status === 'failed') {
                        clearInterval(pollTimer);
                        resetExportButton();
                        showResult('error', '导出失败', data.error || '未知错误');
                    }
                }
            })
            .catch(err => console.error('轮询失败:', err));
    }, 500); // 每500ms轮询一次
}

// V1.2新增: 显示多文件下载结果
function showResultMulti(type, title, message, filesHtml) {
    const area = document.getElementById('result_area');
    area.style.display = 'block';
    
    if (type === 'success') {
        area.innerHTML = `
            <div class="result-success">
                <h3>✅ ${title}</h3>
                <p>${message}</p>
                <div style="margin-top:10px;">${filesHtml}</div>
            </div>
        `;
    } else {
        area.innerHTML = `
            <div class="result-error">
                <h3>❌ ${title}</h3>
                <p>${message}</p>
            </div>
        `;
    }
}

// V1.2新增: Sheet全选/清空
function selectAllSheets(checked) {
    document.querySelectorAll('.sheet-cb').forEach(cb => {
        cb.checked = checked;
    });
}

// 更新进度条
function updateProgress(percent, message) {
    const bar = document.getElementById('progress_bar');
    const text = document.getElementById('progress_text');
    bar.style.width = percent + '%';
    bar.textContent = percent + '%';
    text.textContent = message;
}

// 重置导出按钮
function resetExportButton() {
    const btn = document.getElementById('btn_export');
    btn.disabled = false;
    btn.querySelector('.btn-text').style.display = 'inline';
    btn.querySelector('.btn-loading').style.display = 'none';
}

// 显示结果
function showResult(type, title, message, downloadUrl, filename) {
    const area = document.getElementById('result_area');
    area.style.display = 'block';
    
    if (type === 'success') {
        area.innerHTML = `
            <div class="result-success">
                <h3>✅ ${title}</h3>
                <p>${message}</p>
                ${downloadUrl ? `<a href="${downloadUrl}" class="download-link" download="${filename}">📥 下载文件: ${filename}</a>` : ''}
            </div>
        `;
    } else {
        area.innerHTML = `
            <div class="result-error">
                <h3>❌ ${title}</h3>
                <p>${message}</p>
            </div>
        `;
    }
}

// 重置表单
function resetForm() {
    if (pollTimer) clearInterval(pollTimer);
    setLastMonth();
    moveAllToAvailable();
    document.getElementById('team_keyword').value = '';
    document.getElementById('limit').value = '';
    document.getElementById('progress_area').style.display = 'none';
    document.getElementById('result_area').style.display = 'none';
    resetExportButton();
    // V1.5: 重置比赛模式
    document.getElementById('match_mode').value = 'fulltime';
    document.getElementById('include_fulltime').checked = false;
    document.getElementById('min_minute').value = '60';
    document.getElementById('max_minute').value = '70';
    onMatchModeChange();
}
