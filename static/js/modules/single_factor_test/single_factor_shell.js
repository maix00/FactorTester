/**
 * single_factor_shell.js
 * 单因子测试页面外壳 — 因子列表加载、选择、tab 切换。
 *
 * 全局状态：
 *   _sftFactorFamilies[]        — 完整因子列表（public + custom）
 *   _sftGroupedFactorFamilies{} — 按类别分组的因子
 *   _sftCurrentFactorId         — 当前选中因子 id
 *   _sftCurrentFactorType       — 'public' / 'custom'
 *
 * 生命周期：
 *   DOMContentLoaded → initSingleFactorShell()
 *     → loadSingleFactorFamilyList()    (GET /single_factor_test/api/list)
 *     → selectSingleFactorFamily(id)    (加载 IC + 分组回测模块)
 */
let _sftFactorFamilies = [];
let _sftGroupedFactorFamilies = {};
let _sftCurrentFactorId = '';
let _sftCurrentFactorType = 'public';
let _sftCurrentOwner = '';

window.SingleFactorResearch = (function() {
    const VIEW_KEY = 'single_factor_research_view_uuid';
    const CURSOR_KEY = 'single_factor_research_job_cursors';
    let workspace = null;
    let monitorGeneration = 0;

    function uuid() {
        return window.crypto && window.crypto.randomUUID
            ? window.crypto.randomUUID()
            : String(Date.now()) + '-' + Math.random().toString(16).slice(2);
    }

    async function jsonRequest(url, options) {
        const response = await fetch(url, options);
        const body = await response.json();
        if (!response.ok || !body.success) throw new Error(body.error || ('HTTP ' + response.status));
        return body;
    }

    async function bootstrapView() {
        let viewUuid = '';
        try { viewUuid = sessionStorage.getItem(VIEW_KEY) || ''; } catch (e) {}
        if (!viewUuid) viewUuid = uuid();
        const body = await jsonRequest('/api/single_factor_test/page', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({view_uuid: viewUuid})
        });
        window._viewUuid = body.view_uuid;
        window._pageUuid = body.view_uuid;
        try { sessionStorage.setItem(VIEW_KEY, body.view_uuid); } catch (e) {}
        const label = document.getElementById('page-uuid-label');
        if (label) label.textContent = body.view_uuid;
    }

    async function ensureWorkspace(factorId) {
        function hasFamily(item) {
            const payload = item && item.configuration && item.configuration.payload;
            const families = payload && payload.shared && payload.shared.factor_families;
            return Array.isArray(families) && families.some(entry => entry && entry.alias === factorId);
        }
        if (workspace && hasFamily(workspace)) return workspace;
        const listed = await jsonRequest('/api/workspaces');
        workspace = (listed.workspaces || []).find(hasFamily) || null;
        if (!workspace) {
            const created = await jsonRequest('/api/workspaces', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    factor_families: [{alias: factorId}], factors: [],
                    title: factorId + ' research'
                })
            });
            workspace = created.workspace;
        }
        return workspace;
    }

    async function renewLease() {
        return workspace;
    }

    async function submit(kind, draft) {
        await ensureWorkspace(String(draft.factor_family_alias || _sftCurrentFactorId || ''));
        const configuration = workspace.configuration;
        const payload = JSON.parse(JSON.stringify(configuration.payload || {}));
        payload.schema_version = 1;
        payload.shared = payload.shared || {};
        payload.shared.factor_families = [{alias: String(draft.factor_family_alias || _sftCurrentFactorId || '')}];
        payload.shared.factors = Array.isArray(payload.shared.factors) ? payload.shared.factors : [];
        payload.analyses = payload.analyses || {};
        payload.analyses[kind] = draft;
        payload.ui = payload.ui || {};
        const updated = await jsonRequest('/api/workspaces/' + encodeURIComponent(workspace.workspace_id) + '/configuration', {
            method: 'PUT', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({expected_revision: configuration.revision, payload: payload})
        });
        workspace.configuration = updated.configuration;
        return jsonRequest('/api/runs', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                workspace_id: workspace.workspace_id,
                configuration_revision: workspace.configuration.revision,
                analyses: [kind]
            })
        });
    }

    async function updateUiSnapshot(uiSnapshot) {
        await ensureWorkspace(_sftCurrentFactorId || '');
        const configuration = workspace.configuration;
        const payload = JSON.parse(JSON.stringify(configuration.payload || {}));
        payload.ui = uiSnapshot || {};
        const updated = await jsonRequest('/api/workspaces/' + encodeURIComponent(workspace.workspace_id) + '/configuration', {
            method: 'PUT', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({expected_revision: configuration.revision, payload: payload})
        });
        workspace.configuration = updated.configuration;
        return updated.configuration;
    }

    async function saveTemplate(name, uiSnapshot) {
        await updateUiSnapshot(uiSnapshot);
        return jsonRequest('/api/workspaces/' + encodeURIComponent(workspace.workspace_id) + '/configuration/templates', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name: name})
        });
    }

    async function listTemplates() {
        const data = await jsonRequest('/api/configuration-templates');
        const current = _sftCurrentFactorId || '';
        return (data.templates || []).filter(function(item) {
            const families = item && item.payload && item.payload.shared && item.payload.shared.factor_families;
            return Array.isArray(families) && families.some(entry => entry && entry.alias === current);
        });
    }

    async function loadTemplate(configurationId) {
        await ensureWorkspace(_sftCurrentFactorId || '');
        const data = await jsonRequest('/api/workspaces/' + encodeURIComponent(workspace.workspace_id) + '/configuration/load-template', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                configuration_id: configurationId,
                expected_revision: workspace.configuration.revision
            })
        });
        workspace.configuration = data.configuration;
        return data.configuration;
    }

    async function overwriteTemplate(configurationId) {
        return jsonRequest('/api/configuration-templates/' + encodeURIComponent(configurationId), {
            method: 'PUT', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({workspace_id: workspace.workspace_id})
        });
    }

    async function deleteTemplate(configurationId) {
        return jsonRequest('/api/configuration-templates/' + encodeURIComponent(configurationId), {method: 'DELETE'});
    }

    function jobCursors() {
        try { return JSON.parse(sessionStorage.getItem(CURSOR_KEY) || '{}'); }
        catch (e) { return {}; }
    }

    function saveJobCursor(jobId, seq) {
        const cursors = jobCursors();
        cursors[jobId] = Number(seq || 0);
        try { sessionStorage.setItem(CURSOR_KEY, JSON.stringify(cursors)); } catch (e) {}
    }

    function progressFrom(job, eventData) {
        const data = eventData || (job.latest_progress && job.latest_progress.data) || {};
        const completed = Number(data.completed || 0);
        const total = Number(data.total || 0);
        const phases = job.manifest && job.manifest.data && Array.isArray(job.manifest.data.phases)
            ? job.manifest.data.phases : [];
        const notice = Array.isArray(job.plan_notices) && job.plan_notices.length
            ? job.plan_notices[0].message : '';
        return {
            percent: total > 0 ? Math.max(0, Math.min(100, completed / total * 100)) : 0,
            text: data.message || notice || data.phase || (phases.length ? ('流程 ' + phases.length + ' 步') : job.status) || '',
        };
    }

    function renderJob(job) {
        const list = document.getElementById('research-job-monitor-list');
        if (!list) return null;
        let row = list.querySelector('[data-job-id="' + CSS.escape(job.job_id) + '"]');
        if (!row) {
            row = document.createElement('div');
            row.className = 'research-job-row';
            row.dataset.jobId = job.job_id;
            row.innerHTML = '<div class="research-job-identity"></div>'
                + '<div class="research-job-progress"><div class="research-job-progress-label"></div>'
                + '<div class="research-job-progress-track"><div class="research-job-progress-fill"></div></div></div>'
                + '<div class="research-job-actions"></div>'
                + '<div class="research-job-detail" hidden></div>';
            list.appendChild(row);
        }
        const progress = progressFrom(job);
        const binding = job.research_binding || {};
        const context = job.server_context || {};
        const bindingText = binding.work_package_ref || binding.profile_ref || binding.branch_id || '';
        row.querySelector('.research-job-identity').textContent = job.kind + ' · ' + job.status
            + ' · ' + (job.workspace_id || 'workspace?')
            + ' · port ' + (context.port || '—')
            + ' · profile ' + (context.profile || 'default')
            + (bindingText ? ' · ' + bindingText : '');
        row.querySelector('.research-job-progress-label').textContent = progress.text;
        row.querySelector('.research-job-progress-fill').style.width = progress.percent + '%';
        const actions = row.querySelector('.research-job-actions');
        actions.replaceChildren();
        if (!actions.querySelector('.research-job-details-button')) {
            const detailsButton = document.createElement('button');
            detailsButton.type = 'button';
            detailsButton.className = 'research-job-details-button';
            detailsButton.textContent = '配置/生成物';
            detailsButton.onclick = async function() {
                const detail = row.querySelector('.research-job-detail');
                detail.hidden = !detail.hidden;
                if (!detail.hidden) await loadJobDetail(job, detail);
            };
            actions.appendChild(detailsButton);
        }
        if (job.status === 'awaiting_confirmation') {
            const approve = document.createElement('button');
            approve.type = 'button';
            approve.textContent = '确认';
            approve.onclick = async function() {
                approve.disabled = true;
                await fetch('/api/jobs/' + encodeURIComponent(job.job_id) + '/approve', {method: 'POST'});
                await restoreActiveJobs();
            };
            actions.appendChild(approve);
        }
        if (job.status === 'paused') {
            const next = document.createElement('button');
            next.type = 'button';
            next.textContent = '下一步';
            next.onclick = async function() {
                next.disabled = true;
                await fetch('/api/jobs/' + encodeURIComponent(job.job_id) + '/continue', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({action: 'continue'})
                });
            };
            const end = document.createElement('button');
            end.type = 'button';
            end.textContent = '运行到底';
            end.onclick = async function() {
                end.disabled = true;
                await fetch('/api/jobs/' + encodeURIComponent(job.job_id) + '/continue', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({action: 'end'})
                });
            };
            actions.appendChild(next);
            actions.appendChild(end);
        }
        if (['submitted', 'planning', 'awaiting_confirmation', 'queued', 'running', 'paused'].includes(job.status)) {
            const cancel = document.createElement('button');
            cancel.type = 'button';
            cancel.title = '取消任务';
            cancel.textContent = '取消';
            cancel.onclick = async function() {
                cancel.disabled = true;
                await fetch('/api/jobs/' + encodeURIComponent(job.job_id) + '/cancel', {method: 'POST'});
            };
            actions.appendChild(cancel);
        } else if (job.status === 'cancelled' || job.status === 'failed') {
            const retry = document.createElement('button');
            retry.type = 'button';
            retry.textContent = '重新排队';
            retry.title = '以同一冻结配置创建新任务';
            retry.onclick = async function() {
                retry.disabled = true;
                await fetch('/api/jobs/' + encodeURIComponent(job.job_id) + '/retry', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({})
                });
                await restoreActiveJobs();
            };
            actions.appendChild(retry);
        }
        if (Number(job.artifact_count || 0) > 0) {
            const clear = document.createElement('button');
            clear.type = 'button';
            clear.textContent = '清除完整结果';
            clear.onclick = async function() {
                clear.disabled = true;
                await fetch('/api/jobs/' + encodeURIComponent(job.job_id) + '/artifacts', {method: 'DELETE'});
                await restoreActiveJobs();
            };
            actions.appendChild(clear);
        }
        if (['succeeded', 'failed', 'cancelled'].includes(job.status)) {
            const restore = document.createElement('button');
            restore.type = 'button';
            restore.textContent = '恢复冻结配置';
            restore.title = '从该任务所属 RunSpec 创建一个新的研究工作区';
            restore.onclick = async function() {
                restore.disabled = true;
                try {
                    const data = await jsonRequest('/api/runs/' + encodeURIComponent(job.run_id) + '/clone-workspace', {
                        method: 'POST', headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({})
                    });
                    workspace = data.workspace;
                    window.location.reload();
                } catch (error) {
                    restore.disabled = false;
                    throw error;
                }
            };
            actions.appendChild(restore);
        }
        return row;
    }

    async function loadJobDetail(job, target) {
        target.textContent = '正在读取任务详情…';
        try {
            const detail = await jsonRequest('/api/jobs/' + encodeURIComponent(job.job_id));
            const artifacts = await jsonRequest('/api/jobs/' + encodeURIComponent(job.job_id) + '/artifacts');
            target.replaceChildren();
            const summary = document.createElement('div');
            summary.className = 'research-job-detail-summary';
            const context = detail.server_context || {};
            summary.textContent = '端口 ' + (context.port || '—') + ' · profile ' + (context.profile || 'default')
                + ' · deployment ' + (context.deployment_id || '—')
                + (detail.research_binding && detail.research_binding.work_package_ref
                    ? ' · 研究工作 ' + detail.research_binding.work_package_ref : '');
            target.appendChild(summary);
            const config = document.createElement('pre');
            config.className = 'research-job-config';
            config.textContent = JSON.stringify({
                run_spec_hash: detail.run_spec_hash,
                output_requests: detail.output_requests || [],
                configuration: detail.configuration || null
            }, null, 2);
            target.appendChild(config);
            const title = document.createElement('div');
            title.textContent = '生成物';
            title.className = 'research-job-artifacts-title';
            target.appendChild(title);
            const list = document.createElement('div');
            (artifacts.artifacts || []).forEach(function(item) {
                if (item.state !== 'active') return;
                const line = document.createElement('div');
                line.className = 'research-job-artifact-line';
                const link = document.createElement('a');
                link.href = '/api/jobs/' + encodeURIComponent(job.job_id) + '/artifacts/' + encodeURIComponent(item.name);
                link.textContent = (item.description || item.name) + ' · ' + item.name + '（' + (item.content_type || 'file') + '，' + (item.size_bytes || 0) + ' bytes）';
                link.download = item.name;
                line.appendChild(link);
                list.appendChild(line);
            });
            target.appendChild(list);
            const all = document.createElement('a');
            all.href = '/api/jobs/' + encodeURIComponent(job.job_id) + '/artifacts/archive';
            all.textContent = '一键下载全部生成物';
            all.download = 'job-' + job.job_id + '-artifacts.zip';
            all.className = 'research-job-download-all';
            target.appendChild(all);
        } catch (error) {
            target.textContent = error.message || String(error);
        }
    }

    async function watchJob(job, generation) {
        if (!['submitted', 'planning', 'awaiting_confirmation', 'queued', 'running', 'paused'].includes(job.status)) return;
        const after = Number(jobCursors()[job.job_id] || 0);
        const url = '/api/jobs/' + encodeURIComponent(job.job_id) + '/stream' + (after ? '?after=' + after : '');
        const response = await fetch(url);
        if (!response.ok || generation !== monitorGeneration) return;
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let event = '';
        let seq = after;
        while (generation === monitorGeneration) {
            const chunk = await reader.read();
            if (chunk.done) break;
            buffer += decoder.decode(chunk.value, {stream: true});
            const lines = buffer.split('\n');
            buffer = lines.pop();
            for (const line of lines) {
                if (line.startsWith('id: ')) seq = Number(line.slice(4).trim()) || seq;
                else if (line.startsWith('event: ')) event = line.slice(7).trim();
                else if (line.startsWith('data: ')) {
                    let data = {};
                    try { data = JSON.parse(line.slice(6)); } catch (e) { continue; }
                    saveJobCursor(job.job_id, seq);
                    if (event === 'progress' || event === 'activity' || event === 'activity_manifest') {
                        job.latest_progress = {data: data};
                    }
                    if (event === 'activity_manifest') job.manifest = {data: data};
                    if (event === 'plan') {
                        job.status = data.status || job.status;
                        job.execution_plan = data.execution_plan;
                        job.plan_notices = data.notices || [];
                    }
                    if (event === 'reset') {
                        job.status = data.status || job.status;
                        job.latest_progress = data.latest_progress || job.latest_progress;
                        job.manifest = data.manifest || job.manifest;
                    }
                    if (event === 'heartbeat') {
                        job.status = data.status || job.status;
                        job.latest_progress = data.latest_progress || job.latest_progress;
                    }
                    if (event === 'result') job.status = 'succeeded';
                    if (event === 'error') job.status = data.cancelled ? 'cancelled' : 'failed';
                    renderJob(job);
                }
            }
        }
    }

    async function restoreActiveJobs() {
        if (!workspace) return;
        const generation = ++monitorGeneration;
        // Job ownership is user-scoped, so this module also shows tasks
        // submitted from CLI, other Web pages, and other workspaces.
        const data = await jsonRequest('/api/jobs?limit=100');
        if (generation !== monitorGeneration) return;
        const jobs = data.jobs || [];
        const visible = jobs;
        const monitor = document.getElementById('research-job-monitor');
        const list = document.getElementById('research-job-monitor-list');
        if (!monitor || !list) return;
        list.replaceChildren();
        monitor.hidden = visible.length === 0;
        visible.forEach(renderJob);
        visible.forEach(function(job) { watchJob(job, generation).catch(function() {}); });
        try {
            const storage = await jsonRequest('/api/jobs/storage');
            const label = document.getElementById('research-job-storage');
            if (label) label.textContent = Math.round(storage.usage_bytes / 1048576) + ' / '
                + Math.round(storage.quota_bytes / 1048576) + ' MiB';
        } catch (e) {}
    }

    async function detach() {
        return;
    }

    return {
        bootstrapView, ensureWorkspace, renewLease, submit, detach,
        updateUiSnapshot, saveTemplate, listTemplates, loadTemplate, overwriteTemplate, deleteTemplate,
        restoreActiveJobs,
        workspace: function() { return workspace; }
    };
})();

