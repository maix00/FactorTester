/**
 * registry/tabs.js — Tab 管理系统（模式→UI 编排）
 *
 * 职责：
 *   - 面板注册表（GT_PANEL_REGISTRY）：提供 registerPanel() 让外部注册面板
 *   - Tab 切换（mountTab）
 *   - 操作按钮渲染（泛型，通过 modes 的 editActions + addFlowMeta 动态生成）
 *   - 模式编排：enterAddMode / exitAddMode / enterEditMode / exitEditMode
 *
 * 设计原则：
 *   - tabs.js 不硬编码任何具体 addFlow（如 group/derived/ls）
 *   - 按钮通过 modes.getMatchingEditActions() 和 modes.getActiveFlowMeta() 动态生成
 *   - 面板通过 registerPanel() 注册，不在此文件中硬编码
 *
 * 依赖：
 *   - GT.modes               — 模式管理 (registry/modes.js)
 *   - GT.panels.*            — 各面板实现（由各自文件注册面板）
 *   - GT.groupSettings.*     — 分组设置
 *
 * 挂载到 GT.tabs。
 */
(function(){
    var GT = window.GroupTest;
    if (!GT) { console.warn('[tabs] bootstrap missing'); return; }
    if (GT.tabs) { console.warn('[tabs] already loaded'); return; }

    var M = GT.modes;
    if (!M) throw new Error('[tabs] registry/modes must be loaded before registry/tabs');

    // ═══ Tab category constants ═══
    var TAB_CATEGORY = {
        LIST: 1,
        ADD: 2,
        CONFIG: 3,
    };

    var GT_PANEL_REGISTRY = [];
    var _currentPanel = null;
    var _currentTab = 'list';

    // ── 面板注册 API ──

    /**
     * 注册面板
     * @param {Object} def
     *   - name: string       — 唯一名称
     *   - label: string      — tab 标签
     *   - containerId: string — DOM 容器 ID
     *   - category: number   — TAB_CATEGORY 值
     *   - panel: object      — 面板实例（有 mount/unmount）
     *   - visible: function() — 返回 true 表示可见（可选）
     *   - onBeforeMount: function() — mount 前回调（可选）
     */
    function registerPanel(def) {
        if (!def || !def.name) { console.warn('[tabs] registerPanel: missing name'); return; }
        // 去重
        for (var i = 0; i < GT_PANEL_REGISTRY.length; i++) {
            if (GT_PANEL_REGISTRY[i].name === def.name) {
                GT_PANEL_REGISTRY[i] = def;
                return;
            }
        }
        GT_PANEL_REGISTRY.push(def);
    }

    // ── unmount ──
    function _unmountCurrent() {
        if (_currentPanel && typeof _currentPanel.unmount === 'function') {
            _currentPanel.unmount();
        }
        _currentPanel = null;
        var tabBtnsBar = document.getElementById('gt-tab-btns');
        var panelContainer = document.getElementById('gt-panel-container');
        if (tabBtnsBar) tabBtnsBar.innerHTML = '';
        if (panelContainer) panelContainer.innerHTML = '';
    }

    // ── section status ──
    function _renderSectionStatus() {
        var el = document.getElementById('gt-section-status');
        if (!el) return;
        if (M.isMode('edit')) {
            var REG = window.GT_CONFIG_REGISTRY;
            var hasDirty = REG ? REG.hasDirty() : false;
            el.style.display = '';
            el.style.color = hasDirty ? '#e65100' : '#888';
            el.textContent = hasDirty ? '编辑中 - 未保存' : '编辑中';
        } else if (M.isMode('add')) {
            el.style.display = '';
            el.style.color = '#1565c0';
            el.textContent = '新建中';
        } else {
            el.style.display = 'none';
            el.textContent = '';
        }
    }

    // ── action buttons（泛型） ──

    /** mousedown 触发前先让当前聚焦元素 blur，确保输入值已写入 dirty workspace */
    function _flushFocusedInput() {
        var ae = document.activeElement;
        if (ae && ae !== document.body && ae.blur) { ae.blur(); }
    }

    function _bindActionButtons() {
        // 清除旧绑定
        var bar = document.getElementById('gt-tab-actions');
        if (!bar) return;

        // list 模式按钮（非交互式 focus 场景，click 即可）
        var addGroupBtn = document.getElementById('gt-action-add-group');
        if (addGroupBtn) addGroupBtn.addEventListener('click', function() { _enterAddMode('group'); });

        var addLSBtn = document.getElementById('gt-action-add-ls');
        if (addLSBtn) addLSBtn.addEventListener('click', function() { _enterAddMode('ls'); });

        // 取消按钮 — mousedown 后直接退出，无需等 blur 刷新
        var cancelBtn = document.getElementById('gt-action-cancel');
        if (cancelBtn) cancelBtn.addEventListener('mousedown', function(e) { e.preventDefault(); _exitAddMode(); });

        // 提交/保存 — mousedown 先 blur 聚焦输入框，等 blur 回调执行后再提交
        var submitBtn = document.getElementById('gt-action-submit');
        if (submitBtn) submitBtn.addEventListener('mousedown', function(e) {
            e.preventDefault();
            _flushFocusedInput();
            setTimeout(_submitAddDraft, 0);
        });

        var saveBtn = document.getElementById('gt-action-save');
        if (saveBtn) saveBtn.addEventListener('mousedown', function(e) {
            e.preventDefault();
            _flushFocusedInput();
            setTimeout(_saveEditChanges, 0);
        });

        // edit actions（动态注册的）
        var actions = M.getMatchingEditActions();
        for (var i = 0; i < actions.length; i++) {
            (function(act) {
                var btn = document.getElementById('gt-action-edit-' + act.name);
                if (!btn) return;
                btn.addEventListener('click', function() {
                    if (typeof act.action === 'function') {
                        act.action(M.getEditContext(), {
                            exitEdit: _exitEditMode,
                            enterAdd: _enterAddMode,
                            setDraft: M.setAddDraft,
                            mountTab: mountTab,
                            renderActions: _renderTabActions
                        });
                    }
                });
            })(actions[i]);
        }
    }

    function _renderTabActions() {
        var bar = document.getElementById('gt-tab-actions');
        if (!bar) return;
        var html = '';
        var d = M.getAddDraft();
        function iconButton(id, title, innerHtml, cls, extraStyle) {
            return '<button id="' + id + '" class="btn btn-sm ' + (cls || 'btn-primary') + '" title="' + title + '" aria-label="' + title + '" style="padding:4px 10px;font-size:12px;line-height:1;display:inline-flex;align-items:center;justify-content:center;min-width:30px;' + (extraStyle || '') + '">' + innerHtml + '</button>';
        }

        if (M.isMode('add')) {
            // 泛型提交按钮
            var meta = M.getActiveFlowMeta();
            var submitLabel = (meta && meta.submitLabel) || '提交';
            var submitTitle = (meta && meta.submitTitle) || String(submitLabel).replace(/<[^>]+>/g, '') || '提交';
            html += iconButton('gt-action-submit', submitTitle, submitLabel, 'btn-primary', '');
            html += ' ' + iconButton('gt-action-cancel', '取消新建', '<i class="fas fa-times"></i>', 'btn-outline-secondary', '');

        } else if (M.isMode('edit')) {
            // 动态 edit actions（仅非 config tab 时显示 standalone=false 的按钮）
            var actions = M.getMatchingEditActions();
            var isConfigTab = _currentTab && _currentTab.indexOf('config-') === 0;
            for (var i = 0; i < actions.length; i++) {
                var act = actions[i];
                if (isConfigTab && !act.standalone) continue;
                var cls = act.buttonClass || 'btn-primary';
                html += iconButton('gt-action-edit-' + act.name, act.title || act.label || act.name, act.label, cls, act.style || '');
            }
            html += ' ' + iconButton('gt-action-save', '保存修改', '<i class="fas fa-save"></i>', 'btn-primary', '');

        } else {
            // list 模式 — 固定显示「新增分组」
            html += iconButton('gt-action-add-group', '新增分组', '<i class="fas fa-plus"></i>', 'btn-primary', '');
        }

        bar.innerHTML = html;
        _bindActionButtons();
        _renderSectionStatus();
    }

    // ── 模式切换 ──

    function _enterAddMode(addFlow) {
        M.enterAdd(addFlow);
        _renderTabActions();

        // 找该 flow 的默认 tab，否则找第一个可见的 ADD 类 tab
        var defaultTab = M.getDefaultTab();
        if (defaultTab) {
            mountTab(defaultTab);
        } else {
            var vc = _visibleCategories();
            var firstAdd = null;
            for (var i = 0; i < GT_PANEL_REGISTRY.length; i++) {
                var p = GT_PANEL_REGISTRY[i];
                if (vc.indexOf(p.category) >= 0 && p.category === TAB_CATEGORY.ADD) {
                    if (typeof p.visible !== 'function' || p.visible()) {
                        firstAdd = p.name;
                        break;
                    }
                }
            }
            if (firstAdd) mountTab(firstAdd);
        }
    }

    function _exitAddMode() {
        M.exitAdd();
        _renderTabActions();
        mountTab('list');
    }

    function _submitAddDraft() {
        var d = M.getAddDraft();
        if (!d) { alert('草稿丢失'); return; }

        var REG = window.GT_CONFIG_REGISTRY;
        if (REG && typeof REG.commitDirty === 'function') {
            try { REG.commitDirty(); } catch(e) {}
        }

        var onSubmit = M.getOnSubmit();
        if (typeof onSubmit === 'function') {
            onSubmit(d, { exitAdd: _exitAddMode });
        } else {
            console.warn('[tabs] active add flow has no onSubmit handler:', M.getActiveFlow());
            _exitAddMode();
        }
    }

    function _enterEditMode(selection) {
        var REG = window.GT_CONFIG_REGISTRY;
        if (REG) REG.rollbackDirty();
        M.enterEdit(selection);
        _currentTab = 'list';
        _renderTabActions();
        _renderTabBar();
        mountTab('list');
    }

    function _exitEditMode() {
        M.exitEdit();
        _renderTabActions();
        _renderTabBar();
        mountTab('list');
    }

    function _saveEditChanges() {
        var REG = window.GT_CONFIG_REGISTRY;
        if (REG) REG.commitDirty();
        M.exitEdit();
        _renderTabActions();
        _renderTabBar();
        mountTab('list');
    }

    // ── Tab 可见性 ──

    function _visibleCategories() {
        if (M.isMode('list')) return [TAB_CATEGORY.LIST];
        if (M.isMode('edit')) return [TAB_CATEGORY.LIST, TAB_CATEGORY.CONFIG];
        if (M.isMode('add')) return [TAB_CATEGORY.ADD, TAB_CATEGORY.CONFIG];
        return [TAB_CATEGORY.LIST];
    }

    function _renderTabBar() {
        var tabBtnsBar = document.getElementById('gt-tab-btns');
        if (!tabBtnsBar) return;
        var vc = _visibleCategories();
        var visibleList = GT_PANEL_REGISTRY.filter(function(p) {
            if (vc.indexOf(p.category) < 0) return false;
            if (typeof p.visible === 'function' && !p.visible()) return false;
            return true;
        });
        if (visibleList.length < 1) { tabBtnsBar.innerHTML = ''; return; }
        var stHtml = '';
        for (var i = 0; i < visibleList.length; i++) {
            var p = visibleList[i];
            stHtml += '<button class="gt-tab' + (p.name === _currentTab ? ' active' : '') + '" data-tab="' + p.name + '">' + p.label + '</button>';
        }
        tabBtnsBar.innerHTML = stHtml;
        tabBtnsBar.querySelectorAll('.gt-tab').forEach(function(st) {
            st.addEventListener('click', function() { mountTab(st.getAttribute('data-tab')); });
        });
    }

    // ═══ 核心 Tab 切换 ═══

    function mountTab(tabName) {
        _unmountCurrent();
        _currentTab = tabName;

        var vc = _visibleCategories();
        var visibleList = GT_PANEL_REGISTRY.filter(function(p) {
            if (vc.indexOf(p.category) < 0) return false;
            if (typeof p.visible === 'function' && !p.visible()) return false;
            return true;
        });

        var entry = visibleList.find(function(p) { return p.name === tabName; });
        if (!entry) return;
        if (typeof entry.onBeforeMount === 'function') { entry.onBeforeMount(); }

        _renderTabBar();

        var panelContainer = document.getElementById('gt-panel-container');
        if (panelContainer) {
            panelContainer.innerHTML = '<div id="' + entry.containerId + '" class="gt-panel-inner"></div>';
        }
        if (entry.panel && typeof entry.panel.mount === 'function') {
            var containerEl = document.getElementById(entry.containerId);
            if (containerEl) {
                entry.panel.mount(containerEl);
                _currentPanel = entry.panel;
            } else {
                console.warn('mountTab: container #' + entry.containerId + ' not found for tab ' + tabName);
            }
        }
        _renderTabActions();
    }

    // ═══ 初始化 — 注册基础面板 ═══

    function _registerBuiltinPanels() {
        var P = GT.panels;
        if (!P) return;

        if (P.list && P.list.index) {
            registerPanel({
                name: 'list', label: '📊 分组列表', containerId: 'unified-group-list',
                category: TAB_CATEGORY.LIST, panel: P.list.index
            });
        }
        if (P.add && P.add.group) {
            registerPanel({
                name: 'add-group', label: '新建分组', containerId: 'add-group',
                category: TAB_CATEGORY.ADD, panel: P.add.group,
                visible: function() { return M.isAddFlow('group'); }
            });
        }
        // add-ls panel removed — LS creation is now direct via edit action (refs #109)
        if (P.config && P.config.fee) {
            registerPanel({
                name: 'fee', label: '手续费', containerId: 'config-fee',
                category: TAB_CATEGORY.CONFIG, panel: P.config.fee
            });
        }
        if (P.config && P.config.rebalance) {
            registerPanel({
                name: 'rebalance', label: '⚖️ 再平衡', containerId: 'config-rebalance',
                category: TAB_CATEGORY.CONFIG, panel: P.config.rebalance
            });
        }
        if (P.config && P.config.liquidity) {
            registerPanel({
                name: 'liquidity', label: '💧 流动性', containerId: 'config-liquidity',
                category: TAB_CATEGORY.CONFIG, panel: P.config.liquidity
            });
        }
        if (P.config && P.config.productSift) {
            registerPanel({
                name: 'config-product-sift', label: '🌾 品种筛选', containerId: 'config-product-sift',
                category: TAB_CATEGORY.CONFIG, panel: P.config.productSift
            });
        }
    }

    function init() {
        _registerBuiltinPanels();
        mountTab('list');
    }

    // ═══ 导出 ═══

    GT.tabs = {
        init: init,
        mountTab: mountTab,
        registerPanel: registerPanel,
        getPanelMode: function() { return M.getMode(); },
        getAddDraft: function() { return M.getAddDraft(); },
        updateAddDraft: function(patch) { M.updateAddDraft(patch); },
        getEditSelection: function() { return M.getEditSelection(); },
        enterEditMode: _enterEditMode,
        exitEditMode: _exitEditMode,
        enterAddMode: _enterAddMode,
        exitAddMode: _exitAddMode,
        renderTabActions: _renderTabActions,
        refreshTabBar: _renderTabBar,
        _selectedEditIds: function() { return M.getEditIds(); },
    };

    // ═══════════════════════════════════════════════════════════════
    // 通用编辑操作（删除 / 复制）
    // ═══════════════════════════════════════════════════════════════

    // ── 批量删除 ──
    M.registerEditAction({
        name: 'delete',
        label: '<span style="color:#d40000;font-weight:700;font-size:16px;line-height:1;">&times;</span>',
        title: '删除',
        priority: 50,
        condition: function(ctx) { return ctx.count > 0; },
        buttonClass: 'btn-outline-danger',
        style: 'background:#fff5f5;border-color:#f3b0b0;color:#d40000;',
        action: function(ctx, helpers) {
            var ids = ctx.ids;
            if (ids.length === 0) return;
            try {
                for (var i = 0; i < ids.length; i++) {
                    GT.groupSettings.groups.remove(ids[i]);
                }
            } catch (err) { alert('删除失败: ' + err.message); }
            helpers.exitEdit();
        }
    });

    // ── 复制（派生组） ──
    M.registerEditAction({
        name: 'clone',
        label: '<i class="fas fa-copy"></i>',
        title: '复制为派生组',
        priority: 40,
        condition: function(ctx) { return ctx.count > 0; },
        action: function(ctx, helpers) {
            var groups = GT.groupSettings.groups;
            var ids = ctx.ids;
            var created = [];
            for (var i = 0; i < ids.length; i++) {
                var src = groups.get(ids[i]);
                if (!src) continue;
                var parent = src.parentId ? groups.get(src.parentId) : src;
                if (!parent) continue;
                var clone = {
                    name: '',
                    parentId: src.id,
                    splitCount: src.splitCount || (parent && parent.splitCount) || 1,
                    groupIndex: src.groupIndex || (parent && parent.groupIndex) || 1,
                    productMask: src.productMask ? JSON.parse(JSON.stringify(src.productMask)) : {},
                };
                ['feeMode', 'feeRate', 'feeMap', 'feeSensitivity', 'useCloseToday',
                 'rebalanceMode', 'liquidityMode', 'liquidityPercent'].forEach(function(key) {
                    if (src[key] !== undefined && src[key] !== null) {
                        clone[key] = (typeof src[key] === 'object') ? JSON.parse(JSON.stringify(src[key])) : src[key];
                    }
                });
                try {
                    var newId = groups.add(clone);
                    created.push(newId);
                } catch (err) {
                    alert('复制失败: ' + (err && err.message || err));
                    break;
                }
            }
            if (created.length > 0) {
                // 选中新创建的派生组
                var sel = GT.panels && GT.panels.list && GT.panels.list.selection;
                if (sel) {
                    sel.clear();
                    for (var j = 0; j < created.length; j++) { sel.add(created[j]); }
                }
                if (GT.events && GT.events.emit) GT.events.emit('derivedGraphChanged');
            }
            helpers.exitEdit();
        }
    });

    GT.log('registry/tabs loaded');
})();
