(function(){
    var GT = window.GroupTest;
    if (!GT) { console.warn('[GroupTest] bootstrap missing'); return; }

    if (typeof Highcharts !== 'undefined') {
        Highcharts.setOptions({ global: { useUTC: false } });
    }

    function dates() {
        return (GT.core && GT.core.dates) || {};
    }

    function cache() {
        return GT.groupSettings && GT.groupSettings.cache ? GT.groupSettings.cache : null;
    }

    function call(fn, fallback) {
        return typeof fn === 'function' ? fn : fallback;
    }

    function bindGroupDetailOverlayChrome() {
        var overlay = document.getElementById('group-detail-overlay');
        var closeBtn = document.getElementById('group-detail-close');
        if (closeBtn) closeBtn.addEventListener('click', function() {
            if (overlay) overlay.classList.remove('open');
        });
        if (overlay) overlay.addEventListener('click', function(event) {
            if (event.target === overlay) overlay.classList.remove('open');
        });

        var rankingOverlay = document.getElementById('group-ranking-overlay');
        var rankingCloseBtn = document.getElementById('group-ranking-close');
        if (rankingCloseBtn) rankingCloseBtn.addEventListener('click', function() {
            if (rankingOverlay) rankingOverlay.classList.remove('open');
        });
        if (rankingOverlay) rankingOverlay.addEventListener('click', function(event) {
            if (event.target === rankingOverlay) rankingOverlay.classList.remove('open');
        });
    }

    function bindLegacyLongShortDrawerChrome() {
        var overlay = document.getElementById('long-short-drawer');
        var openBtn = document.getElementById('long-short-drawer-trigger');
        var closeBtn = document.getElementById('long-short-drawer-close');
        var addBtn = document.getElementById('long-short-add-btn');

        if (openBtn) openBtn.addEventListener('click', function() {
            if (GT.panels && GT.panels.actions) {
                if (typeof GT.panels.actions.renderLongShortConfigList === 'function') GT.panels.actions.renderLongShortConfigList();
                if (typeof GT.panels.actions.updateLongShortSummary === 'function') GT.panels.actions.updateLongShortSummary();
            }
            if (overlay) overlay.classList.add('open');
        });
        if (closeBtn) closeBtn.addEventListener('click', function() {
            if (overlay) overlay.classList.remove('open');
        });
        if (overlay) overlay.addEventListener('click', function(event) {
            if (event.target === overlay) overlay.classList.remove('open');
        });
        if (addBtn) addBtn.addEventListener('click', function() {
            var c = cache();
            var definitions = c ? c.getLongShortDefinitions() : [];
            definitions.push({
                id: 'LS' + Date.now(),
                name: 'Long-Short ' + definitions.length,
                longGroups: '1',
                longWeights: '1',
                shortGroups: '',
                shortWeights: '1',
            });
            if (c) c.setLongShortDefinitions(definitions);
            if (GT.panels && GT.panels.actions) {
                if (typeof GT.panels.actions.renderLongShortConfigList === 'function') GT.panels.actions.renderLongShortConfigList();
                if (typeof GT.panels.actions.updateLongShortSummary === 'function') GT.panels.actions.updateLongShortSummary();
            }
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

    function bindSubmissionBus() {
        var bus = window._submissionBus;
        if (!bus || typeof bus.on !== 'function') return;

        bus.on(bus.EVENTS && bus.EVENTS.REMOVED, function(data) {
            if (!data || !data.id_time) return;
            var removedTesterId = String(data.id_time);
            if (GT.groupSettings && GT.groupSettings.groups) {
                GT.groupSettings.groups.getAll().forEach(function(group) {
                    if (String(group.testerId) !== removedTesterId) return;
                    try { GT.groupSettings.groups.remove(group.id); }
                    catch (err) { console.warn('[group_test/bus] Failed to remove group:', group.id, err); }
                });
            }
            if (GT.groupSettings && GT.groupSettings.lsConfigs) {
                try { GT.groupSettings.lsConfigs._reset(); } catch (_) {}
            }
        });

        bus.on('*', function() {
            if (window.submissions && window.submissions.length > 0 && GT.tabs && GT.tabs.mountTab) {
                GT.tabs.mountTab('list');
            }
        });
    }

    function init() {
        call(dates().bindDateValidation, function(){})();
        call(dates().bindUseTimeRange, function(){})();
        call(dates().bindTimeSyncListeners, function(){})();

        if (GT.fee && typeof GT.fee.bind === 'function') GT.fee.bind();

        // Bridge: global_template_module.js snapshots use these globals
        window._getFeeModifications = function() {
            if (GT.fee && typeof GT.fee.getModifications === 'function') return GT.fee.getModifications();
            return {};
        };
        window._applyFeeModifications = function(mods) {
            if (GT.fee && typeof GT.fee.applyModifications === 'function') GT.fee.applyModifications(mods);
        };

        if (GT.results.snapshot && typeof GT.results.snapshot.bindSnapshotDrawerEvents === 'function') {
            GT.results.snapshot.bindSnapshotDrawerEvents();
        }

        bindGroupDetailOverlayChrome();
        bindLegacyLongShortDrawerChrome();
        bindGroupSectionToggles();

        if (GT.panels && GT.panels.actions && typeof GT.panels.actions.updateRebalanceModeDescription === 'function') {
            GT.panels.actions.updateRebalanceModeDescription();
        }
        call(dates().syncFromTimeModule, function(){})();
        document.addEventListener('timeRangeDefaultLoaded', function() {
            call(dates().syncFromTimeModule, function(){})();
        }, { once: true });
        setTimeout(function() { call(dates().syncFromTimeModule, function(){})(); }, 0);

        var runBtn = document.getElementById('run_group_test_btn');
        if (runBtn) {
            runBtn.addEventListener('click', function() {
                console.log('[GT] run_group_test_btn clicked');
                if (GT.core && GT.core.runTest && typeof GT.core.runTest.runGroupTest === 'function') {
                    try {
                        GT.core.runTest.runGroupTest();
                    } catch(e) {
                        console.error('[GT] runGroupTest error:', e);
                    }
                } else {
                    console.warn('[GT] GT.core.runTest.runGroupTest not available', {
                        core: !!GT.core,
                        runTest: !!(GT.core && GT.core.runTest),
                        runGroupTest: typeof (GT.core && GT.core.runTest && GT.core.runTest.runGroupTest)
                    });
                }
            });
            runBtn.style.display = '';
        }
        var defaultBtn = document.getElementById('load_default_groups_btn');
        if (defaultBtn) {
            defaultBtn.addEventListener('click', function() {
                console.log('[GT] load_default_groups_btn clicked');
                if (GT.core && GT.core.runTest && typeof GT.core.runTest.loadDefaultGroups === 'function') {
                    try {
                        GT.core.runTest.loadDefaultGroups();
                    } catch(e) {
                        console.error('[GT] loadDefaultGroups error:', e);
                    }
                } else {
                    console.warn('[GT] loadDefaultGroups not available');
                }
            });
            defaultBtn.style.display = '';
        }
        var rebalanceSelect = document.getElementById('rebalance_mode');
        if (rebalanceSelect) rebalanceSelect.addEventListener('change', function() {
            if (GT.panels && GT.panels.actions && typeof GT.panels.actions.updateRebalanceModeDescription === 'function') {
                GT.panels.actions.updateRebalanceModeDescription();
            }
        });

        if (GT.tabs && typeof GT.tabs.init === 'function') {
            GT.tabs.init();
        }
        if (window.submissions && window.submissions.length > 0 && GT.tabs && GT.tabs.mountTab) {
            GT.tabs.mountTab('list');
        }

        var sectionHeader = document.getElementById('gt-section-header');
        var sectionToggle = document.getElementById('gt-section-toggle');
        var layerTabs = document.getElementById('gt-layer-tabs');
        if (sectionHeader && layerTabs && sectionToggle) {
            sectionHeader.removeAttribute('onclick');
            sectionHeader.addEventListener('click', function() {
                var collapsed = layerTabs.classList.toggle('gt-collapsed');
                sectionToggle.style.transform = collapsed ? 'rotate(-90deg)' : 'rotate(0deg)';
                if (!collapsed) layerTabs.scrollIntoView({ behavior: 'smooth', block: 'start' });
            });
            layerTabs.classList.add('gt-collapsed');
            sectionToggle.style.transform = 'rotate(-90deg)';
        }

        var panelContainer = document.getElementById('gt-panel-container');
        if (panelContainer) {
            panelContainer.addEventListener('click', function(event) {
                if (event.target === panelContainer && GT.tabs && GT.tabs.getPanelMode && GT.tabs.getPanelMode() === 'edit' && GT.tabs.exitEditMode) {
                    GT.tabs.exitEditMode();
                }
            });
        }

        bindSubmissionBus();
    }

    GT.init = init;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
