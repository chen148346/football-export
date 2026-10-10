/* ============================================
   固定表头导出模块 V1.8 - 交互逻辑
   8 Sheet 固定表头导出（简体中文/双编码归一/球队ID归一）
   ============================================ */

let availableLeagues = [];
let selectedLeagues = [];
let pollTimer = null;

// ========== 页面初始化 ==========
document.addEventListener('DOMContentLoaded', function () {
    initDateRange();
    loadSclassList();
    loadDbInfo();
});

// ========== 日期时间范围初始化 ==========
function initDateRange() {
    const today = new Date();
    const yyyy = today.getFullYear();
    const mm = String(today.getMonth() + 1).padStart(2, '0');
    const dd = String(today.getDate()).padStart(2, '0');
    document.getElementById('date_start').value = `${yyyy}-${mm}-${dd}T00:00`;
    document.getElementById('date_end').value = `${yyyy}-${mm}-${dd}T23:59`;

    fetch('/api/date_range')
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                const d = data.data;
                document.getElementById('date_start').min = d.min_date + 'T00:00';
                document.getElementById('date_start').max = d.max_date + 'T23:59';
                document.getElementById('date_end').min = d.min_date + 'T00:00';
                document.getElementById('date_end').max = d.max_date + 'T23:59';
            }
        })
        .catch(err => console.error('日期范围加载失败:', err));
}

// V1.6: 快捷：最近一月
function setLastMonth() {
    const today = new Date();
    const yyyy = today.getFullYear();
    const mm = String(today.getMonth() + 1).padStart(2, '0');
    const dd = String(today.getDate()).padStart(2, '0');
    const end = `${yyyy}-${mm}-${dd}T23:59`;
    const startDate = new Date(today.getTime() - 30 * 24 * 60 * 60 * 1000);
    const sy = startDate.getFullYear();
    const sm = String(startDate.getMonth() + 1).padStart(2, '0');
    const sd = String(startDate.getDate()).padStart(2, '0');
    document.getElementById('date_start').value = `${sy}-${sm}-${sd}T00:00`;
    document.getElementById('date_end').value = end;
}

// V1.6: 快捷：全部日期
function setAllDates() {
    document.getElementById('date_start').value = '';
    document.getElementById('date_end').value = '';
}

// ========== 联赛列表 ==========
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

function toggleSelect(elem) {
    const list = elem.parentElement;
    list.querySelectorAll('.league-item').forEach(e => e.classList.remove('selected'));
    elem.classList.add('selected');
}

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

function moveAllToSelected() {
    selectedLeagues = selectedLeagues.concat(availableLeagues);
    selectedLeagues.sort();
    availableLeagues = [];
    renderLeagueLists();
}

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

function filterSelected() {
    const keyword = document.getElementById('selected_search').value.toLowerCase();
    document.querySelectorAll('#selected_list .league-item').forEach(item => {
        item.style.display = item.textContent.toLowerCase().includes(keyword) ? '' : 'none';
    });
}

function filterAvailable() {
    const keyword = document.getElementById('available_search').value.toLowerCase();
    document.querySelectorAll('#available_list .league-item').forEach(item => {
        item.style.display = item.textContent.toLowerCase().includes(keyword) ? '' : 'none';
    });
}

// ========== 数据库信息 ==========
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
        .catch(() => {
            document.getElementById('db_info').innerHTML = '<span style="color:red;">加载失败</span>';
        });
}