document.addEventListener('DOMContentLoaded', function() {
    initSingleFactorShell();
});

async function initSingleFactorShell() {
    initSingleFactorSidebarResizer();
    initSingleFactorSidebarToggle();
    await window.SingleFactorResearch.bootstrapView();
    const clearWorkspaceResults = document.getElementById('research-job-clear-workspace-results');
    if (clearWorkspaceResults) {
        clearWorkspaceResults.addEventListener('click', async function() {
            const current = window.SingleFactorResearch.workspace();
            if (!current) return;
            clearWorkspaceResults.disabled = true;
            try {
                await jsonRequest('/api/jobs/artifacts?workspace_id=' + encodeURIComponent(current.workspace_id), {
                    method: 'DELETE'
                });
                await window.SingleFactorResearch.restoreActiveJobs();
            } finally {
                clearWorkspaceResults.disabled = false;
            }
        });
    }
    const clearWorkspaceHistory = document.getElementById('research-job-clear-workspace-history');
    if (clearWorkspaceHistory) {
        clearWorkspaceHistory.addEventListener('click', async function() {
            const current = window.SingleFactorResearch.workspace();
            if (!current) return;
            if (!window.confirm('删除当前工作区全部已完成、失败和已取消的任务记录？运行中的任务会保留。')) return;
            clearWorkspaceHistory.disabled = true;
            try {
                await jsonRequest('/api/jobs?workspace_id=' + encodeURIComponent(current.workspace_id), {
                    method: 'DELETE'
                });
                await window.SingleFactorResearch.restoreActiveJobs();
            } finally {
                clearWorkspaceHistory.disabled = false;
            }
        });
    }
    await loadSingleFactorFamilyList();

    const app = document.querySelector('.single-factor-app');
    const initialFactor = app?.dataset.initialFactor || '';
    if (initialFactor) {
        await selectSingleFactorFamily(
            initialFactor,
            app?.dataset.initialFactorType || 'public',
            app?.dataset.initialOwnerUsername || '',
            { replaceHistory: true }
        );
    }
}

