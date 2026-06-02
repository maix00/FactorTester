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
        }

        // 画图 + 指标表
        drawGroupChart(data.groups);
        renderMetricsTable(data.metrics);
    }

    // 桥接到 runner.js
    function postGroupTest(payload) { return GT.core.actions.runner.postGroupTest(payload); }
    function postBatchGroupTest(payload) { return GT.core.actions.runner.postBatchGroupTest(payload); }

    // 桥接到 runner.js
    async function loadDefaultGroups() { return GT.core.actions.runner.loadDefaultGroups(); }

    // 桥接到 runner.js
    async function runGroupTest() { return GT.core.actions.runner.runGroupTest(); }

    // 桥接到 runner.js
    async function runAllGroupTestsForCurrentSubmission() { return GT.core.actions.runner.runAllGroupTestsForCurrentSubmission(); }

    var _currentGroupDetailIndex = GT.core.cache ? GT.core.cache.getCurrentGroupDetailIndex() : null;
    var _longShortDefinitions = GT.core.cache ? GT.core.cache.getLongShortDefinitions() : [defaultLongShortDefinition()];
    var _lastGroupStructureKey = GT.core.cache ? GT.core.cache.getLastGroupStructureKey() : null;
    var _lastGrossData = GT.core.cache ? GT.core.cache.getLastGrossData() : null;
    var _lastMetrics = GT.core.cache ? GT.core.cache.getLastMetrics() : null;
    var _lastTimestamps = GT.core.cache ? GT.core.cache.getLastTimestamps() : [];
    var _lastNgroups = GT.core.cache ? GT.core.cache.getLastNgroups() : 0;

    // ═══ Panel registry — unified flat tab list ═══

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

        // 当 submissions 到达时，重新挂载当前面板
        if (window.submissions && window.submissions.length > 0 && GT.ui.mountTab) {
            GT.ui.mountTab('list');
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
            if (GT.core && GT.core.cache) GT.core.cache.setLongShortDefinitions(_longShortDefinitions);
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



    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
    // Expose primary entrypoints under GroupTest (namespaced)
    GT.ui.init = init;

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

            // 5) Group caches already handled at cache layer (GT.core.cache removed)
        });

        // React to any change: re-mount active panel
        bus.on('*', function(event) {
            if (window.submissions && window.submissions.length > 0 && GT.ui.mountTab) {
                GT.ui.mountTab('list');
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