// ========== 开始固定表头导出 ==========
function startFixedExport() {
    const date_start = document.getElementById('date_start').value || null;
    const date_end = document.getElementById('date_end').value || null;
    const sclass_names = selectedLeagues.length > 0 ? selectedLeagues : null;
    const team_keyword = document.getElementById('team_keyword').value.trim() || null;
    const limit = document.getElementById('limit').value || null;
    const max_per_file = document.getElementById('max_per_file').value || null;
    const save_path = document.getElementById('save_path').value.trim() || null;

    // 校验：至少一个筛选条件
    if (!date_start && !date_end && !sclass_names && !team_keyword) {
        alert('请至少设置一个筛选条件（日期范围 / 联赛 / 球队）');
        return;
    }

    // 按钮切换为加载态
    document.querySelector('#btn_export .btn-text').style.display = 'none';
    document.querySelector('#btn_export .btn-loading').style.display = 'inline-flex';
    document.getElementById('result_area').style.display = 'none';
    document.getElementById('progress_area').style.display = 'block';
    setProgress(5, '正在提交任务...');

    const payload = {
        start_datetime: date_start,
        end_datetime: date_end,
        sclass_names: sclass_names,
        team_keyword: team_keyword,
        limit: limit,
        max_per_file: max_per_file,
        save_path: save_path,
    };

    fetch('/api/fixed_export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    })
        .then(r => r.json())
        .then(data => {
            if (!data.success) {
                throw new Error(data.error || '提交导出任务失败');
            }
            setProgress(10, '任务已提交，开始轮询进度...');
            pollTask(data.task_id);
        })
        .catch(err => {
            finishWithError(err.message);
        });
}

// ========== 进度轮询 ==========
function pollTask(taskId) {
    if (pollTimer) clearInterval(pollTimer);
    let attempts = 0;

    pollTimer = setInterval(() => {
        fetch(`/api/export_status/${taskId}`)
            .then(r => r.json())
            .then(data => {
                if (!data.success) {
                    clearInterval(pollTimer);
                    finishWithError(data.error || '状态查询失败');
                    return;
                }

                setProgress(data.progress || 0, data.message || '处理中...');

                if (data.status === 'completed') {
                    clearInterval(pollTimer);
                    renderResult(data);
                } else if (data.status === 'failed') {
                    clearInterval(pollTimer);
                    finishWithError(data.error || data.message || '导出失败');
                }
            })
            .catch(() => {
                attempts++;
                if (attempts > 30) {
                    clearInterval(pollTimer);
                    finishWithError('进度查询超时，请刷新页面查看');
                }
            });
    }, 1500);
}

// ========== 进度条 ==========
function setProgress(percent, text) {
    document.getElementById('progress_bar').style.width = percent + '%';
    document.getElementById('progress_text').textContent = text;
}

// ========== 结果渲染 ==========
function renderResult(data) {
    // 恢复按钮状态
    resetButton();
    document.getElementById('progress_bar').style.width = '100%';

    let html = '<div style="color:#2e7d32;font-weight:bold;margin-bottom:10px;">✅ 导出完成</div>';

    if (data.files && data.files.length > 0) {
        html += `<div style="margin-bottom:8px;">共导出 ${data.file_count || data.files.length} 个文件：</div>`;
        data.files.forEach(f => {
            html += `<div style="margin:4px 0;">
                <a href="${f.download_url}" target="_blank" class="download-link">⬇ ${f.filename}</a>
                <span style="color:#999;">（${f.file_size_kb} KB，${f.match_count} 场）</span>
            </div>`;
        });
    } else if (data.download_url) {
        html += `<div style="margin-bottom:8px;">${data.message || ''}</div>
            <div><a href="${data.download_url}" target="_blank" class="download-link">⬇ ${data.filename}</a>
            <span style="color:#999;">（${data.file_size_kb} KB）</span></div>`;
    } else {
        html += `<div>${data.message || ''}</div>`;
    }

    const area = document.getElementById('result_area');
    area.style.display = 'block';
    area.innerHTML = html;
}

function finishWithError(msg) {
    resetButton();
    document.getElementById('result_area').style.display = 'block';
    document.getElementById('result_area').innerHTML = `
        <div style="color:#d32f2f;font-weight:bold;margin-bottom:6px;">❌ 导出失败</div>
        <div>${msg || '未知错误'}</div>`;
}

function resetButton() {
    document.querySelector('#btn_export .btn-text').style.display = 'inline';
    document.querySelector('#btn_export .btn-loading').style.display = 'none';
}

// ========== 重置表单 ==========
function resetForm() {
    if (pollTimer) clearInterval(pollTimer);
    selectedLeagues = [];
    renderLeagueLists();
    document.getElementById('team_keyword').value = '';
    document.getElementById('limit').value = '';
    document.getElementById('max_per_file').value = '50';
    document.getElementById('save_path').value = '';
    document.getElementById('progress_area').style.display = 'none';
    document.getElementById('result_area').style.display = 'none';
    resetButton();
    initDateRange();
}