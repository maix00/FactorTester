(function(){
    var GT = window.GroupTest;
    if (!GT) { console.warn('[GroupTest] bootstrap missing'); return; }

    GT.ui = GT.ui || {};

    if (typeof Highcharts !== 'undefined') {
        Highcharts.setOptions({ global: { useUTC: false } });
    }

    function dates() {
        return (GT.core && GT.core.dates) || {};
    }

    function cache() {
        return GT.core && GT.core.cache ? GT.core.cache : null;
    }

    function call(fn, fallback) {
        return typeof fn === 'function' ? fn : fallback;
    }

    GT.ui._readGroupTimeRangeInput = function() {
        return call(dates().readGroupTimeRangeInput, function(){ return { startDate: null, endDate: null }; })();
    };
    GT.ui._resolveGroupRunTimeRange = function() {
        return call(dates().resolveGroupRunTimeRange, function(){ return { startDate: null, endDate: null }; })();
    };

    GT.results = GT.results || {};
    GT.results.detailOverlay = GT.results.detailOverlay || {};
    GT.results.detailOverlay.hostRefs = {
        get _lastGrossData() {
            var c = cache();
            return c ? c.getLastGrossData() : null;
        },
        get _lastMetrics() {
            var c = cache();
            return c ? c.getLastMetrics() : null;
        },
        get _currentGroupDetailIndex() {
            var c = cache();
            return c ? c.getCurrentGroupDetailIndex() : null;
        },
        set _currentGroupDetailIndex(value) {
            var c = cache();
            if (c) c.setCurrentGroupDetailIndex(value);
        },
        onRenderDerivedPanel: function(groupIndex) {
            if (GT.panels && GT.panels.actions && typeof GT.panels.actions.renderDerivedGroupsPanel === 'function') {
                GT.panels.actions.renderDerivedGroupsPanel(groupIndex);
            }
        },
    };

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
            if (window.submissions && window.submissions.length > 0 && GT.ui.mountTab) {
                GT.ui.mountTab('list');
            }
        });
    }

    function init() {
        call(dates().bindDateValidation, function(){})();
        call(dates().bindUseTimeRange, function(){})();
        call(dates().bindTimeSyncListeners, function(){})();

        if (GT.fee && typeof GT.fee.bind === 'function') GT.fee.bind();
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
        if (runBtn) runBtn.addEventListener('click', function() {
            if (GT.core && GT.core.runTest) GT.core.runTest.runGroupTest();
        });
        var defaultBtn = document.getElementById('load_default_groups_btn');
        if (defaultBtn) defaultBtn.addEventListener('click', function() {
            if (GT.core && GT.core.runTest) GT.core.runTest.loadDefaultGroups();
        });
        var rebalanceSelect = document.getElementById('rebalance_mode');
        if (rebalanceSelect) rebalanceSelect.addEventListener('change', function() {
            if (GT.panels && GT.panels.actions && typeof GT.panels.actions.updateRebalanceModeDescription === 'function') {
                GT.panels.actions.updateRebalanceModeDescription();
            }
        });

        if (GT.panels && GT.panels.registry && typeof GT.panels.registry.init === 'function') {
            GT.panels.registry.init();
        }
        if (window.submissions && window.submissions.length > 0 && GT.ui.mountTab) {
            GT.ui.mountTab('list');
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
                if (event.target === panelContainer && GT.ui.getPanelMode && GT.ui.getPanelMode() === 'edit' && GT.ui.exitEditMode) {
                    GT.ui.exitEditMode();
                }
            });
        }

        bindSubmissionBus();
    }

    GT.ui.init = init;
    GT.ui.syncLegacyStateToDatamodel = function() {
        return !!(GT.groupSettings && GT.groupSettings.groups && GT.groupSettings.lsConfigs);
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
