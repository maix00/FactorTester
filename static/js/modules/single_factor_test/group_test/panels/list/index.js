/**
 * panels/list/index.js — Unified group list panel orchestrator.
 *
 * This file intentionally contains no row HTML and no per-control event logic.
 * Those live in:
 *   - selection-state.js  → selected group ids
 *   - helpers.js          → shared list-domain helpers/cache
 *   - render.js           → LS/base/derived list HTML and modals
 *   - events.js           → click handlers and edit-mode sync
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');

    GT.panels = GT.panels || {};
    GT.panels.list = GT.panels.list || {};

    var CONTAINER_ID = 'unified-group-list';
    var _mounted = false;
    var _container = null;
    var _containerDelegate = null;
    var _unbinders = [];
    var _expandedBatches = {};
    var _lsSectionExpanded = { val: false };

    function deps() {
        var list = GT.panels && GT.panels.list;
        if (!list) throw new Error('GT.panels.list not initialized');
        if (!list.selection) throw new Error('panels/list/selection-state.js must load before index.js');
        if (!list._helpers) throw new Error('panels/list/helpers.js must load before index.js');
        if (!list.render) throw new Error('panels/list/render.js must load before index.js');
        if (!list.events) throw new Error('panels/list/events.js must load before index.js');
        return {
            SEL: list.selection,
            H: list._helpers,
            R: list.render,
            E: list.events,
        };
    }

    function stateBus() {
        return GT.events || {
            on: function(){},
            off: function(){},
        };
    }

    function groupSettings() {
        return GT.groupSettings || {};
    }

    function getContainer(containerEl) {
        if (containerEl && typeof containerEl !== 'string') return containerEl;
        return document.getElementById(containerEl || CONTAINER_ID);
    }

    function renderBaseList(d, container) {
        var groups = groupSettings().groups;
        var lsConfigs = groupSettings().lsConfigs;
        var hasGroups = groups && typeof groups.getAll === 'function';
        var hasLS = lsConfigs && typeof lsConfigs.getAll === 'function';

        if (!hasGroups || !hasLS) {
            container.innerHTML = '<div style="padding:16px;text-align:center;color:#d40000;">分组设置模块尚未加载</div>';
            return;
        }

        d.H.invalidateExpandCaches();
        var lsHtml = d.R.renderLSSection(_lsSectionExpanded.val);
        var baseHtml = d.R.renderBaseSection(_expandedBatches);
        container.innerHTML = '<div id="unified-list-container">'
            + (lsHtml ? lsHtml + '<div style="margin-top:16px;">' + baseHtml + '</div>' : baseHtml)
            + '</div>';
    }

    function fullRender() {
        if (!_mounted || !_container) return;
        var d = deps();
        d.R._setSEL(d.SEL);
        d.E._setSEL(d.SEL);
        renderBaseList(d, _container);
        d.E.bindEvents(_container, {
            fullRender: fullRender,
            expandedBatches: _expandedBatches,
            lsSectionExpanded: _lsSectionExpanded,
            getBatchMap: d.H.getBatchMap,
        });
    }

    function addStateListener(eventName, handler) {
        var bus = stateBus();
        if (!bus || typeof bus.on !== 'function') return;
        bus.on(eventName, handler);
        _unbinders.push(function() {
            if (bus && typeof bus.off === 'function') bus.off(eventName, handler);
        });
    }

    function addSelectionListener(selection, handler) {
        if (!selection || typeof selection.on !== 'function') return;
        selection.on('selectionChanged', handler);
        _unbinders.push(function() {
            if (selection && typeof selection.off === 'function') selection.off('selectionChanged', handler);
        });
    }

    function bindLifecycleListeners(d) {
        var rerender = function() { fullRender(); };
        ['lsConfigsChanged', 'groupsChanged', 'derivedGraphChanged', 'feeDataChanged'].forEach(function(eventName) {
            addStateListener(eventName, rerender);
        });
        addSelectionListener(d.SEL, rerender);
    }

    function mount(containerEl) {
        unmount();
        _container = getContainer(containerEl);
        if (!_container) return;
        _mounted = true;

        var d = deps();
        d.R._setSEL(d.SEL);
        d.E._setSEL(d.SEL);
        _containerDelegate = d.E.buildContainerDelegate(_expandedBatches, _lsSectionExpanded, fullRender);
        _container.addEventListener('click', _containerDelegate);
        _unbinders.push(function() {
            if (_container && _containerDelegate) {
                _container.removeEventListener('click', _containerDelegate);
            }
            _containerDelegate = null;
        });

        bindLifecycleListeners(d);
        fullRender();
    }

    function unmount() {
        for (var i = _unbinders.length - 1; i >= 0; i--) {
            try { _unbinders[i](); } catch (_) {}
        }
        _unbinders = [];
        _mounted = false;
        _container = null;
        _containerDelegate = null;
    }

    var api = {
        mount: mount,
        unmount: unmount,
        refresh: fullRender,
        _openLSForm: function(editData) {
            var d = deps();
            d.R.lsShowModal(editData);
        },
    };

    GT.panels.list.index = api;
})();
