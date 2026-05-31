/**
 * test_panels_base_fee.js — Node.js tests for panels/base/fee.js
 */

var passed = 0, failed = 0;

function assert(condition, msg) {
    if (condition) { passed++; }
    else { console.log('FAIL: ' + msg); failed++; }
}

function assertEquals(actual, expected, msg) {
    if (JSON.stringify(actual) === JSON.stringify(expected)) { passed++; }
    else { console.log('FAIL: ' + msg + '\n  expected: ' + JSON.stringify(expected) + '\n  actual:   ' + JSON.stringify(actual)); failed++; }
}

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

var mockBG = [];
var _uiUpdates = [];     // track calls to base_groups.update

function resetAll() {
    mockBG = [];
    _uiUpdates = [];
    _domElements = {};
    _bodyHTML = '';
    global._mockActiveBGId = null;
    global._confirmResult = true;
}

// ---------------------------------------------------------------------------
// Mock DOM
// ---------------------------------------------------------------------------

var _domElements = {};
var _bodyHTML = '';

global.document = {
    getElementById: function(id) {
        return _domElements[id] || null;
    },
    body: {
        insertAdjacentHTML: function(pos, html) {
            _bodyHTML += html;
        },
    },
};

function _makeContainer(id) {
    var el = {
        id: id,
        _html: '',
        _listeners: {},
        get innerHTML() { return this._html; },
        set innerHTML(v) { this._html = v; },
        querySelectorAll: function(sel) { return []; },
        querySelector: function(sel) { return null; },
        addEventListener: function(evt, fn) {
            if (!this._listeners[evt]) this._listeners[evt] = [];
            this._listeners[evt].push(fn);
        },
        _fire: function(evt, e) {
            var fns = this._listeners[evt] || [];
            for (var i = 0; i < fns.length; i++) fns[i](e || {});
        },
    };
    _domElements[id] = el;
    return el;
}

global.confirm = function() { return global._confirmResult; };
global.alert = function() {};

// ---------------------------------------------------------------------------
// Mock window.GroupTest
// ---------------------------------------------------------------------------

global._mockActiveBGId = null;
global._events = {};

global.window = {
    GroupTest: {
        datamodel: {
            base_groups: {
                get: function(id) {
                    for (var i = 0; i < mockBG.length; i++) {
                        if (mockBG[i].id === id) return JSON.parse(JSON.stringify(mockBG[i]));
                    }
                    return null;
                },
                getAll: function() { return JSON.parse(JSON.stringify(mockBG)); },
                update: function(id, patch) {
                    _uiUpdates.push({ id: id, patch: JSON.parse(JSON.stringify(patch)) });
                    for (var i = 0; i < mockBG.length; i++) {
                        if (mockBG[i].id === id) {
                            Object.keys(patch).forEach(function(k) { mockBG[i][k] = patch[k]; });
                            return JSON.parse(JSON.stringify(mockBG[i]));
                        }
                    }
                    throw new Error('not found: ' + id);
                },
            },
        },
        state: {
            on: function(evt, fn) {
                if (!global._events[evt]) global._events[evt] = [];
                global._events[evt].push(fn);
            },
            off: function(evt, fn) {
                var arr = global._events[evt] || [];
                var idx = arr.indexOf(fn);
                if (idx !== -1) arr.splice(idx, 1);
            },
            emit: function(evt, data) {
                var arr = global._events[evt] || [];
                for (var i = 0; i < arr.length; i++) arr[i](data);
            },
            getActiveBaseGroupId: function() { return global._mockActiveBGId; },
            setActiveBaseGroupId: function(id) { global._mockActiveBGId = id; },
        },
        panels: {},
        log: function() {},
        ui: {
            getPanelMode: function() { return 'list'; },
            getAddDraft: function() { return null; },
            getEditSelection: function() { return null; },
            updateAddDraft: function() {},
        },
    },
    GT_CONFIG_REGISTRY: {
        _items: {},
        register: function(def, containerId) {
            this._items[def.name] = { def: def, containerId: containerId };
        },
        getAll: function() { return Object.values(this._items); },
        getTableColumns: function() {
            var cols = [];
            Object.values(this._items).forEach(function(entry) {
                if (entry.def.panel && entry.def.panel.getTableColumns) {
                    cols = cols.concat(entry.def.panel.getTableColumns());
                }
            });
            return cols;
        },
        toPanelEntry: function(name, label, containerId) {
            return { name: name, label: label, containerId: containerId, category: 3, panel: this._items[name].def.panel };
        },
    },
};

