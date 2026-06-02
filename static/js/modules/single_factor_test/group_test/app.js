(function(){
    var GT = window.GroupTest;
    if (!GT) { console.warn('[GroupTest] bootstrap missing'); return; }

    // 确保 GT.ui 在全局代码使用前已初始化
    GT.ui = GT.ui || {};

    // 时区：后端返回 UTC epoch，useUTC=false 按浏览器本地时区显示
    if (typeof Highcharts !== 'undefined') {
        Highcharts.setOptions({ global: { useUTC: false } });
    }

    // ---------- 日期工具桥接（已迁移到 GT.utils.dates） ----------
    // 保留本地引用以兼容现有代码，无新代码使用时应逐步移除
    var showDateHint = GT.utils.dates ? GT.utils.dates.showDateHint : function(){};
    var bindDateValidation = GT.utils.dates ? GT.utils.dates.bindDateValidation : function(){};
    var buildValidDate = GT.utils.dates ? GT.utils.dates.buildValidDate : function(y,m,d){ return y+'-'+m+'-'+d; };
    var readGroupTimeRangeInput = GT.utils.dates ? GT.utils.dates.readGroupTimeRangeInput : function(){ return {startDate:null,endDate:null}; };
    var persistGroupTimeRangeToDatamodel = GT.utils.dates ? GT.utils.dates.persistGroupTimeRangeToDatamodel : function(){};
    var resolveGroupRunTimeRange = GT.utils.dates ? GT.utils.dates.resolveGroupRunTimeRange : function(){ return {startDate:null,endDate:null}; };
    var bindUseTimeRange = GT.utils.dates ? GT.utils.dates.bindUseTimeRange : function(){};
    var syncFromTimeModule = GT.utils.dates ? GT.utils.dates.syncFromTimeModule : function(){};
    var bindTimeSyncListeners = GT.utils.dates ? GT.utils.dates.bindTimeSyncListeners : function(){};

    GT.ui._readGroupTimeRangeInput = readGroupTimeRangeInput;
    GT.ui._resolveGroupRunTimeRange = resolveGroupRunTimeRange;

    // ---------- 激活状态桥接（已迁移到 GT.utils.dates） ----------
    var getActiveSubmissionId = GT.utils.dates ? GT.utils.dates.getActiveSubmissionId : function() { return null; };
    var getActiveFactorAlias = GT.utils.dates ? GT.utils.dates.getActiveFactorAlias : function() { return null; };
    var pageHasICModule = GT.utils.dates ? GT.utils.dates.pageHasICModule : function() { return false; };

    // ---------- 多时段品种策略提示面板 ----------
    function updateStrategyPanel() {
        return GT.results && GT.results.strategyPanel && GT.results.strategyPanel.update
            ? GT.results.strategyPanel.update.apply(GT.results.strategyPanel, arguments) : undefined;
    }
    function updateRebalanceModeDescription() {
        return GT.panels && GT.panels.actions && GT.panels.actions.updateRebalanceModeDescription
            ? GT.panels.actions.updateRebalanceModeDescription() : undefined;
    }

    // ---------- 清空测试结果 ----------
    function clearResults(options) {
        options = options || {};
        var chartContainer = document.getElementById('group_chart_container');
        var metricsContainer = document.getElementById('group_metrics_container');
        if (chartContainer) chartContainer.style.display = 'none';
        if (metricsContainer) metricsContainer.style.display = 'none';
        if (GT.results && GT.results.snapshot && typeof GT.results.snapshot.closeSnapshotDrawer === 'function') {
            GT.results.snapshot.closeSnapshotDrawer();
        }
        if (options.clearStatus) {
            var status = document.getElementById('group_test_status');
            if (status) status.innerHTML = '';
        }
    }

    /**
     * 构建连续等间隔时间轴。
     * 自动检测日内/日间，生成自适应格式的标签，并计算合理的标签步长。
     * 返回 { labels, labelAt, stepMs, labelEvery }。
     */
    function buildContinuousTimeAxis(rows, timestampGetter) {
        return GT.utils.dates.buildContinuousTimeAxis(rows, timestampGetter);
    }

    function drawGroupChart(groups) {
        if (!GT.results || !GT.results.chart || !GT.results.chart.groups || typeof GT.results.chart.groups.draw !== 'function') return;
        GT.results.chart.groups.draw(groups, {
            onSnapshot: fetchGroupSnapshot,
        });
    }

    // ---------- 快照导航状态（已迁移到 GT.results.snapshot） ----------
    var fetchGroupSnapshot = function(t) { return GT.results.snapshot.fetchGroupSnapshot(t); };
    var closeSnapshotDrawer = function() { return GT.results.snapshot.closeSnapshotDrawer(); };
    var openSnapshotDrawer = function() { return GT.results.snapshot.openSnapshotDrawer(); };
    var bindSnapshotDrawerEvents = function() { return GT.results.snapshot.bindSnapshotDrawerEvents(); };

    // ---------- 渲染统计指标表格 ----------
    function renderMetricsTable(metrics) {
        if (GT.results && GT.results.renderer && GT.results.renderer.renderMetricsTable) {
            GT.results.renderer.renderMetricsTable(metrics);
        }
    }

    function renderGroupDetailTable(rows, type) {
        return GT.panels && GT.panels.actions && GT.panels.actions.renderGroupDetailTable
            ? GT.panels.actions.renderGroupDetailTable(rows, type) : '<div class="group-detail-muted">暂无数据</div>';
    }

    function renderGroupFrequency(rows, selectable) {
        return GT.panels && GT.panels.actions && GT.panels.actions.renderGroupFrequency
            ? GT.panels.actions.renderGroupFrequency(rows, selectable) : '<div class="group-detail-muted">暂无数据</div>';
    }

    /* ───── 辅助函数（已移出到 panels/actions.js） ───── */
    function formatGroupProduct(p) { return GT.panels && GT.panels.actions ? GT.panels.actions.formatGroupProduct(p) : '—'; }
    function formatGroupProducts(ps) { return GT.panels && GT.panels.actions ? GT.panels.actions.formatGroupProducts(ps) : '—'; }
    function escapeHtml(v) { return GT.escapeHTML(v); }
    function fmtFeeRate(v) { return GT.panels && GT.panels.actions ? GT.panels.actions.fmtFeeRate(v) : '—'; }
    function isRealFee(r) { return GT.panels && GT.panels.actions ? GT.panels.actions.isRealFee(r) : false; }

    function getDerivedGroupsForCurrentBase(groupIndex) {
        return GT.panels && GT.panels.actions ? GT.panels.actions.getDerivedGroupsForCurrentBase(groupIndex) : [];
    }

    // ── 桥接（实现已移出到 panels/actions.js / core/actions/runner.js） ──
    function renderDerivedGroupsPanel(groupIndex) {
        if (GT.panels && GT.panels.actions && GT.panels.actions.renderDerivedGroupsPanel) {
            GT.panels.actions.renderDerivedGroupsPanel(groupIndex);
        }
    }
    function bindDerivedGroupPanelEvents(groupIndex) {
        if (GT.panels && GT.panels.actions && GT.panels.actions.bindDerivedGroupPanelEvents) {
            GT.panels.actions.bindDerivedGroupPanelEvents(groupIndex);
        }
    }
    function collectSelectedDerivedProducts() {
        return GT.panels && GT.panels.actions ? GT.panels.actions.collectSelectedDerivedProducts() : [];
    }
    function productNamesForTester(testerId) {
        return GT.panels && GT.panels.actions ? GT.panels.actions.productNamesForTester(testerId) : [];
    }
    function effectiveDerivedProductNames(node, seen) {
        return GT.panels && GT.panels.actions ? GT.panels.actions.effectiveDerivedProductNames(node, seen) : [];
    }
    function groupDisplayKey(group, allGroups) {
        return GT.panels && GT.panels.actions ? GT.panels.actions.groupDisplayKey(group, allGroups) : (group ? group.shortAlias || group.key || group.name || group.id || '' : '');
    }
    function lsDisplayName(ls) {
        return GT.panels && GT.panels.actions ? GT.panels.actions.lsDisplayName(ls) : ((ls && (ls.shortAlias || ls.name)) || 'Long-Short');
    }
    function serializeGroupFeeMap(feeMap) {
        return GT.panels && GT.panels.actions ? GT.panels.actions.serializeGroupFeeMap(feeMap) : feeMap;
    }
    function serializeGroupVariant(group, fallbackName) {
        return GT.panels && GT.panels.actions ? GT.panels.actions.serializeGroupVariant(group, fallbackName) : group;
    }
    function collectDerivedPayloadForBatch(batch) {
        if (!GT.datamodel || !GT.datamodel.groups || typeof GT.datamodel.groups.collectDerivedPayloadForBatch !== 'function') return [];
        return GT.datamodel.groups.collectDerivedPayloadForBatch(batch, { getProductsForTester: productNamesForTester });
    }
    function defineDerivedGroup(groupIndex) {
        if (GT.panels && GT.panels.actions && GT.panels.actions.defineDerivedGroup) {
            GT.panels.actions.defineDerivedGroup(groupIndex);
        }
    }
    function findBaseGroupIdForResultGroup(groupIndex) {
        return GT.panels && GT.panels.actions ? GT.panels.actions.findBaseGroupIdForResultGroup(groupIndex) : null;
    }
    function openAddDerivedFromDetail(groupIndex) {
        if (GT.panels && GT.panels.actions && GT.panels.actions.openAddDerivedFromDetail) {
            GT.panels.actions.openAddDerivedFromDetail(groupIndex);
        }
    }
    function makeUniqueGroupKey(name, ownId) {
        return GT.panels && GT.panels.actions ? GT.panels.actions.makeUniqueGroupKey(name, ownId) : (name || ownId || '派生组');
    }
    function removeGeneratedDerivedArtifacts(id) {
        if (GT.panels && GT.panels.actions && GT.panels.actions.removeGeneratedDerivedArtifacts) {
            GT.panels.actions.removeGeneratedDerivedArtifacts(id);
        }
    }

    // ── 派生组生成（实现已移出到 core/actions/runner.js，保留局部桥接） ──
    async function _generateDerivedGroupOnce(def, fee, fee_map) {
        if (GT.core.actions && GT.core.actions.runner && GT.core.actions.runner._generateDerivedGroupOnce) {
            return GT.core.actions.runner._generateDerivedGroupOnce(def, fee, fee_map);
        }
        return null;
    }
    function _applyDerivedGroupResult(result) {
        if (GT.core.actions && GT.core.actions.runner && GT.core.actions.runner._applyDerivedGroupResult) {
            return GT.core.actions.runner._applyDerivedGroupResult(result);
        }
    }
    function _refreshGroupView(baseGroupIndex) {
        if (GT.core.actions && GT.core.actions.runner && GT.core.actions.runner._refreshGroupView) {
            return GT.core.actions.runner._refreshGroupView(baseGroupIndex);
        }
    }
    async function generateDerivedGroup(id) {
        if (GT.core.actions && GT.core.actions.runner && GT.core.actions.runner.generateDerivedGroup) {
            return GT.core.actions.runner.generateDerivedGroup(id);
        }
    }
    function deleteDerivedGroup(id) {
        if (GT.core.actions && GT.core.actions.runner && GT.core.actions.runner.deleteDerivedGroup) {
            return GT.core.actions.runner.deleteDerivedGroup(id);
        }
    }

    // ──────────────────────────────────────────────
    // Detail overlay — 桥接到 metrics/detail_overlay/
    // ──────────────────────────────────────────────
    if (!GT.results.detailOverlay) GT.results.detailOverlay = {};
    GT.results.detailOverlay.hostRefs = {
        get _lastGrossData() { return _lastGrossData; },
        get _lastMetrics() { return _lastMetrics; },
        get _currentGroupDetailIndex() { return (typeof _currentGroupDetailIndex !== 'undefined') ? _currentGroupDetailIndex : null; },
        onRenderDerivedPanel: renderDerivedGroupsPanel,
    };

    // renderGroupDetail 委托给 tabs.js 版本
    function renderGroupDetail(detail, options) {
        if (GT.metrics && GT.metrics.detailOverlay && GT.metrics.detailOverlay.tabs && typeof GT.metrics.detailOverlay.tabs.renderGroupDetail === 'function') {
            GT.metrics.detailOverlay.tabs.renderGroupDetail(detail, options);
        }
    }

    // ── LS 配置桥接（实现已移出到 panels/actions.js / core/actions/collect.js） ──
    function collectLongShortConfig(nGroups) {
        return GT.core.actions && GT.core.actions.collect ? GT.core.actions.collect.collectLongShortConfig(nGroups) : null;
    }
    function defaultLongShortDefinition() {
        return GT.core.actions && GT.core.actions.collect ? GT.core.actions.collect.defaultLongShortDefinition() : { id: 'LS1', name: 'Long-Short', longGroups: '1', longWeights: '1', shortGroups: '', shortWeights: '1' };
    }
    function buildLongShortPayload(def, nGroups) {
        return GT.core.actions && GT.core.actions.collect ? GT.core.actions.collect.buildLongShortPayload(def, nGroups) : null;
    }
    function collectLongShortConfigs(nGroups) {
        return GT.core.actions && GT.core.actions.collect ? GT.core.actions.collect.collectLongShortConfigs(nGroups) : [];
    }
    function buildGroupStructureKey(submissionId, factorAlias, nGroups, startDate, endDate) {
        return GT.core.actions && GT.core.actions.collect ? GT.core.actions.collect.buildGroupStructureKey(submissionId, factorAlias, nGroups, startDate, endDate) : [submissionId, factorAlias, nGroups, startDate, endDate].join('|');
    }

    // ── LS 面板桥接 ──
    function updateLongShortSummary() {
        if (GT.panels && GT.panels.actions && GT.panels.actions.updateLongShortSummary) {
            GT.panels.actions.updateLongShortSummary();
        }
    }
    function renderLongShortConfigList() {
        if (GT.panels && GT.panels.actions && GT.panels.actions.renderLongShortConfigList) {
            GT.panels.actions.renderLongShortConfigList();
        }
    }

    async function collectGroupRunPayload(submissionId, factorAlias) {
        if (GT.core.actions && GT.core.actions.collect && GT.core.actions.collect.buildGroupRunPayload) {
            return GT.core.actions.collect.buildGroupRunPayload(submissionId, factorAlias);
        }
        var statusSpan = document.getElementById('group_test_status');
        if (!submissionId || !factorAlias) {
            return { error: '请先选择测试器和因子' };
        }
        // ── 兜底 ──
        return { payload: { submission_id: submissionId, factor_alias: factorAlias }, statusEl: statusSpan };
    }

    function applyGroupTestResult(data, statusText) {
        // DEBUG: log response identity to verify tester switching
        console.log('[GroupTest] applyGroupTestResult:', {
            submission_id: data.submission_id,
            factor_alias: data.factor_alias,
            tester_alias: data.tester_alias,
            tester_product_count: data.tester_product_count,
            n_groups: data.n_groups,
        });

        updateStrategyPanel(data.multi_session_active, data.rebalance_mode, data.multi_session_batches);
        _lastGrossData = data.groups;
        _lastMetrics = data.metrics;
        _lastNgroups = data.n_groups;
        _lastTimestamps = data.groups.length > 0 ? data.groups[0].timestamps : [];
        _lastGroupStructureKey = data.structure_key || null;

        // 同步到 GT.core.cache 以便其他模块读取
        if (GT.core && GT.core.cache) {
            GT.core.cache.setLastGrossData(_lastGrossData);
            GT.core.cache.setLastMetrics(_lastMetrics);
            GT.core.cache.setLastGroupStructureKey(_lastGroupStructureKey);
            GT.core.cache.setDerivedGroups(_derivedGroups);
            GT.core.cache.setDerivedGroupSeq(_derivedGroupSeq);
        }

        // metrics key 即为 shortAlias，无需额外映射表

        // 从响应中重建 _derivedGroups（后端已统一计算，无需额外请求）
        // 注意：跳过 LS 组（is_ls），其 derived 中无 base_group。
        _derivedGroups = [];
        _derivedGroupSeq = 1;
        (data.groups || []).forEach(function(g) {
            if (g.is_derived && g.derived && !g.is_ls) {
                _derivedGroups.push({
                    id: g.derived.id || ('D' + _derivedGroupSeq),
                    name: g.name,
                    baseGroup: g.derived.base_group,
                    productNames: g.derived.product_names || [],
                    key: g.key,
                    generated: true
                });
                var num = parseInt(String(g.derived.id || '').replace(/^D/, ''), 10);
                if (!isNaN(num)) _derivedGroupSeq = Math.max(_derivedGroupSeq, num + 1);
            }
        });

        // 画图 + 指标表
        drawGroupChart(data.groups);
        renderMetricsTable(data.metrics);
    }

    // 桥接到 runner.js
    async function refreshAllDerivedGroups(generation) { return GT.core.actions.runner.refreshAllDerivedGroups(generation); }
    async function regenerateDerivedGroupQuiet(def, generation) { return GT.core.actions.runner.regenerateDerivedGroupQuiet(def, generation); }

    // 桥接到 runner.js
    function postGroupTest(payload) { return GT.core.actions.runner.postGroupTest(payload); }
    function postBatchGroupTest(payload) { return GT.core.actions.runner.postBatchGroupTest(payload); }

    // 桥接到 runner.js
    async function loadDefaultGroups() { return GT.core.actions.runner.loadDefaultGroups(); }

    // 桥接到 runner.js
    async function runGroupTest() { return GT.core.actions.runner.runGroupTest(); }

    // 桥接到 runner.js
    async function runAllGroupTestsForCurrentSubmission() { return GT.core.actions.runner.runAllGroupTestsForCurrentSubmission(); }

    // ---------- 缓存桥接（共享状态已迁移到 GT.core.cache） ----------
    // 本地桥接变量供 app.js 内其他函数直接使用
    var _groupResultsBySubmission = GT.core.cache ? GT.core.cache.getGroupResultsBySubmission() : {};
    var _activeGroupSubmissionId = GT.core.cache ? GT.core.cache.getActiveGroupSubmissionId() : null;
    var _activeGroupFactorBySubmission = GT.core.cache ? GT.core.cache.getActiveGroupFactorBySubmission() : {};
    var _derivedGroups = GT.core.cache ? GT.core.cache.getDerivedGroups() : [];
    var _derivedGroupSeq = GT.core.cache ? GT.core.cache.getDerivedGroupSeq() : 1;
    var _derivedGeneration = GT.core.cache ? GT.core.cache.getDerivedGeneration() : 0;
    var _currentGroupDetailIndex = GT.core.cache ? GT.core.cache.getCurrentGroupDetailIndex() : null;
    var _longShortDefinitions = GT.core.cache ? GT.core.cache.getLongShortDefinitions() : [defaultLongShortDefinition()];
    var _lastGroupStructureKey = GT.core.cache ? GT.core.cache.getLastGroupStructureKey() : null;
    var _lastGrossData = GT.core.cache ? GT.core.cache.getLastGrossData() : null;
    var _lastMetrics = GT.core.cache ? GT.core.cache.getLastMetrics() : null;
    var _lastTimestamps = GT.core.cache ? GT.core.cache.getLastTimestamps() : [];
    var _lastNgroups = GT.core.cache ? GT.core.cache.getLastNgroups() : 0;

    function cacheGroupResult(sid, fa, d) { return GT.core.cache && GT.core.cache.cacheGroupResult(sid, fa, d); }
    function getCachedGroupResult(sid, fa) { return GT.core.cache ? GT.core.cache.getCachedGroupResult(sid, fa) : null; }
    function clearCachedGroupResultsForSubmission(sid) { return GT.core.cache && GT.core.cache.clearCachedGroupResultsForSubmission(sid); }
    function updateActiveGroupCache() {
        var submissionId = getActiveSubmissionId();
        var factorAlias = getActiveFactorAlias();
        if (!submissionId || !factorAlias) return;
        var cached = getCachedGroupResult(submissionId, factorAlias);
        if (!cached) return;
        cached.groups = _lastGrossData;
        cached.metrics = _lastMetrics;
        cached._derivedGroups = _derivedGroups.map(function(item) { return Object.assign({}, item); });
        cached.structure_key = _lastGroupStructureKey;
    }
    function markGroupFactorStatus(sid, fa, s) { return GT.core.cache && GT.core.cache.markGroupFactorStatus(sid, fa, s); }
    function clearGroupFactorStatuses(sid) { return GT.core.cache && GT.core.cache.clearGroupFactorStatuses(sid); }

    // ═══ Panel registry — unified flat tab list ═══
    // Each entry: { name, label, containerId, category, panel, addFlow }
    // 桥接：fee.js 中 close-today 变更回调
    GT.ui.onCloseTodayChanged = function() {
        var derivedGroups = GT.core.cache ? GT.core.cache.getDerivedGroups() : [];
        if (derivedGroups.length > 0) {
            var gen = (GT.core.cache ? GT.core.cache.getDerivedGeneration() : 0) + 1;
            if (GT.core.cache) GT.core.cache.setDerivedGeneration(gen);
            _derivedGeneration = gen;
            refreshAllDerivedGroups(gen);
        }
    };

    function bindICModuleEvents() {
        // 分组测试结果按 submission + factor 缓存，切换选项卡时不主动清空。
    }

    // ---------- 初始化 ----------
    function init() {
        bindDateValidation();
        bindUseTimeRange();
        bindICModuleEvents();
        bindTimeSyncListeners();
        // 使用 GT.fee.bind() 替代原 bindFeeControls()
        if (GT.fee && typeof GT.fee.bind === 'function') {
            GT.fee.bind();
        }
        bindSnapshotDrawerEvents();
        bindGroupDetailOverlay();
        bindGroupSectionToggles();
        updateRebalanceModeDescription();
        syncFromTimeModule();
        document.addEventListener('timeRangeDefaultLoaded', syncFromTimeModule, { once: true });
        setTimeout(syncFromTimeModule, 0);
        var runBtn = document.getElementById('run_group_test_btn');
        if (runBtn) runBtn.addEventListener('click', runGroupTest);
        var defaultBtn = document.getElementById('load_default_groups_btn');
        if (defaultBtn) defaultBtn.addEventListener('click', loadDefaultGroups);
        var rebalanceSelect = document.getElementById('rebalance_mode');
        if (rebalanceSelect) rebalanceSelect.addEventListener('change', updateRebalanceModeDescription);

        // P7: Wire unified tab bar — delegated to panels/registry.js
        GT.panels.registry.init();

        // 如果已有 submissions，渲染两级选项卡
        if (window.submissions && window.submissions.length > 0) {
            window.renderGroupTabs(window.submissions);
        }

        // 绑定分组组合设置折叠/展开
        var sectionHeader = document.getElementById('gt-section-header');
        var sectionToggle = document.getElementById('gt-section-toggle');
        var layerTabs = document.getElementById('gt-layer-tabs');
        if (sectionHeader && layerTabs && sectionToggle) {
            // 移除 HTML 上的 inline onclick，用 JS 统一管理
            sectionHeader.removeAttribute('onclick');
            sectionHeader.addEventListener('click', function() {
                var collapsed = layerTabs.classList.toggle('gt-collapsed');
                sectionToggle.style.transform = collapsed ? 'rotate(-90deg)' : 'rotate(0deg)';
                // Scroll to reveal tab content when expanding
                if (!collapsed && layerTabs) {
                    layerTabs.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            });
            // 默认折叠
            layerTabs.classList.add('gt-collapsed');
            sectionToggle.style.transform = 'rotate(-90deg)';
        }

        // ── Click-on-empty-area exits edit mode ──
        var panelContainer = document.getElementById('gt-panel-container');
        if (panelContainer) {
            panelContainer.addEventListener('click', function(e) {
                // Only react if clicking the container itself (not children), and in edit mode
                if (e.target === panelContainer && GT.ui.getPanelMode() === 'edit') {
                    GT.ui.exitEditMode();
                }
            });
        }
    }

    function bindGroupDetailOverlay() {
        var overlay = document.getElementById('group-detail-overlay');
        var closeBtn = document.getElementById('group-detail-close');
        if (closeBtn) closeBtn.addEventListener('click', function() {
            if (overlay) overlay.classList.remove('open');
        });
        if (overlay) overlay.addEventListener('click', function(event) {
            if (event.target === overlay) overlay.classList.remove('open');
        });
        var lsOverlay = document.getElementById('long-short-drawer');
        var lsOpenBtn = document.getElementById('long-short-drawer-trigger');
        var lsCloseBtn = document.getElementById('long-short-drawer-close');
        var lsAddBtn = document.getElementById('long-short-add-btn');
        if (lsOpenBtn) lsOpenBtn.addEventListener('click', function() {
            renderLongShortConfigList();
            updateLongShortSummary();
            if (lsOverlay) lsOverlay.classList.add('open');
        });
        if (lsCloseBtn) lsCloseBtn.addEventListener('click', function() {
            if (lsOverlay) lsOverlay.classList.remove('open');
        });
        if (lsOverlay) lsOverlay.addEventListener('click', function(event) {
            if (event.target === lsOverlay) lsOverlay.classList.remove('open');
        });
        if (lsAddBtn) lsAddBtn.addEventListener('click', function() {
            var nextId = 'LS' + (Date.now());
            _longShortDefinitions.push({ id: nextId, name: 'Long-Short ' + _longShortDefinitions.length, longGroups: '1', longWeights: '1', shortGroups: '', shortWeights: '1' });
            renderLongShortConfigList();
            updateLongShortSummary();
        });
        updateLongShortSummary();
        var rankingOverlay = document.getElementById('group-ranking-overlay');
        var rankingCloseBtn = document.getElementById('group-ranking-close');
        if (rankingCloseBtn) rankingCloseBtn.addEventListener('click', function() {
            if (rankingOverlay) rankingOverlay.classList.remove('open');
        });
        if (rankingOverlay) rankingOverlay.addEventListener('click', function(event) {
            if (event.target === rankingOverlay) rankingOverlay.classList.remove('open');
        });
    }

    function bindGroupSectionToggles() {
        document.querySelectorAll('.group-detail-section-toggle').forEach(function(btn) {
            btn.addEventListener('click', function() {
                var section = btn.closest('.group-detail-section');
                if (section) section.classList.toggle('open');
            });
        });
    }

    // 暴露给外部调用：渲染分组测试 UI（P7: 5-layer layout）
    // Fills #gt-submission-tabs with horizontal pills.
    // Old #group-tab-container kept hidden for backward compat factor navigation.
    window.renderGroupTabs = function(submissions) {
        var container = document.getElementById('group-tab-container');
        var subTabsContainer = document.getElementById('gt-submission-tabs');
        var runBtn = document.getElementById('run_group_test_btn');
        var defaultBtn = document.getElementById('load_default_groups_btn');

        if (!submissions || submissions.length === 0) {
            // Update both old and new containers
            if (container) container.innerHTML = '<div style="color:#888; padding:8px; border:1px dashed #ccc; border-radius:4px; font-size:13px;">暂无提交记录，请先在产品类别筛选模块提交产品。</div>';
            if (subTabsContainer) subTabsContainer.innerHTML = '<span style="color:#888;font-size:12px;padding:4px 8px;">暂无提交记录</span>';
            if (runBtn) runBtn.style.display = 'none';
            if (defaultBtn) defaultBtn.style.display = 'none';
            return;
        }
        if (runBtn) runBtn.style.display = '';
        if (defaultBtn) defaultBtn.style.display = '';

        var factorList = window.factorList || [];
        var activeSubmission = submissions.find(function(sub) {
            return String(sub.id) === String(_activeGroupSubmissionId);
        }) || submissions[0];
        _activeGroupSubmissionId = activeSubmission ? String(activeSubmission.id) : null;

        // ── P7: Fill #gt-submission-tabs with horizontal pills ──
        if (subTabsContainer) {
            var subTabsHtml = '';
            submissions.forEach(function(sub) {
                var isActive = String(sub.id) === String(_activeGroupSubmissionId);
                var tabLabel = sub.product_group || sub.label || ('测试器');
                subTabsHtml += '<button type="button" class="gt-submission-tab' + (isActive ? ' active' : '') + '" data-submission-id="' + escGrp(sub.id) + '">'
                    + escGrp(tabLabel) + '</button>';
            });
            subTabsContainer.innerHTML = subTabsHtml;
            subTabsContainer.querySelectorAll('.gt-submission-tab').forEach(function(tab) {
                tab.addEventListener('click', function() {
                    _activeGroupSubmissionId = tab.getAttribute('data-submission-id');
                    window.renderGroupTabs(submissions);
                });
            });
        }

        // ── P7: Fill old #group-tab-container (hidden) for factor navigation compat ──
        var activeFactorAlias = getActiveFactorAliasForSubmission(_activeGroupSubmissionId)
            || (factorList.length > 0 ? (factorList[0].alias || factorList[0].name || '') : null);
        if (activeFactorAlias && _activeGroupSubmissionId) {
            _activeGroupFactorBySubmission[_activeGroupSubmissionId] = activeFactorAlias;
        }

        if (container) {
            var navHtml = '';
            if (factorList.length > 0 && _activeGroupSubmissionId) {
                factorList.forEach(function(f) {
                    var alias = f.alias || f.name || '';
                    var isFactorActive = alias === activeFactorAlias;
                    var cached = getCachedGroupResult(_activeGroupSubmissionId, alias);
                    var status = cached ? (cached.success ? 'done' : 'error') : '';
                    navHtml += '<button type="button" class="group-factor-nav-btn' + (isFactorActive ? ' active' : '')
                        + '" data-submission-id="' + escGrp(_activeGroupSubmissionId)
                        + '" data-factor-alias="' + escGrp(alias)
                        + '" data-run-status="' + status + '" style="display:none;">'
                        + '<span>' + escGrp(alias) + '</span>'
                        + '<span class="group-factor-run-status">' + (status === 'done' ? '✓' : (status === 'error' ? '!' : '')) + '</span>'
                        + '</button>';
                });
            }
            container.innerHTML = navHtml;
        }

        bindGroupFactorTabLongPress();
        bindGroupFactorNavigation();
        restoreActiveGroupResult({ preserveWhenMissingActive: factorList.length === 0 });

        // 当 submissions 到达时，总是重新挂载当前面板。
        // 这确保面板能感知到新的 submission 上下文（如基础组列表按 testerId 筛选）。
        if (submissions.length > 0) {
            // 重新挂载当前 tab（panels/registry.js 已在 init 时注册完毕）
            if (GT.ui.mountTab) {
                GT.ui.mountTab('list');
            }
        }
    };
    function getActiveFactorAliasForSubmission(submissionId) {
        if (_activeGroupFactorBySubmission[submissionId]) return _activeGroupFactorBySubmission[submissionId];
        var activeBtn = document.querySelector('.group-factor-nav-btn.active[data-submission-id="' + cssEscape(String(submissionId)) + '"]');
        if (activeBtn) return activeBtn.getAttribute('data-factor-alias');
        var cached = _groupResultsBySubmission[submissionId];
        if (cached) {
            var first = Object.keys(cached)[0];
            if (first) return first;
        }
        return null;
    }

    function bindGroupSubmissionNavigation(submissions) {
        document.querySelectorAll('.group-submission-nav-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                _activeGroupSubmissionId = btn.getAttribute('data-submission-id');
                window.renderGroupTabs(submissions);
            });
        });
    }

    function bindGroupFactorNavigation() {
        document.querySelectorAll('.group-factor-nav-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                document.querySelectorAll('.group-factor-nav-btn').forEach(function(other) {
                    other.classList.remove('active');
                });
                btn.classList.add('active');
                _activeGroupFactorBySubmission[btn.getAttribute('data-submission-id')] = btn.getAttribute('data-factor-alias');
                restoreActiveGroupResult();
            });
        });
    }

    function restoreActiveGroupResult(options) {
        options = options || {};
        var activeBtn = document.querySelector('.group-factor-nav-btn.active');
        if (!activeBtn) {
            if (!options.preserveWhenMissingActive) {
                clearResults({ clearStatus: false });
            }
            return;
        }
        var sid = activeBtn.getAttribute('data-submission-id');
        var falias = activeBtn.getAttribute('data-factor-alias');
        var result = getCachedGroupResult(sid, falias);
        console.log('[GroupTest] restoreActiveGroupResult: sid=' + sid + ' factor=' + falias + ' cached=' + (result ? result.tester_alias || '(yes, no tester_alias)' : 'no'));
        clearResults({ clearStatus: !result });
        if (result && result.success) {
            applyGroupTestResult(result);
            var statusSpan = document.getElementById('group_test_status');
            if (statusSpan) {
                statusSpan.innerHTML = '✓ 分组测试完成';
                statusSpan.style.color = '#28a745';
            }
        } else if (result && !result.success) {
            var statusEl = document.getElementById('group_test_status');
            if (statusEl) {
                statusEl.innerHTML = '✗ 分组测试失败: ' + (result.error || '未知错误');
                statusEl.style.color = '#d40000';
            }
        }
    }

    // ── 长按因子选项卡辅助函数 ──
    function bindGroupFactorTabLongPress() {
        var helper = window.SingleFactorLibraryHelper;
        if (!helper) return;
        var allFactorTabs = document.querySelectorAll('.group-factor-nav-btn');
        allFactorTabs.forEach(function(btn) {
            helper.bindLongPress(btn, {
                popoverClass: 'group-add-to-library-popover',
                getFactorAlias: function(anchor) {
                    return anchor.getAttribute('data-factor-alias') || anchor.textContent.trim();
                },
                getProductGroup: function(anchor) {
                    return helper.inferScopeFromSubmissionId(anchor.getAttribute('data-submission-id'));
                }
            });
        });
    }

    function escGrp(s) {
        var d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
    // Expose primary entrypoints under GroupTest (namespaced)
    GT.ui.init = init;
    GT.ui.renderTabs = window.renderGroupTabs;

    // ── Submission bus subscriptions ────────────────────────────────────────────
    (function() {
        var bus = window._submissionBus;
        if (!bus) return;

        // React to tester deletion: clean up groups, ls_configs, registrations, caches
        bus.on(bus.EVENTS.REMOVED, function(data) {
            if (!data || !data.id_time) return;
            var removedTesterId = String(data.id_time);

            // 1) Remove all groups referencing this tester (base + derived via cascade)
            if (GT.datamodel && GT.datamodel.groups) {
                var allGroups = GT.datamodel.groups.getAll();
                // First pass: remove all groups (base or derived) that reference this tester
                for (var gi = 0; gi < allGroups.length; gi++) {
                    var g = allGroups[gi];
                    if (String(g.testerId) === removedTesterId) {
                        try {
                            GT.datamodel.groups.remove(g.id); // cascades to descendants
                        } catch(e) {
                            console.warn('[group_test/bus] Failed to remove group:', g.id, e);
                        }
                    }
                }
            }

            // 3) Clear ls_configs (these are tester-scoped)
            if (GT.datamodel && GT.datamodel.ls_configs) {
                try {
                    GT.datamodel.ls_configs._reset();
                } catch(e) {}
            }

            // 4) Clear registrations
            if (GT.datamodel && GT.datamodel.registrations) {
                try {
                    GT.datamodel.registrations._reset();
                } catch(e) {}
            }

            // 5) Clear group result cache for this tester
            if (_groupResultsBySubmission[removedTesterId]) {
                delete _groupResultsBySubmission[removedTesterId];
            }
            if (_activeGroupFactorBySubmission[removedTesterId]) {
                delete _activeGroupFactorBySubmission[removedTesterId];
            }
            if (String(_activeGroupSubmissionId) === removedTesterId) {
                _activeGroupSubmissionId = null;
            }
        });

        // React to any change: re-render tabs
        bus.on('*', function(event) {
            if (window.submissions && window.submissions.length > 0) {
                window.renderGroupTabs(window.submissions);
            } else {
                // Empty state
                var container = document.getElementById('gt-submission-tabs');
                if (container) {
                    container.innerHTML = '<span style="color:#888;font-size:12px;padding:4px 8px;">暂无提交记录</span>';
                }
                var runBtn = document.getElementById('run_group_test_btn');
                if (runBtn) runBtn.style.display = 'none';
            }
        });
    })();

    // ── Datamodel sync bridge (Issue #85 P7) ───────────────────────────────────
    // When new datamodel is available, expose a sync function so that
    // global_template_module.js can push legacy DOM/state into GT.datamodel
    // before calling GT.datamodel.settings.snapshot() during template save.
    GT.ui.syncLegacyStateToDatamodel = function() {
        if (!GT.datamodel || !GT.datamodel.groups ||
            !GT.datamodel.ls_configs || !GT.datamodel.registrations) {
            return false;
        }
        try {
            GT.datamodel.groups._reset();
            GT.datamodel.ls_configs._reset();
            GT.datamodel.registrations._reset();

            // Sync legacy _derivedGroups → datamodel.groups (unified storage)
            if (_derivedGroups && _derivedGroups.length > 0) {
                // Sort: base-only first (no parent or parent==='0'), then by id
                var sortedDerived = _derivedGroups.slice().sort(function(a, b) {
                    var aIsBase = !a.parent || a.parent === '0';
                    var bIsBase = !b.parent || b.parent === '0';
                    if (aIsBase && !bIsBase) return -1;
                    if (!aIsBase && bIsBase) return 1;
                    return (a.id || '').localeCompare(b.id || '');
                });
                sortedDerived.forEach(function(dg) {
                    var parentId = (!dg.parent || dg.parent === '0') ? null : dg.parent;
                    try {
                        GT.datamodel.groups.add({
                            name: dg.name || ('Group ' + dg.id),
                            isDerived: true,
                            parentId: parentId,
                            baseGroupId: dg.baseGroup,
                            productMask: dg.productMask,
                            feeMode: dg.feeMode || 'none',
                            feeRate: dg.feeRate != null ? dg.feeRate : null,
                            feeMap: dg.feeMap != null ? dg.feeMap : null,
                            useCloseToday: dg.useCloseToday !== undefined ? !!dg.useCloseToday : false,
                            rebalanceMode: dg.rebalanceMode || 'each_period'
                        });
                    } catch (e) {
                        console.warn('[app.js syncDatamodel] skip derived group:', dg.id, e.message);
                    }
                });
            }

            // Sync legacy _longShortDefinitions → datamodel.ls_configs
            if (_longShortDefinitions && _longShortDefinitions.length > 0) {
                _longShortDefinitions.forEach(function(ls) {
                    try {
                        GT.datamodel.ls_configs.add({
                            name: ls.name || 'LS-' + ls.id,
                            longGroups: (ls.longGroups || '').toString(),
                            longWeights: (ls.longWeights || '').toString(),
                            shortGroups: (ls.shortGroups || '').toString(),
                            shortWeights: (ls.shortWeights || '').toString()
                        });
                    } catch (e) {
                        console.warn('[app.js syncDatamodel] skip LS config:', ls.id, e.message);
                    }
                });
            }

            return true;
        } catch (e) {
            console.error('[app.js syncDatamodel] error:', e);
            return false;
        }
    };
})();