async function loadSingleFactorFamilyList() {
    const filter = document.getElementById('factor-family-filter')?.value || '';
    const includeSubordinates = document.getElementById('include-subordinate-factors')?.checked;
    const params = new URLSearchParams();
    if (filter.trim()) params.set('search', filter.trim());
    if (includeSubordinates) params.set('include_subordinates', '1');

    try {
        const res = await fetch('/single_factor_test/api/list?' + params.toString());
        const data = await res.json();
        if (!data.success) throw new Error(data.error || '加载失败');
        const custom = (data.custom_factors || []).map(f => ({...f, type: 'custom'}));
        const publicF = (data.public_factors || []).map(f => ({...f, type: 'public'}));
        _sftFactorFamilies = [...custom, ...publicF];
        _sftGroupedFactorFamilies = groupSingleFactorFamilies(_sftFactorFamilies);
        renderSingleFactorFamilyList();
    } catch (e) {
        const list = document.getElementById('factor-family-list');
        if (list) list.innerHTML = '<div class="factor-family-list-empty" style="color:#d40000">加载失败</div>';
    }
}

function filterSingleFactorFamilyList() {
    loadSingleFactorFamilyList();
}

function groupSingleFactorFamilies(factors) {
    const groups = {};
    factors.forEach(f => {
        const key = f.group || getSingleFactorGroup(f.name || f.id);
        if (!groups[key]) groups[key] = [];
        groups[key].push(f);
    });
    return groups;
}