// ---------------------------------------------------------------------------
// Load module
// ---------------------------------------------------------------------------

require('../../static/js/modules/single_factor_test/group_test/panels/base/fee.js');

var GT = window.GroupTest;
var panel = GT.panels.base.fee;

// We need a helper to simulate DOM after render (since querySelector is called in _bindEvents)
function _simulateRender() {
    // After render, we manually call the bindEvents behavior
    // The test controls mockBG to set up data
}

// ---------------------------------------------------------------------------
// 1. Module exports
// ---------------------------------------------------------------------------

resetAll();
assert(typeof panel === 'object', 'exports: panel is object');
assert(typeof panel.mount === 'function', 'exports: mount exists');
assert(typeof panel.unmount === 'function', 'exports: unmount exists');
assert(typeof panel.refresh === 'function', 'exports: refresh exists');
assert(typeof panel.render === 'function', 'exports: render exists');

// ---------------------------------------------------------------------------
// 2. render — no active group
// ---------------------------------------------------------------------------

resetAll();
_makeContainer('base-fee-settings');
panel.render();
var html = _domElements['base-fee-settings']._html;
assert(html.indexOf('请先在「列表」中选择或创建一个基础组') !== -1, 'no active: shows placeholder');

// ---------------------------------------------------------------------------
// 3. render — none mode (default)
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Test', testerId: 't', factorAlias: 'f', groupCount: 5, groupIndex: 0, feeMode: 'none' });
global._mockActiveBGId = 'bg_1';
_makeContainer('base-fee-settings');
panel.render();
html = _domElements['base-fee-settings']._html;
assert(html.indexOf('费率模式') !== -1, 'render none: shows mode selector');
assert(html.indexOf('value="none"') !== -1, 'render none: has none radio');
assert(html.indexOf('checked') !== -1, 'render none: none is checked');
// Uniform editor should NOT appear for 'none' mode
assert(html.indexOf('base-fee-settings-uniform-editor') === -1, 'render none: no uniform editor');

// ---------------------------------------------------------------------------
// 4. render — uniform mode
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Test', testerId: 't', factorAlias: 'f', groupCount: 5, groupIndex: 0, feeMode: 'uniform', feeRate: 2.5 });
global._mockActiveBGId = 'bg_1';
_makeContainer('base-fee-settings');
panel.render();
html = _domElements['base-fee-settings']._html;
assert(html.indexOf('base-fee-settings-uniform-editor') !== -1, 'render uniform: shows editor');
assert(html.indexOf('value="2.5"') !== -1, 'render uniform: rate is 2.5');
assert(html.indexOf('base-fee-settings-feerate') !== -1, 'render uniform: has feerate input');

// ---------------------------------------------------------------------------
// 5. render — per_product mode
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Test', testerId: 't', factorAlias: 'f', groupCount: 5, groupIndex: 0, feeMode: 'per_product', feeMap: { 'ag': 1.5, 'rb': 2.0 } });
global._mockActiveBGId = 'bg_1';
_makeContainer('base-fee-settings');
panel.render();
html = _domElements['base-fee-settings']._html;
assert(html.indexOf('base-fee-settings-pp-editor') !== -1, 'render pp: shows editor');
assert(html.indexOf('ag') !== -1, 'render pp: shows ag product');
assert(html.indexOf('rb') !== -1, 'render pp: shows rb product');
assert(html.indexOf('data-pp-product="ag"') !== -1, 'render pp: ag row has data attr');

// ---------------------------------------------------------------------------
// 6. render — per_product empty map
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Test', testerId: 't', factorAlias: 'f', groupCount: 5, groupIndex: 0, feeMode: 'per_product', feeMap: null });
global._mockActiveBGId = 'bg_1';
_makeContainer('base-fee-settings');
panel.render();
html = _domElements['base-fee-settings']._html;
assert(html.indexOf('base-fee-settings-pp-editor') !== -1, 'render pp null: shows editor');
// Should not crash on null feeMap

