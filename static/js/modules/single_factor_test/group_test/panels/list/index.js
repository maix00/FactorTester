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

    function _buildSnapshotMatrixColumns(groups) {
        var d = deps();
        var H = d.H;
        var sourceGroups = Array.isArray(groups) ? groups : [];
        if (!sourceGroups.length && GT.groupSettings && GT.groupSettings.groups && typeof GT.groupSettings.groups.getAll === 'function') {
            sourceGroups = GT.groupSettings.groups.getAll() || [];
        }
        if (!sourceGroups.length) return [];

        var indexById = {};
        for (var i = 0; i < sourceGroups.length; i++) {
            var g = sourceGroups[i];
            if (g && g.id) indexById[g.id] = i;
        }

        var childrenById = {};
        for (var j = 0; j < sourceGroups.length; j++) {
            var item = sourceGroups[j];
            if (!item || !item.parentId) continue;
            if (!childrenById[item.parentId]) childrenById[item.parentId] = [];
            childrenById[item.parentId].push(item);
        }

        var batches = H.buildAddGroupBatches(sourceGroups);
        var columns = [];

        function walk(node, depth, batchKey, batchExpanded) {
            if (!node) return;
            var sourceIndex = indexById[node.id];
            if (sourceIndex == null) return;
            var hasChildren = !!(childrenById[node.id] && childrenById[node.id].length);
            var expanded = node._expanded !== false;
            columns.push({
                sourceIndex: sourceIndex,
                group: node,
                depth: depth,
                batchKey: batchKey,
                batchExpanded: batchExpanded,
                hasChildren: hasChildren,
                expanded: expanded,
                label: node.shortAlias || node.name || node.id || ('Group ' + (sourceIndex + 1)),
            });
            if (!hasChildren || !expanded) return;
            var children = childrenById[node.id];
            for (var ci = 0; ci < children.length; ci++) {
                walk(children[ci], depth + 1, batchKey, batchExpanded);
            }
        }

        for (var bi = 0; bi < batches.length; bi++) {
            var batch = batches[bi];
            for (var ri = 0; ri < batch.items.length; ri++) {
                walk(batch.items[ri], 0, batch.key, batches.length === 1 ? true : (_expandedBatches[batch.key] === true));
            }
        }

        return columns;
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
            getAddGroupBatchMap: d.H.getAddGroupBatchMap,
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

    function getSnapshotMatrixColumns(groups) {
        return _buildSnapshotMatrixColumns(groups);
    }

    var api = {
        mount: mount,
        unmount: unmount,
        refresh: fullRender,
        getSnapshotMatrixColumns: getSnapshotMatrixColumns,
        getExpansionState: function() {
            return {
                expandedBatches: JSON.parse(JSON.stringify(_expandedBatches || {})),
                lsSectionExpanded: !!_lsSectionExpanded.val,
            };
        },
        setBatchExpanded: function(batchKey, expanded) {
            if (!batchKey) return;
            _expandedBatches[batchKey] = !!expanded;
            fullRender();
        },
        toggleBatchExpanded: function(batchKey) {
            if (!batchKey) return false;
            _expandedBatches[batchKey] = !_expandedBatches[batchKey];
            fullRender();
            return _expandedBatches[batchKey];
        },
        setLSSectionExpanded: function(expanded) {
            _lsSectionExpanded.val = !!expanded;
            fullRender();
        },
        _openLSForm: function(editData) {
            var d = deps();
            d.R.lsShowModal(editData);
        },
    };

    GT.panels.list.index = api;
})();
