let _sftFactorFamilies = [];
let _sftGroupedFactorFamilies = {};
let _sftCurrentFactorId = '';
let _sftCurrentFactorType = 'public';
let _sftCurrentOwner = '';

document.addEventListener('DOMContentLoaded', function() {
    initSingleFactorShell();
});

async function initSingleFactorShell() {
    initSingleFactorSidebarResizer();
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
    _sftCurrentFactorId = factorId || '';
    _sftCurrentFactorType = factorType || 'public';
    _sftCurrentOwner = ownerUsername || '';
    renderSingleFactorFamilyList();

    const body = document.getElementById('editor-body');
    const title = document.getElementById('editor-title');
    const factor = findSingleFactorFamily(factorId, factorType, ownerUsername);
    if (title) {
        const label = factor?.name || factorId || '因子家族';
        const typeLabel = _sftCurrentFactorType === 'custom' ? '自定义因子' : '公共因子';
        const owner = factor?.owner_alias && _sftCurrentFactorType === 'custom' ? ` / ${factor.owner_alias}` : '';
        title.textContent = `${label}（${typeLabel}${owner}）`;
    }
    if (body) body.innerHTML = '<div class="single-factor-loading">正在加载测试模块...</div>';

    const params = new URLSearchParams();
    params.set('factor', factorId || '');
    params.set('type', _sftCurrentFactorType);
    if (_sftCurrentOwner) params.set('owner_username', _sftCurrentOwner);

    try {
        const res = await fetch('/single_factor_test/api/content?' + params.toString());
        const data = await res.json();
        if (!data.success) throw new Error(data.error || '加载失败');
        await replaceSingleFactorContent(data.html || '');
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
    return new Promise(resolve => {
        const script = document.createElement('script');
        script.src = src;
        script.onload = function() { script.remove(); resolve(); };
        script.onerror = function() { script.remove(); resolve(); };
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