function getSingleFactorGroup(name) {
    let group = '';
    let upperCount = 0;
    for (const c of String(name || '')) {
        if (c === c.toUpperCase() && c !== c.toLowerCase()) {
            upperCount += 1;
            if (upperCount === 1) group += c;
            else if (upperCount === 2) break;
        } else if (upperCount === 1) {
            group += c;
        }
    }
    return group || name || '';
}

function renderSingleFactorFamilyList() {
    const list = document.getElementById('factor-family-list');
    if (!list) return;
    const groups = Object.keys(_sftGroupedFactorFamilies).sort();
    if (!groups.length) {
        list.innerHTML = '<div class="factor-family-list-empty">无匹配因子</div>';
        return;
    }

    let html = '';
    groups.forEach(group => {
        const groupItems = (_sftGroupedFactorFamilies[group] || []).slice().sort(compareSingleFactorFamiliesForDisplay);
        const ownerGroups = {};
        groupItems.forEach(f => {
            const ownerKey = getSingleFactorOwnerSortKey(f);
            if (!ownerGroups[ownerKey]) ownerGroups[ownerKey] = [];
            ownerGroups[ownerKey].push(f);
        });

        html += `<div class="collapsible-factor-node collapsible-factor-group" data-factor-group="${escAttr(group)}">
            <button class="collapsible-factor-header" type="button">
                <span class="caret">▶</span>
                <span class="collapsible-factor-title">${escHtml(group)}</span>
                <span class="collapsible-factor-count">${groupItems.length}</span>
            </button>
            <div class="collapsible-factor-body">`;

        Object.keys(ownerGroups).sort().forEach(ownerKey => {
            const ownerItems = ownerGroups[ownerKey];
            html += `<div class="collapsible-factor-node collapsible-factor-owner" data-factor-owner="${escAttr(ownerKey)}">
                <button class="collapsible-factor-header" type="button">
                    <span class="caret">▶</span>
                    <span class="collapsible-factor-title">${escHtml(getSingleFactorOwnerLabel(ownerItems[0]))}</span>
                    <span class="collapsible-factor-count">${ownerItems.length}</span>
                </button>
                <div class="collapsible-factor-body">`;

            ownerItems.forEach(f => {
                const ownerUsername = f.owner_username || '';
                const active = (
                    f.id === _sftCurrentFactorId
                    && f.type === (_sftCurrentFactorType || 'public')
                    && (f.type === 'public' || ownerUsername === (_sftCurrentOwner || ''))
                ) ? ' active' : '';
                const name = f.name || f.id || '';
                const cn = f.chinese_name || '';
                const metaParts = [cn, f.type === 'custom' ? (f.category || '自编') : '公共'];
                if (f.type === 'custom' && f.owner_alias) {
                    metaParts.push(f.can_edit ? '我的因子' : `来自 ${f.owner_alias}`);
                }
                const sourceTag = f.type === 'custom'
                    ? `<span class="source-tag custom">${f.can_edit ? '我' : escHtml(f.owner_alias || '下级')}</span>`
                    : '<span class="source-tag public">公共</span>';
                html += `<div class="factor-family-list-item${active}"
                    data-factor-id="${escAttr(f.id)}"
                    data-factor-type="${escAttr(f.type)}"
                    data-factor-owner-username="${escAttr(ownerUsername)}"
                    onclick="selectSingleFactorFamily('${escAttr(f.id)}', '${escAttr(f.type)}', '${escAttr(ownerUsername)}')">
                    <div class="info">
                        <div class="name">${escHtml(name)}${sourceTag}</div>
                        <div class="meta">${metaParts.filter(Boolean).map(escHtml).join(' · ')}</div>
                    </div>
                </div>`;
            });

            html += '</div></div>';
        });

        html += '</div></div>';
    });

    list.innerHTML = html;
    if (typeof bindCollapsibleFactorLists === 'function') bindCollapsibleFactorLists(list);
    expandCurrentSingleFactorInNav();
}