// ---------------------------------------------------------------------------
// 7. render — custom mode
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Test', testerId: 't', factorAlias: 'f', groupCount: 5, groupIndex: 0, feeMode: 'custom' });
global._mockActiveBGId = 'bg_1';
_makeContainer('base-fee-settings');
panel.render();
html = _domElements['base-fee-settings']._html;
assert(html.indexOf('value="custom"') !== -1, 'render custom: custom checked');
assert(html.indexOf('base-fee-settings-uniform-editor') === -1, 'render custom: no uniform editor');
assert(html.indexOf('base-fee-settings-pp-editor') === -1, 'render custom: no pp editor');

// ---------------------------------------------------------------------------
// 8. sensitivity slider always present
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Test', testerId: 't', factorAlias: 'f', groupCount: 5, groupIndex: 0, feeMode: 'none', feeSensitivity: 1.5 });
global._mockActiveBGId = 'bg_1';
_makeContainer('base-fee-settings');
panel.render();
html = _domElements['base-fee-settings']._html;
assert(html.indexOf('base-fee-settings-sensitivity') !== -1, 'sensitivity: slider present');
assert(html.indexOf('value="1.5"') !== -1, 'sensitivity: value 1.5');
assert(html.indexOf('1.5') !== -1, 'sensitivity: label shows 1.5');

// ---------------------------------------------------------------------------
// 9. mount lifecycle
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Test', testerId: 't', factorAlias: 'f', groupCount: 5, groupIndex: 0, feeMode: 'none' });
global._mockActiveBGId = 'bg_1';
_makeContainer('base-fee-settings');
panel.mount();
assert(_domElements['base-fee-settings']._html.indexOf('费率模式') !== -1, 'mount: renders');
// Should have registered handlers
assert(global._events['baseGroupsChanged'].length >= 1, 'mount: registered baseGroupsChanged');
assert(global._events['activeBaseGroupChanged'].length >= 1, 'mount: registered activeBaseGroupChanged');

// Unmount cleans up
panel.unmount();
// After unmount, events should be unregistered
// (Our mock just removes them from array)
assert(global._events['baseGroupsChanged'].length === 0, 'unmount: baseGroupsChanged cleared');
assert(global._events['activeBaseGroupChanged'].length === 0, 'unmount: activeBaseGroupChanged cleared');

// ---------------------------------------------------------------------------
// 10. activeBaseGroupChanged triggers re-render
// ---------------------------------------------------------------------------

resetAll();
_makeContainer('base-fee-settings');
panel.mount();
// Initially no selection
assert(_domElements['base-fee-settings']._html.indexOf('请先在') !== -1, 'before select: placeholder');

// Select a group
mockBG.push({ id: 'bg_2', name: 'G2', testerId: 't', factorAlias: 'f', groupCount: 3, groupIndex: 0, feeMode: 'uniform', feeRate: 3.0 });
global._mockActiveBGId = 'bg_2';
GT.state.emit('activeBaseGroupChanged', { id: 'bg_2' });
assert(_domElements['base-fee-settings']._html.indexOf('value="3"') !== -1, 'after select: shows 3.0 rate');

panel.unmount();

// ---------------------------------------------------------------------------
// 11. unmount does not respond to events
// ---------------------------------------------------------------------------

resetAll();
_makeContainer('base-fee-settings');
panel.mount();
panel.unmount();

// Change data — should NOT re-render
var htmlBefore = _domElements['base-fee-settings']._html;
mockBG.push({ id: 'bg_3', name: 'G3', testerId: 't', factorAlias: 'f', groupCount: 2, groupIndex: 0, feeMode: 'per_product' });
GT.state.emit('activeBaseGroupChanged', { id: 'bg_3' });
var htmlAfter = _domElements['base-fee-settings']._html;
assertEquals(htmlAfter, htmlBefore, 'unmounted: does not react to events');

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------

console.log('\n=== Results ===');
console.log('Passed: ' + passed);
console.log('Failed: ' + failed);
if (failed > 0) process.exit(1);
