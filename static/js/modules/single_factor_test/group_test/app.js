(function(){
    var GT = window.GroupTest;
    if (!GT) { console.warn('[GroupTest] bootstrap missing'); return; }

    if (typeof Highcharts !== 'undefined') {
        Highcharts.setOptions({ global: { useUTC: false } });
    }

    function dates() {
        return (GT.core && GT.core.dateInputs) || {};
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

    function initResearchDetailTabs() {
        var content = document.getElementById('group-detail-content');
        if (!content || content.querySelector('[data-research-tab-bar]')) return;
        var groups = [
            { key: 'overview', label: '概览', titles: ['概览', '收益时序', '自动结论'] },
            { key: 'risk', label: '风险稳定性', titles: ['收益分布', '滚动稳定性', '鲁棒性', '连续正收益区间'] },
            { key: 'portfolio', label: '持仓与归因', titles: ['入组产品', '产品毛收益贡献', '持有期画像'] },
            { key: 'execution', label: '执行与容量', titles: ['组容量风险', '可交易性'] },
            { key: 'timing', label: '时序诊断', titles: ['日历结构', '日期贡献', '具体时段', '日内结构'] },
        ];
        var sections = Array.prototype.slice.call(content.querySelectorAll(':scope > .group-detail-section'));
        sections.forEach(function(section) {
            var title = section.querySelector('.group-detail-section-toggle span');
            var text = title ? title.textContent.trim() : '';
            var owner = groups.find(function(group) { return group.titles.indexOf(text) >= 0; });
            section.setAttribute('data-research-tab', owner ? owner.key : 'risk');
        });
        var bar = document.createElement('div');
        bar.setAttribute('data-research-tab-bar', '');
        bar.setAttribute('role', 'tablist');
        bar.style.cssText = 'display:flex;gap:6px;overflow:auto;position:sticky;top:0;z-index:3;padding:8px 0 12px;background:#fff;';
        function activate(key) {
            sections.forEach(function(section) {
                section.style.display = section.getAttribute('data-research-tab') === key ? '' : 'none';
            });
            bar.querySelectorAll('button').forEach(function(button) {
                var active = button.getAttribute('data-research-tab-button') === key;
                button.className = active ? 'btn btn-sm btn-dark' : 'btn btn-sm btn-outline-secondary';
                button.setAttribute('aria-selected', active ? 'true' : 'false');
            });
        }
        groups.forEach(function(group) {
            var button = document.createElement('button');
            button.type = 'button';
            button.textContent = group.label;
            button.setAttribute('role', 'tab');
            button.setAttribute('data-research-tab-button', group.key);
            button.addEventListener('click', function() { activate(group.key); });
            bar.appendChild(button);
        });
        content.insertBefore(bar, content.firstChild);
        activate('overview');
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

    function initEssential() {
        // Phase 1 loads only the backend tab index. Tab schemas load on first click.
        if (GT.backendSettings && typeof GT.backendSettings.registerSnapshot === 'function') {
            GT.backendSettings.registerSnapshot();
        }
        if (GT.backendSettings && typeof GT.backendSettings.init === 'function') {
            GT.backendSettings.init().catch(function(error) {
                console.error('[GT backend-settings] index load failed', error);
            });
        }
        if (GT.localSettings && typeof GT.localSettings.initTabs === 'function') {
            GT.localSettings.initTabs();
        }

        // Section starts collapsed; toggle is bound after deferred scripts load
        var layerTabs = document.getElementById('gt-layer-tabs');
        var sectionToggle = document.getElementById('gt-section-toggle');
        if (layerTabs && sectionToggle) {
            layerTabs.classList.add('gt-collapsed');
            sectionToggle.style.transform = 'rotate(-90deg)';
        }
    }

    function initDeferred() {
        // ── Phase 2: runs after all 40 deferred scripts are loaded ──
        if (GT._deferredInitDone) return;
        GT._deferredInitDone = true;

        if (GT.fee && typeof GT.fee.bind === 'function') GT.fee.bind();

        if (GT.backendSettings && typeof GT.backendSettings.attachGroupTabs === 'function') {
            GT.backendSettings.attachGroupTabs();
        }

        window._getFeeModifications = function() {
            if (GT.fee && typeof GT.fee.getModifications === 'function') return GT.fee.getModifications();
            return {};
        };
        window._applyFeeModifications = function(mods) {
            if (GT.fee && typeof GT.fee.applyModifications === 'function') GT.fee.applyModifications(mods);
        };

        if (GT.results && GT.results.snapshot && typeof GT.results.snapshot.bindSnapshotDrawerEvents === 'function') {
            GT.results.snapshot.bindSnapshotDrawerEvents();
        }

        bindGroupDetailOverlayChrome();
        bindLegacyLongShortDrawerChrome();
        bindGroupSectionToggles();
        initResearchDetailTabs();

        var chipToggle = document.getElementById('gt-toggle-config-chips');
        var groupModule = document.getElementById('group_test_module');
        if (chipToggle && groupModule) {
            chipToggle.addEventListener('click', function() {
                var hidden = groupModule.classList.toggle('gt-hide-config-chips');
                chipToggle.textContent = hidden ? '显示设置标签' : '隐藏设置标签';
                chipToggle.setAttribute('aria-pressed', hidden ? 'true' : 'false');
            });
        }

        if (GT.panels && GT.panels.actions && typeof GT.panels.actions.updateRebalanceModeDescription === 'function') {
            GT.panels.actions.updateRebalanceModeDescription();
        }

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

        // Bind section toggle (only after everything is ready)
        var sectionHeader = document.getElementById('gt-section-header');
        var sectionToggle = document.getElementById('gt-section-toggle');
        var layerTabs = document.getElementById('gt-layer-tabs');
        if (sectionHeader && layerTabs && sectionToggle) {
            sectionHeader.removeAttribute('onclick');
            sectionHeader._toggleHandler = function() {
                var collapsed = layerTabs.classList.toggle('gt-collapsed');
                sectionToggle.style.transform = collapsed ? 'rotate(-90deg)' : 'rotate(0deg)';
                if (!collapsed) layerTabs.scrollIntoView({ behavior: 'smooth', block: 'start' });
            };
            sectionHeader.addEventListener('click', sectionHeader._toggleHandler);

            // Expand section now that everything is ready
            layerTabs.classList.remove('gt-collapsed');
            sectionToggle.style.transform = 'rotate(0deg)';
            setTimeout(function() { layerTabs.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, 100);
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

    GT.initEssential = initEssential;
    GT.initDeferred = initDeferred;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initEssential);
    } else {
        initEssential();
    }
})();