async function selectSingleFactorFamily(factorId, factorType, ownerUsername, options = {}) {
    const prevFactorId = _sftCurrentFactorId || '';
    _sftCurrentFactorId = factorId || '';
    _sftCurrentFactorType = factorType || 'public';
    _sftCurrentOwner = ownerUsername || '';
    await window.SingleFactorResearch.ensureWorkspace(_sftCurrentFactorId);
    renderSingleFactorFamilyList();

    const body = document.getElementById('editor-body');
    const title = document.getElementById('editor-title');
    const factor = findSingleFactorFamily(factorId, factorType, ownerUsername);
    const displayName = factor?.chinese_name || factor?.name || factorId || '因子家族';
    if (title) {
        const typeLabel = _sftCurrentFactorType === 'custom' ? '自定义因子' : '公共因子';
        const owner = factor?.owner_alias && _sftCurrentFactorType === 'custom' ? ` / ${factor.owner_alias}` : '';
        title.textContent = `${displayName}（${typeLabel}${owner}）`;
    }
    document.title = displayName + ' - 单因子测试';
    if (body) body.innerHTML = '<div class="single-factor-loading">正在加载测试模块...</div>';

    const params = new URLSearchParams();
    params.set('factor', factorId || '');
    params.set('type', _sftCurrentFactorType);
    if (_sftCurrentOwner) params.set('owner_username', _sftCurrentOwner);
    if (window._pageUuid) params.set('page_uuid', window._pageUuid);

    try {
        const res = await fetch('/single_factor_test/api/content?' + params.toString());
        const data = await res.json();
        if (!data.success) throw new Error(data.error || '加载失败');
        await replaceSingleFactorContent(data.html || '');
        await window.SingleFactorResearch.restoreActiveJobs();
        updateSingleFactorHistory(options.replaceHistory);
        expandCurrentSingleFactorInNav();
    } catch (e) {
        if (body) body.innerHTML = `<div class="editor-placeholder" style="color:#d40000;">加载失败: ${escHtml(e.message || e)}</div>`;
    }
}

