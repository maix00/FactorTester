/**
 * panels/list/selection-state.js — 分组多选状态
 *
 * 管理选中的 group ID 集合（base + derived 统一），提供：
 *   - toggle(id)          单个 toggle
 *   - setBatch(ids)       批量替换（用于 batch header 全选/取消）
 *   - clear()             清空
 *   - isSelected(id)      是否选中
 *   - getAll()            所有选中 id 数组
 *   - getFirst()          第一个选中 id
 *
 * 事件（挂载到自身）：
 *   - selectionChanged    { ids: [...] }
 *
 * 挂载到 GT.panels.list.selection
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');

    GT.panels = GT.panels || {};
    GT.panels.list = GT.panels.list || {};
    if (GT.panels.list.selection) { console.warn('[selection-state] already loaded'); return; }

    var _ids = {};          // { id: true }
    var _listeners = {};

    function emit(event, data) {
        var cbs = _listeners[event] || [];
        for (var i = 0; i < cbs.length; i++) {
            try { cbs[i](data); } catch (_) {}
        }
    }

    function _emitChange() {
        emit('selectionChanged', { ids: Object.keys(_ids) });
    }

    /** Toggle 单个 group id */
    function toggle(id) {
        if (_ids[id]) {
            delete _ids[id];
        } else {
            _ids[id] = true;
        }
        _emitChange();
    }

    /** 批量替换整个选中集（batch header 全选/取消） */
    function setBatch(ids) {
        _ids = {};
        for (var i = 0; i < ids.length; i++) {
            _ids[ids[i]] = true;
        }
        _emitChange();
    }

    /** 添加单个 id（不 toggle，用于批次选中等场景） */
    function add(id) {
        _ids[id] = true;
        _emitChange();
    }

    /** 移除单个 id */
    function remove(id) {
        delete _ids[id];
        _emitChange();
    }

    function clear() {
        var hadAny = Object.keys(_ids).length > 0;
        _ids = {};
        if (hadAny) _emitChange();
    }

    function isSelected(id) {
        return !!_ids[id];
    }

    function getAll() {
        return Object.keys(_ids);
    }

    function getFirst() {
        var keys = Object.keys(_ids);
        return keys.length > 0 ? keys[0] : null;
    }

    function count() {
        return Object.keys(_ids).length;
    }

    function _groupById(id) {
        return id && GT.groupSettings && GT.groupSettings.groups && typeof GT.groupSettings.groups.get === 'function'
            ? GT.groupSettings.groups.get(id)
            : null;
    }

    function getFirstGroup() {
        return _groupById(getFirst());
    }

    function getFirstBaseGroup() {
        var group = getFirstGroup();
        if (!group) return null;
        if (!group.parentId) return group;
        // Walk parentId chain to root
        var cur = group;
        var visited = {};
        while (cur && cur.parentId) {
            if (visited[cur.id]) return group; // cycle, return original
            visited[cur.id] = true;
            cur = _groupById(cur.parentId);
        }
        return cur || group;
    }

    function getFirstProductPathSelectionId() {
        var group = getFirstBaseGroup();
        var selection = group && group.product_path_selection;
        return selection ? String(selection.product_path_selection_id || selection.selection_id || selection.id || '') : null;
    }

    function getFirstFactorAlias() {
        var group = getFirstBaseGroup();
        return group ? (group.factorAlias || '') : '';
    }

    function on(event, callback) {
        if (!_listeners[event]) { _listeners[event] = []; }
        _listeners[event].push(callback);
    }

    function off(event, callback) {
        if (!_listeners[event]) return;
        if (!callback) { delete _listeners[event]; return; }
        _listeners[event] = _listeners[event].filter(function(cb) { return cb !== callback; });
    }

    // -- 挂载 --
    var api = {
        toggle: toggle,
        setBatch: setBatch,
        add: add,
        remove: remove,
        clear: clear,
        isSelected: isSelected,
        getAll: getAll,
        getFirst: getFirst,
        getFirstGroup: getFirstGroup,
        getFirstBaseGroup: getFirstBaseGroup,
        getFirstProductPathSelectionId: getFirstProductPathSelectionId,
        getFirstFactorAlias: getFirstFactorAlias,
        count: count,
        on: on,
        off: off,
    };
    GT.panels.list.selection = api;

    GT.events = {
        emit: emit,
        on: on,
        off: off,
    };
})();
