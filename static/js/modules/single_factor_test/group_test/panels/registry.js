/**
 * panels/registry.js — 面板注册与 Tab 管理系统
 *
 * 从 app.js 解耦提取。
 * 管理面板注册表、Tab 切换、编辑/添加模式等 UI 编排逻辑。
 * 挂载到 GT.panels.registry 命名空间。
 *
 * 依赖（通过 GT.* 访问）：
 *   - GT.panels.*           — 各面板实现
 *   - GT.datamodel.*         — 数据模型
 *   - GT.state               — 状态管理
 *   - GT.fee                 — 费用模块
 *   - GT_CONFIG_REGISTRY     — 窗口全局
 *
 * 对外暴露：
 *   - GT.panels.registry.init()     — 初始化
 *   - mountTab(tabName)             — 切换 Tab
 *   - registerPanels()              — 注册所有面板
 */
(function(){
    var GT = window.GroupTest;
    if (!GT) { console.warn('[GT panels/registry] bootstrap missing'); return; }
    GT.panels = GT.panels || {};
    if (GT.panels.registry) { console.warn('[GT panels/registry] already loaded'); return; }

    // ═══ Tab category constants ═══
    var GT_TAB_CATEGORY = {
        LIST: 1,
        ADD: 2,
        CONFIG: 3,
    };

    var GT_PANEL_REGISTRY = [];
    var _panelsRegistered = false;

    // ═══ 内部状态 ═══
    var _currentPanel = null;
    var _currentTab = 'list';
    var _panelMode = 'list';  // 'list' | 'add' | 'edit'
    var _addDraft = null;
    var _editSelection = null;

    // ── 辅助函数 ──
    function _selectedEditIds() {
        if (_editSelection && _editSelection instanceof Set) return Array.from(_editSelection);
        if (_editSelection && Array.isArray(_editSelection)) return _editSelection.slice();
        if (_editSelection && typeof _editSelection === 'object') {
            return Object.keys(_editSelection).filter(function(k) { return _editSelection[k]; });
        }
        return [];
    }

    function _resolvedConfigForDraft(group) {
        var base = null;
        if (group && group.isDerived && group.baseGroupId && GT.datamodel && GT.datamodel.groups) {
            base = GT.datamodel.groups.get(group.baseGroupId);
        }
        var resolvedFee = null;
        if (group && group.isDerived && GT.datamodel && GT.datamodel.fee_strategy) {
            try { resolvedFee = GT.datamodel.fee_strategy.resolveFee(group.id); } catch (e) { resolvedFee = null; }
        }
        return {
            feeMode: resolvedFee ? (resolvedFee.mode || 'none') : (group && group.feeMode != null ? group.feeMode : (base && base.feeMode != null ? base.feeMode : 'none')),
            feeRate: resolvedFee ? resolvedFee.rate : (group && group.feeRate != null ? group.feeRate : (base ? base.feeRate : null)),
            feeMap: resolvedFee ? resolvedFee.feeMap : (group && group.feeMap != null ? group.feeMap : (base ? base.feeMap : null)),
            feeSensitivity: resolvedFee && resolvedFee.sensitivity !== undefined ? resolvedFee.sensitivity : (group && group.feeSensitivity != null ? group.feeSensitivity : (base && base.feeSensitivity != null ? base.feeSensitivity : 1)),
            useCloseToday: group && group.useCloseToday != null ? !!group.useCloseToday : !!(base && base.useCloseToday),
            rebalanceMode: group && group.rebalanceMode != null ? group.rebalanceMode : (base && base.rebalanceMode ? base.rebalanceMode : 'each_period'),
            liquidityMode: group && group.liquidityMode != null ? group.liquidityMode : (base && base.liquidityMode ? base.liquidityMode : 'infinite'),
            liquidityPercent: group && group.liquidityPercent != null ? group.liquidityPercent : (base && base.liquidityPercent != null ? base.liquidityPercent : 100)
        };
    }

    function _buildDerivedAddDraftFromSelection() {
        var ids = _selectedEditIds();
        if (ids.length !== 1 || !GT.datamodel || !GT.datamodel.groups) return { addFlow: 'derived' };
        var selected = GT.datamodel.groups.get(ids[0]);
        if (!selected) return { addFlow: 'derived' };
        var draft = { addFlow: 'derived' };
        if (selected.isDerived) {
            draft.preselectedParentDerivedId = selected.id;
            draft.preselectedBaseGroupId = selected.baseGroupId;
            var parentMask = selected.productMask || {};
            var hasOwnMask = Object.keys(parentMask).length > 0;
            if (hasOwnMask) {
                draft.preselectedProducts = Object.keys(parentMask).filter(function(k) { return parentMask[k]; });
            }
        } else {
            draft.preselectedBaseGroupId = selected.id;
        }
        var cfg = _resolvedConfigForDraft(selected);
        Object.assign(draft, cfg);
        draft._inheritedConfigKeys = {};
        ['feeMode', 'feeRate', 'feeMap', 'feeSensitivity', 'useCloseToday', 'rebalanceMode', 'liquidityMode', 'liquidityPercent'].forEach(function(key) {
            draft._inheritedConfigKeys[key] = true;
        });
        return draft;
    }

    // ── 注册面板（懒加载） ──
    function _registerPanels() {
        if (_panelsRegistered) return;
        var P = GT.panels;
        if (!P) return;

        if (P.list && P.list.index) {
            GT_PANEL_REGISTRY.push({ name: 'list', label: '📊 分组列表', containerId: 'unified-group-list', category: GT_TAB_CATEGORY.LIST, panel: P.list.index });
        }
        if (P.add && P.add.base) {
            GT_PANEL_REGISTRY.push({ name: 'add-base', label: '新建基础组', containerId: 'add-base', category: GT_TAB_CATEGORY.ADD, panel: P.add.base, addFlow: 'base' });
        }
        if (P.config && P.config.derived) {
            GT_PANEL_REGISTRY.push({ name: 'config-derived', label: '品种筛选', containerId: 'config-derived', category: GT_TAB_CATEGORY.CONFIG, panel: P.config.derived });
        }
        if (P.add && P.add.ls) {
            GT_PANEL_REGISTRY.push({ name: 'add-ls', label: '新建 LS 组', containerId: 'add-ls', category: GT_TAB_CATEGORY.ADD, panel: P.add.ls, addFlow: 'ls' });
        }
        if (P.config && P.config.fee) {
            GT_PANEL_REGISTRY.push({ name: 'fee', label: '💰 手续费与平今', containerId: 'config-fee', category: GT_TAB_CATEGORY.CONFIG, panel: P.config.fee });
        }
        if (P.config && P.config.rebalance) {
            GT_PANEL_REGISTRY.push({ name: 'rebalance', label: '⚖️ 再平衡', containerId: 'config-rebalance', category: GT_TAB_CATEGORY.CONFIG, panel: P.config.rebalance });
        }
        if (P.config && P.config.liquidity) {
            GT_PANEL_REGISTRY.push({ name: 'liquidity', label: '💧 流动性', containerId: 'config-liquidity', category: GT_TAB_CATEGORY.CONFIG, panel: P.config.liquidity });
        }
        _panelsRegistered = true;
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

    // ── render section status ──
    function _renderSectionStatus() {
        var el = document.getElementById('gt-section-status');
        if (!el) return;
        if (_panelMode === 'edit') {
            var REG = window.GT_CONFIG_REGISTRY;
            var hasDirty = REG ? REG.hasDirty() : false;
            el.style.display = '';
            el.style.color = hasDirty ? '#e65100' : '#888';
            el.textContent = hasDirty ? '编辑中 - 未保存' : '编辑中';
        } else if (_panelMode === 'add') {
            el.style.display = '';
            el.style.color = '#1565c0';
            el.textContent = '新建中';
        } else {
            el.style.display = 'none';
            el.textContent = '';
        }
    }

    // ── action buttons ──
    function _bindActionButtons() {
        var addBaseBtn = document.getElementById('gt-action-add-base');
        if (addBaseBtn) addBaseBtn.addEventListener('click', function() { _enterAddMode('base'); });
        var addDerivedBtn = document.getElementById('gt-action-add-derived');
        if (addDerivedBtn) addDerivedBtn.addEventListener('click', function() { _enterAddMode('derived'); });
        var addLSBtn = document.getElementById('gt-action-add-ls');
        if (addLSBtn) addLSBtn.addEventListener('click', function() { _enterAddMode('ls'); });

        var submitBtn = document.getElementById('gt-action-submit');
        if (submitBtn) submitBtn.addEventListener('click', function() { _submitAddBatches(); });
        var submitDerivedBtn = document.getElementById('gt-action-submit-derived');
        if (submitDerivedBtn) submitDerivedBtn.addEventListener('click', function() { _submitAddDerivedGroup(); });
        var submitLSBtn = document.getElementById('gt-action-submit-ls');
        if (submitLSBtn) submitLSBtn.addEventListener('click', function() { _submitAddLSGroup(); });
        var cancelBtn = document.getElementById('gt-action-cancel');
        if (cancelBtn) cancelBtn.addEventListener('click', function() { _exitAddMode(); });

        var saveBtn = document.getElementById('gt-action-save');
        if (saveBtn) saveBtn.addEventListener('click', function() { _saveEditChanges(); });
        var cancelEditBtn = document.getElementById('gt-action-cancel-edit');
        if (cancelEditBtn) cancelEditBtn.addEventListener('click', function() { _exitEditMode(); });
        var createDerivedBtn = document.getElementById('gt-action-create-derived-from-selection');
        if (createDerivedBtn) createDerivedBtn.addEventListener('click', function() { _createDerivedFromSelection(); });
        var createLSBtn = document.getElementById('gt-action-create-ls-from-selection');
        if (createLSBtn) createLSBtn.addEventListener('click', function() { _createLSFromSelection(); });
    }

    function _renderTabActions() {
        var bar = document.getElementById('gt-tab-actions');
        if (!bar) return;
        var html = '';
        if (_panelMode === 'add') {
            if (_addDraft && _addDraft.addFlow === 'derived') {
                html += '<button id="gt-action-submit-derived" class="btn btn-primary btn-sm" style="padding:4px 12px;font-size:12px;">创建派生组</button>';
            } else if (_addDraft && _addDraft.addFlow === 'ls') {
                html += '<button id="gt-action-submit-ls" class="btn btn-primary btn-sm" style="padding:4px 12px;font-size:12px;">保存 LS 组</button>';
            } else {
                html += '<button id="gt-action-submit" class="btn btn-primary btn-sm" style="padding:4px 12px;font-size:12px;">提交基础组</button>';
            }
            html += '<button id="gt-action-cancel" class="btn btn-outline-secondary btn-sm" style="padding:4px 12px;font-size:12px;">取消新建</button>';
        } else if (_panelMode === 'edit') {
            var selIds = _selectedEditIds();
            var selCount = selIds.length;
            if (_currentTab !== 'config-derived') {
                if (selCount === 1) {
                    html += '<button id="gt-action-create-derived-from-selection" class="btn btn-primary btn-sm" style="padding:4px 12px;font-size:12px;">🌳 创建派生组</button>';
                } else if (selCount === 2) {
                    html += '<button id="gt-action-create-ls-from-selection" class="btn btn-primary btn-sm" style="padding:4px 12px;font-size:12px;">⚡ 创建 Long-Short 组</button>';
                }
            }
            html += '<button id="gt-action-save" class="btn btn-primary btn-sm" style="padding:4px 12px;font-size:12px;">保存修改</button>';
            html += '<button id="gt-action-cancel-edit" class="btn btn-outline-secondary btn-sm" style="padding:4px 12px;font-size:12px;">取消编辑</button>';
        } else {
            html += '<button id="gt-action-add-base" class="btn btn-primary btn-sm" style="padding:4px 12px;font-size:12px;">＋ 新增基础组</button>';
        }
        bar.innerHTML = html;
        _bindActionButtons();
        _renderSectionStatus();
    }

    // ── 模式切换 ──
    function _enterAddMode(addFlow) {
        _panelMode = 'add';
        _addDraft = { addFlow: addFlow };
        if (addFlow === 'base') {
            _addDraft.testerId = null;
            _addDraft.groupCount = 5;
            _addDraft.allGroups = true;
            _addDraft.groupIndex = 1;
            _addDraft.selectedFactors = [];
            _addDraft.feeMode = 'none';
            _addDraft.rebalanceMode = 'each_period';
            _addDraft.liquidityMode = 'infinite';
            _addDraft.liquidityPercent = 100;
            _renderTabActions();
            mountTab('add-base');
        } else if (addFlow === 'derived') {
            if (!_addDraft.preselectedBaseGroupId && !_addDraft.preselectedParentDerivedId) {
                var activeDerivedId = GT.state && GT.state.getActiveDerivedNodeId ? GT.state.getActiveDerivedNodeId() : null;
                if (activeDerivedId) {
                    _addDraft.preselectedParentDerivedId = activeDerivedId;
                    var activeDerived = GT.datamodel.groups && GT.datamodel.groups.get(activeDerivedId);
                    if (activeDerived) {
                        _addDraft.preselectedBaseGroupId = activeDerived.baseGroupId;
                        var effProdFn = GT.datamodel.groups && GT.datamodel.groups.effectiveProductNames;
                        _addDraft.preselectedProducts = (typeof effProdFn === 'function')
                            ? effProdFn(activeDerived)
                            : [];
                        Object.assign(_addDraft, _resolvedConfigForDraft(activeDerived));
                        _addDraft._inheritedConfigKeys = { feeMode: true, feeRate: true, feeMap: true, feeSensitivity: true, useCloseToday: true, rebalanceMode: true, liquidityMode: true, liquidityPercent: true };
                    }
                } else {
                    var activeBaseId = GT.state && GT.state.getActiveBaseGroupId ? GT.state.getActiveBaseGroupId() : null;
                    _addDraft.preselectedBaseGroupId = activeBaseId;
                    var activeBase = GT.datamodel.groups && GT.datamodel.groups.get(activeBaseId);
                    if (activeBase) {
                        Object.assign(_addDraft, _resolvedConfigForDraft(activeBase));
                        _addDraft._inheritedConfigKeys = { feeMode: true, feeRate: true, feeMap: true, feeSensitivity: true, useCloseToday: true, rebalanceMode: true, liquidityMode: true, liquidityPercent: true };
                    }
                }
            }
            _renderTabActions();
            mountTab('config-derived');
        } else if (addFlow === 'ls') {
            _renderTabActions();
            mountTab('add-ls');
        }
    }

    function _exitAddMode() {
        _panelMode = 'list';
        _addDraft = null;
        _renderTabActions();
        mountTab('list');
    }

    function _submitAddBatches() {
        if (!_addDraft || !_addDraft.testerId) { alert('请先选择测试器'); return; }
        if (_addDraft.groupCount < 1) { alert('分组数必须 ≥ 1'); return; }
        if (_addDraft.selectedFactors.length === 0) { alert('请至少选择一个因子'); return; }
        try {
            var REG = window.GT_CONFIG_REGISTRY;
            if (REG && typeof REG.commitDirty === 'function') REG.commitDirty();
            var addPanel = GT_PANEL_REGISTRY.find(function(p) { return p.name === 'add-base'; });
            if (addPanel && addPanel.panel && typeof addPanel.panel.submitAddBatches === 'function') {
                addPanel.panel.submitAddBatches(_addDraft);
            }
        } catch (err) {
            GT.log('_submitAddBatches error: ' + (err && err.message || err));
            alert('提交失败：' + (err && err.message || '未知错误'));
        } finally {
            _exitAddMode();
        }
    }

    function _submitAddDerivedGroup() {
        if (!_addDraft) { alert('提交草稿丢失'); return; }
        var baseGroupId = _addDraft.preselectedBaseGroupId;
        var parentDerivedId = _addDraft.preselectedParentDerivedId;
        if (!baseGroupId && !parentDerivedId) {
            alert('请先从列表中选择一个基础组或派生组作为上级');
            return;
        }
        if (!baseGroupId && parentDerivedId) {
            var pNode = GT.datamodel.groups && GT.datamodel.groups.get(parentDerivedId);
            if (pNode && pNode.isDerived) baseGroupId = pNode.baseGroupId;
            if (!baseGroupId) { alert('无法确定上级派生组关联的基础组'); return; }
        }
        var resolvedName = _addDraft.name || _addDraft.defaultName;
        if (!resolvedName || !resolvedName.trim()) {
            var bg = GT.datamodel.groups && GT.datamodel.groups.get(baseGroupId);
            resolvedName = (bg && (bg.shortAlias || bg.name)) || '派生组';
        }
        var derivedPanel = GT.panels.config && GT.panels.config.derived;
        var selectedProducts = (derivedPanel && typeof derivedPanel.getSelectedProducts === 'function')
            ? derivedPanel.getSelectedProducts() : [];
        var allProducts = (derivedPanel && typeof derivedPanel.getAllProducts === 'function')
            ? derivedPanel.getAllProducts() : [];
        var productMask = {};
        if (selectedProducts.length > 0 && selectedProducts.length < allProducts.length) {
            for (var i = 0; i < selectedProducts.length; i++) productMask[selectedProducts[i]] = true;
        }
        var config = {
            name: resolvedName,
            isDerived: true,
            baseGroupId: baseGroupId,
            productMask: productMask,
        };
        ['feeMode', 'feeRate', 'feeMap', 'feeSensitivity', 'useCloseToday', 'rebalanceMode', 'liquidityMode', 'liquidityPercent'].forEach(function(key) {
            var inherited = _addDraft._inheritedConfigKeys && _addDraft._inheritedConfigKeys[key];
            if (!inherited && _addDraft[key] !== undefined) config[key] = _addDraft[key];
        });
        if (parentDerivedId) config.parentId = parentDerivedId;
        try {
            GT.datamodel.groups.add(config);
        } catch (err) {
            alert('创建派生组失败: ' + (err && err.message || err));
            return;
        }
        if (parentDerivedId && GT.datamodel.groups) {
            var parentNode = GT.datamodel.groups.get(parentDerivedId);
            if (parentNode && parentNode._expanded === false) GT.datamodel.groups.toggleExpanded(parentDerivedId);
        }
        _exitAddMode();
    }

    function _submitAddLSGroup() {
        var lsPanel = GT.panels.add && GT.panels.add.ls;
        if (lsPanel && typeof lsPanel.handleSave === 'function') {
            var result = lsPanel.handleSave();
            if (result.success) { _exitAddMode(); }
            else if (result.error) { alert('创建 LS 组失败: ' + result.error); }
        }
    }

    function _enterEditMode(selection) {
        var REG = window.GT_CONFIG_REGISTRY;
        if (REG) REG.rollbackDirty();
        _panelMode = 'edit';
        _editSelection = selection || {};
        _renderTabActions();
        var tabBtnsBar = document.getElementById('gt-tab-btns');
        if (tabBtnsBar) {
            var L = GT_TAB_CATEGORY.LIST, C = GT_TAB_CATEGORY.CONFIG;
            var selIds = _selectedEditIds();
            var hasDerived = selIds.some(function(sid) {
                var g = GT.datamodel.groups && GT.datamodel.groups.get(sid);
                return g && g.isDerived;
            });
            var visibleList = GT_PANEL_REGISTRY.filter(function(p) {
                if (p.category === L) return true;
                if (p.category === C && p.name === 'config-derived' && !hasDerived) return false;
                if (p.category === C) return true;
                return false;
            });
            if (visibleList.length >= 1) {
                var stHtml = '';
                visibleList.forEach(function(p) {
                    stHtml += '<button class="gt-tab' + (p.name === _currentTab ? ' active' : '') + '" data-tab="' + p.name + '">' + p.label + '</button>';
                });
                tabBtnsBar.innerHTML = stHtml;
                tabBtnsBar.querySelectorAll('.gt-tab').forEach(function(st) {
                    st.addEventListener('click', function() { mountTab(st.getAttribute('data-tab')); });
                });
            }
        }
    }

    function _exitEditMode() {
        var REG = window.GT_CONFIG_REGISTRY;
        if (REG) REG.rollbackDirty();
        _panelMode = 'list';
        _editSelection = null;
        if (GT.state) {
            GT.state.setActiveBaseGroupId(null);
            GT.state.setActiveDerivedNodeId(null);
            GT.state.emit('editModeExited');
        }
        _renderTabActions();
        var tabBtnsBar = document.getElementById('gt-tab-btns');
        if (tabBtnsBar) {
            var L = GT_TAB_CATEGORY.LIST;
            var visibleList = GT_PANEL_REGISTRY.filter(function(p) { return p.category === L; });
            if (visibleList.length >= 1) {
                var stHtml = '';
                visibleList.forEach(function(p) {
                    stHtml += '<button class="gt-tab' + (p.name === _currentTab ? ' active' : '') + '" data-tab="' + p.name + '">' + p.label + '</button>';
                });
                tabBtnsBar.innerHTML = stHtml;
                tabBtnsBar.querySelectorAll('.gt-tab').forEach(function(st) {
                    st.addEventListener('click', function() { mountTab(st.getAttribute('data-tab')); });
                });
            } else { tabBtnsBar.innerHTML = ''; }
        }
        mountTab('list');
    }

    function _createDerivedFromSelection() {
        var selIds = _selectedEditIds();
        if (selIds.length !== 1) { alert('请选择 1 行来创建派生组'); return; }
        var draft = _buildDerivedAddDraftFromSelection();
        if (!draft.preselectedBaseGroupId && !draft.preselectedParentDerivedId) { alert('无法识别选中的分组类型'); return; }
        _exitEditMode();
        _panelMode = 'add';
        _addDraft = draft;
        mountTab('config-derived');
        _renderTabActions();
    }

    function _createLSFromSelection() {
        var selIds = _selectedEditIds();
        if (selIds.length < 2) { alert('请至少选择 2 个基础组来创建 Long-Short 组'); return; }
        _exitEditMode();
        _panelMode = 'add';
        _addDraft = { addFlow: 'ls', preselectedBaseGroupIds: selIds };
        mountTab('add-ls');
        _renderTabActions();
    }

    function _saveEditChanges() {
        var REG = window.GT_CONFIG_REGISTRY;
        if (REG) REG.commitDirty();
        if (_currentTab === 'config-derived') {
            var selIds = _selectedEditIds();
            if (selIds.length === 1) {
                var derivedPanel = GT.panels.config && GT.panels.config.derived;
                if (derivedPanel && typeof derivedPanel.getSelectedProducts === 'function') {
                    var selectedProds = derivedPanel.getSelectedProducts();
                    var productMask = {};
                    for (var pi = 0; pi < selectedProds.length; pi++) productMask[selectedProds[pi]] = true;
                    try { GT.datamodel.groups.update(selIds[0], { productMask: productMask }); }
                    catch (e) { alert('保存品种修改失败: ' + (e && e.message || e)); return; }
                }
            }
        }
        _panelMode = 'list';
        _editSelection = null;
        if (GT.state) {
            GT.state.setActiveBaseGroupId(null);
            GT.state.setActiveDerivedNodeId(null);
            GT.state.emit('editModeExited');
        }
        _renderTabActions();
        var tabBtnsBar = document.getElementById('gt-tab-btns');
        if (tabBtnsBar) {
            var L = GT_TAB_CATEGORY.LIST;
            var visibleList = GT_PANEL_REGISTRY.filter(function(p) { return p.category === L; });
            if (visibleList.length >= 1) {
                var stHtml = '';
                visibleList.forEach(function(p) {
                    stHtml += '<button class="gt-tab' + (p.name === _currentTab ? ' active' : '') + '" data-tab="' + p.name + '">' + p.label + '</button>';
                });
                tabBtnsBar.innerHTML = stHtml;
                tabBtnsBar.querySelectorAll('.gt-tab').forEach(function(st) {
                    st.addEventListener('click', function() { mountTab(st.getAttribute('data-tab')); });
                });
            } else { tabBtnsBar.innerHTML = ''; }
        }
        mountTab('list');
    }

    // ═══ 核心 Tab 切换函数 ═══
    function mountTab(tabName) {
        _unmountCurrent();
        _currentTab = tabName;

        var L = GT_TAB_CATEGORY.LIST, C = GT_TAB_CATEGORY.CONFIG, A = GT_TAB_CATEGORY.ADD;
        var visibleCategories;
        if (_panelMode === 'list') visibleCategories = [L];
        else if (_panelMode === 'edit') visibleCategories = [L, C, A];
        else if (_panelMode === 'add') visibleCategories = [A, C];
        else visibleCategories = [L];

        var visibleList = GT_PANEL_REGISTRY.filter(function(p) {
            return visibleCategories.indexOf(p.category) >= 0;
        });

        if (_panelMode === 'add' && _addDraft && _addDraft.addFlow) {
            visibleList = visibleList.filter(function(p) {
                if (p.category === A) return p.addFlow === _addDraft.addFlow;
                if (p.category === C && p.name === 'config-derived') return _addDraft.addFlow === 'derived';
                return true;
            });
        } else if (_panelMode === 'edit') {
            var selIds = _selectedEditIds();
            var hasDerived = selIds.some(function(sid) {
                var g = GT.datamodel.groups && GT.datamodel.groups.get(sid);
                return g && g.isDerived;
            });
            visibleList = visibleList.filter(function(p) {
                if (p.category === A) return false;
                if (p.name === 'config-derived' && !hasDerived) return false;
                return true;
            });
        }

        var entry = visibleList.find(function(p) {
            if (p.name !== tabName) return false;
            if (_panelMode === 'add' && p.category === A) return true;
            return true;
        });
        if (!entry) return;
        if (_panelMode === 'edit' && tabName === 'config-derived') {
            _addDraft = _buildDerivedAddDraftFromSelection();
        }

        var tabBtnsBar = document.getElementById('gt-tab-btns');
        if (tabBtnsBar && visibleList.length >= 1) {
            var stHtml = '';
            visibleList.forEach(function(p) {
                stHtml += '<button class="gt-tab' + (p.name === tabName ? ' active' : '') + '" data-tab="' + p.name + '">' + p.label + '</button>';
            });
            tabBtnsBar.innerHTML = stHtml;
            tabBtnsBar.querySelectorAll('.gt-tab').forEach(function(st) {
                st.addEventListener('click', function() { mountTab(st.getAttribute('data-tab')); });
            });
        } else if (tabBtnsBar) { tabBtnsBar.innerHTML = ''; }

        var panelContainer = document.getElementById('gt-panel-container');
        if (panelContainer) {
            panelContainer.innerHTML = '<div id="' + entry.containerId + '" class="gt-panel-inner"></div>';
        }
        if (entry.panel && typeof entry.panel.mount === 'function') {
            var containerEl = document.getElementById(entry.containerId);
            if (containerEl) { entry.panel.mount(containerEl); _currentPanel = entry.panel; }
            else { console.warn('mountTab: container #' + entry.containerId + ' not found for tab ' + tabName); }
        }
        _renderTabActions();
    }

    // ═══ 初始化（由 app.js 的 init 调用） ═══
    function init() {
        _registerPanels();
        mountTab('list');
    }

    // ═══ 导出 ═══
    GT.panels.registry = {
        // 核心
        init: init,
        mountTab: mountTab,
        registerPanels: _registerPanels,

        // 模式管理
        getPanelMode: function() { return _panelMode; },
        getAddDraft: function() { return _addDraft; },
        updateAddDraft: function(patch) {
            if (!_addDraft) return;
            Object.assign(_addDraft, patch);
            if (_addDraft._inheritedConfigKeys && patch) {
                Object.keys(patch).forEach(function(key) { delete _addDraft._inheritedConfigKeys[key]; });
            }
        },
        getEditSelection: function() { return _editSelection; },
        enterEditMode: _enterEditMode,
        exitEditMode: _exitEditMode,
        enterAddMode: _enterAddMode,
        exitAddMode: _exitAddMode,
        renderTabActions: _renderTabActions,

        // 内部钩子
        _selectedEditIds: _selectedEditIds,
    };

    // ── 桥接：保持 GT.ui.* 的向后兼容性 ──
    GT.ui = GT.ui || {};
    GT.ui.mountTab = mountTab;
    GT.ui.getPanelMode = GT.panels.registry.getPanelMode;
    GT.ui.getAddDraft = GT.panels.registry.getAddDraft;
    GT.ui.updateAddDraft = GT.panels.registry.updateAddDraft;
    GT.ui.getEditSelection = GT.panels.registry.getEditSelection;
    GT.ui.enterEditMode = GT.panels.registry.enterEditMode;
    GT.ui.exitEditMode = GT.panels.registry.exitEditMode;
    GT.ui.enterAddMode = GT.panels.registry.enterAddMode;
    GT.ui.exitAddMode = GT.panels.registry.exitAddMode;
    GT.ui.renderTabActions = GT.panels.registry.renderTabActions;
    GT.ui.createDerivedFromSelection = _createDerivedFromSelection;
    GT.ui.createLSFromSelection = _createLSFromSelection;
})();