async function replaceSingleFactorContent(html) {
    const body = document.getElementById('editor-body');
    if (!body) return;
    body.innerHTML = html || '<div class="editor-placeholder">暂无内容</div>';
    await executeScriptsIn(body);
    if (window.MathJax?.typesetPromise) {
        const mathBlocks = Array.from(body.querySelectorAll('#latex-math-block, #pm-math-block, #cfe-math-block, #readonly-math-block'));
        if (mathBlocks.length) MathJax.typesetPromise(mathBlocks).catch(function() {});
    }
}

window.reloadSingleFactorContent = async function(callback) {
    const params = new URLSearchParams();
    params.set('factor', _sftCurrentFactorId || '');
    params.set('type', _sftCurrentFactorType || 'public');
    if (_sftCurrentOwner) params.set('owner_username', _sftCurrentOwner);
    if (window._pageUuid) params.set('page_uuid', window._pageUuid);
    const res = await fetch('/single_factor_test/api/content?' + params.toString());
    const data = await res.json();
    if (data.success) {
        await replaceSingleFactorContent(data.html || '');
        if (typeof callback === 'function') callback();
    }
};

async function executeScriptsIn(root) {
    const scripts = Array.from(root.querySelectorAll('script'));
    for (const oldScript of scripts) {
        const newScript = document.createElement('script');
        Array.from(oldScript.attributes).forEach(attr => newScript.setAttribute(attr.name, attr.value));
        if (oldScript.src) {
            await loadExternalScript(oldScript.src);
        } else {
            newScript.textContent = oldScript.textContent || '';
            document.body.appendChild(newScript);
            newScript.remove();
        }
        oldScript.remove();
    }
    root.querySelectorAll('link[rel="stylesheet"]').forEach(link => {
        const href = link.getAttribute('href');
        const exists = href && Array.from(document.querySelectorAll('head link[rel="stylesheet"]'))
            .some(existing => existing.getAttribute('href') === href);
        if (href && !exists) {
            document.head.appendChild(link.cloneNode(true));
        }
        link.remove();
    });
}

function loadExternalScript(src) {
    return new Promise((resolve, reject) => {
        const normalized = String(src || '');
        const isHighchartsVendor = normalized.includes('/vendor/highcharts/') || normalized.includes('code.highcharts.com/');
        if (isHighchartsVendor && window.Highcharts) {
            resolve();
            return;
        }
        const script = document.createElement('script');
        script.src = src;
        script.onload = function() { script.remove(); resolve(); };
        script.onerror = function() {
            script.remove();
            reject(new Error('Failed to load script: ' + src));
        };
        document.body.appendChild(script);
    });
}

function updateSingleFactorHistory(replaceHistory) {
    const params = new URLSearchParams();
    const filter = document.getElementById('factor-family-filter')?.value || '';
    const includeSubordinates = document.getElementById('include-subordinate-factors')?.checked;
    if (filter.trim()) params.set('search', filter.trim());
    if (includeSubordinates) params.set('include_subordinates', '1');
    if (_sftCurrentFactorId) params.set('factor', _sftCurrentFactorId);
    if (_sftCurrentFactorType === 'custom') params.set('type', 'custom');
    if (_sftCurrentOwner) params.set('owner_username', _sftCurrentOwner);
    const url = '/single_factor_test' + (params.toString() ? '?' + params.toString() : '');
    const state = {factor: _sftCurrentFactorId, type: _sftCurrentFactorType, owner: _sftCurrentOwner};
    if (replaceHistory) history.replaceState(state, '', url);
    else history.pushState(state, '', url);
}

window.addEventListener('popstate', function(e) {
    const params = new URLSearchParams(window.location.search);
    const factor = params.get('factor') || '';
    if (!factor) return;
    selectSingleFactorFamily(factor, params.get('type') || 'public', params.get('owner_username') || '', {replaceHistory: true});
});

function findSingleFactorFamily(factorId, factorType, ownerUsername) {
    return _sftFactorFamilies.find(f => {
        if (f.id !== factorId || f.type !== factorType) return false;
        if (factorType === 'public') return true;
        return (f.owner_username || '') === (ownerUsername || '');
    });
}

function expandCurrentSingleFactorInNav() {
    if (!_sftCurrentFactorId) return;
    const list = document.getElementById('factor-family-list');
    if (!list) return;
    const selector = `.factor-family-list-item[data-factor-id="${cssEscape(_sftCurrentFactorId)}"][data-factor-type="${cssEscape(_sftCurrentFactorType || 'public')}"]`;
    const candidates = [...list.querySelectorAll(selector)];
    const item = candidates.find(el => {
        if ((_sftCurrentFactorType || 'public') === 'public') return true;
        return (el.dataset.factorOwnerUsername || '') === (_sftCurrentOwner || '');
    });
    if (!item) return;
    let node = item.parentElement;
    while (node && node !== list) {
        if (node.classList?.contains('collapsible-factor-node')) {
            node.classList.add('open');
            const body = node.querySelector(':scope > .collapsible-factor-body');
            if (body) body.style.removeProperty('display');
        }
        node = node.parentElement;
    }
    requestAnimationFrame(() => item.scrollIntoView({block: 'nearest'}));
}

function initSingleFactorSidebarResizer() {
    const resizer = document.getElementById('sidebar-resizer');
    const sidebar = document.querySelector('.single-factor-app .sidebar');
    const app = document.querySelector('.single-factor-app');
    if (!resizer || !sidebar || !app) return;
    let dragging = false;
    resizer.addEventListener('mousedown', function(e) {
        dragging = true;
        document.body.style.cursor = 'col-resize';
        e.preventDefault();
    });
    document.addEventListener('mousemove', function(e) {
        if (!dragging) return;
        const width = Math.max(260, Math.min(520, e.clientX));
        sidebar.style.width = width + 'px';
        app.style.gridTemplateColumns = `${width}px 8px minmax(0, 1fr)`;
    });
    document.addEventListener('mouseup', function() {
        if (!dragging) return;
        dragging = false;
        document.body.style.cursor = '';
    });
}

/** Sidebar 折叠/展开 — issue #107 */
const SIDEBAR_STORAGE_KEY = 'ft:singlefactor:sidebar-expanded';

function initSingleFactorSidebarToggle() {
    var app = document.querySelector('.single-factor-app');
    var collapseBtn = document.getElementById('sidebar-collapse-btn');   // 内嵌 ❮ 按钮
    var expandBtn = document.getElementById('sidebar-expand-btn');       // 内嵌 ☰ 按钮
    var overlay = document.getElementById('sidebar-overlay');
    if (!app) return;

    var expanded = getSidebarExpanded();

    function applyState(state) {
        if (state) {
            app.classList.remove('sidebar-collapsed');
            app.classList.add('sidebar-expanded');
        } else {
            app.classList.add('sidebar-collapsed');
            app.classList.remove('sidebar-expanded');
        }
    }

    function collapse() { expanded = false; setSidebarExpanded(false); applyState(false); }
    function expand()   { expanded = true;  setSidebarExpanded(true);  applyState(true); }

    // 内嵌折叠按钮（宽屏 sidebar 内的 ❮）
    if (collapseBtn) collapseBtn.addEventListener('click', collapse);
    // 内嵌展开按钮（sidebar 隐藏后出现在 editor-header 的 ☰）
    if (expandBtn) expandBtn.addEventListener('click', expand);
    // overlay（手机模式关闭）
    if (overlay) overlay.addEventListener('click', collapse);

    // 初始状态
    applyState(expanded);
}

function getSidebarExpanded() {
    try {
        var v = localStorage.getItem(SIDEBAR_STORAGE_KEY);
        if (v === null) return true; // 默认展开
        return v === '1';
    } catch(e) {
        return true;
    }
}

function setSidebarExpanded(v) {
    try {
        localStorage.setItem(SIDEBAR_STORAGE_KEY, v ? '1' : '0');
    } catch(e) {}
}

function getSingleFactorOwnerSortKey(f) {
    if (f.type === 'public') return '公共';
    return `${f.owner_organization_name || f.owner_organization_id || '未分机构'}/${f.owner_alias || f.owner_username || '未知用户'}`;
}

function getSingleFactorOwnerLabel(f) {
    if (f.type === 'public') return '公共';
    if (f.can_edit) return '我的因子';
    return `${f.owner_organization_name || f.owner_organization_id || '未分机构'} / ${f.owner_alias || f.owner_username || '未知用户'}`;
}

function compareSingleFactorFamiliesForDisplay(a, b) {
    return (
        getSingleFactorGroup(a.name || a.id).localeCompare(getSingleFactorGroup(b.name || b.id)) ||
        getSingleFactorOwnerSortKey(a).localeCompare(getSingleFactorOwnerSortKey(b)) ||
        (a.name || a.id || '').localeCompare(b.name || b.id || '')
    );
}

function escHtml(s) {
    const d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
}

function escAttr(s) {
    return String(s || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function cssEscape(value) {
    if (window.CSS?.escape) return CSS.escape(String(value || ''));
    return String(value || '').replace(/["\\]/g, '\\$&');
}
