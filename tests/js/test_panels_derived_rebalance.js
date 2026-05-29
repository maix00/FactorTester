/**
 * test_panels_derived_rebalance.js — Node.js tests for panels/derived/rebalance.js
 *
 * Tests P4-4: derived group rebalance panel with inherit/override toggle
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

function assertContains(str, substr, msg) {
    if (typeof str === 'string' && str.indexOf(substr) !== -1) { passed++; }
    else { console.log('FAIL: ' + msg + '\n  expected to contain: ' + substr + '\n  actual snippet: ' + String(str).substring(0, 500)); failed++; }
}

// ---------------------------------------------------------------------------
// Mock DOM
// ---------------------------------------------------------------------------

var _domElements = {};
var _bodyHTML = '';

global.document = {
    getElementById: function(id) {
        if (_domElements[id]) return _domElements[id];
        if (id && id.indexOf('derived-rebalance-panel') === 0) {
            return _makeEl(id);
        }
        return null;
    },
    body: {
        insertAdjacentHTML: function(pos, html) {
            _bodyHTML += html;
            var idRe = /\bid="([^"]+)"/g;
            var im;
            while ((im = idRe.exec(html)) !== null) {
                _domElements[im[1]] = _makeEl(im[1]);
            }
        },
    },
};

function _makeEl(id) {
    var el = {
        id: id,
        _html: '',
        _value: '',
        _textContent: '',
        _listeners: {},
        _checked: false,
        _options: [],
        _classList: { add: function() {}, remove: function() {} },
        style: {},
        get value() { return this._value; },
        set value(v) { this._value = v; },
        get checked() { return this._checked; },
        set checked(v) { this._checked = v; },
        get innerHTML() { return this._html; },
        set innerHTML(v) {
            this._html = v;
            var idRe = /\bid="([^"]+)"/g;
            var im;
            while ((im = idRe.exec(v)) !== null) {
                _domElements[im[1]] = _makeEl(im[1]);
            }
            var optRe = /<option\s+value="([^"]*)"([^>]*)>/g;
            var om;
            this._options = [];
            while ((om = optRe.exec(v)) !== null) {
                this._options.push({ value: om[1], selected: om[2].indexOf('selected') !== -1 });
            }
        },
        querySelectorAll: function(sel) { return []; },
        querySelector: function(sel) { return null; },
        addEventListener: function(evt, fn) {
            if (!this._listeners[evt]) this._listeners[evt] = [];
            var self = this;
            this._listeners[evt].push(function(e) { return fn.call(self, e); });
        },
        removeEventListener: function() {},
        remove: function() { delete _domElements[this.id]; },
        _fire: function(evt, e) {
            var fns = this._listeners[evt] || [];
            for (var i = 0; i < fns.length; i++) fns[i](e || {});
        },
    };
    _domElements[id] = el;
    return el;
}

global.confirm = function() { return true; };
global.alert = function() {};

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

var mockDG = [];
var mockBG = [];
var _dgUpdates = [];

function resetAll() {
    mockDG = [];
    mockBG = [];
    _dgUpdates = [];
    _domElements = {};
    _bodyHTML = '';
    global._mockActiveDGId = null;
}

// ---------------------------------------------------------------------------
// Mock window.GroupTest
// ---------------------------------------------------------------------------

global._mockActiveDGId = null;
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
            },
            derived_graph: {
                get: function(id) {
                    for (var i = 0; i < mockDG.length; i++) {
                        if (mockDG[i].id === id) return JSON.parse(JSON.stringify(mockDG[i]));
                    }
                    return null;
                },
                update: function(id, patch) {
                    _dgUpdates.push({ id: id, patch: JSON.parse(JSON.stringify(patch)) });
                    for (var i = 0; i < mockDG.length; i++) {
                        if (mockDG[i].id === id) {
                            Object.keys(patch).forEach(function(k) {
                                if (patch[k] === null || typeof patch[k] === 'object') {
                                    mockDG[i][k] = JSON.parse(JSON.stringify(patch[k]));
                                } else {
                                    mockDG[i][k] = patch[k];
                                }
                            });
                            return JSON.parse(JSON.stringify(mockDG[i]));
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
            emit: function() {},
            getActiveDerivedNodeId: function() { return global._mockActiveDGId; },
            setActiveDerivedNodeId: function(id) { global._mockActiveDGId = id; },
        },
        panels: {},
        log: function() {},
    },
};

// ---------------------------------------------------------------------------
// Load module
// ---------------------------------------------------------------------------

try {
    require('../../static/js/modules/single_factor_test/group_test/panels/derived/rebalance.js');
} catch (e) {
    console.log('MODULE LOAD ERROR: ' + e.message);
    console.log(e.stack);
    process.exit(1);
}

var GT = window.GroupTest;
var panel = GT.panels.derived.rebalance;

// ---------------------------------------------------------------------------
// 1. Module exports
// ---------------------------------------------------------------------------

resetAll();
assert(typeof panel === 'object', '1. exports: panel is object');
assert(typeof panel.mount === 'function', '1. exports: mount');
assert(typeof panel.unmount === 'function', '1. exports: unmount');
assert(typeof panel.refresh === 'function', '1. exports: refresh');
assert(typeof panel.render === 'function', '1. exports: render');

// ---------------------------------------------------------------------------
// 2. No active node
// ---------------------------------------------------------------------------

resetAll();
_makeEl('derived-rebalance-panel');
panel.render();
assertContains(_domElements['derived-rebalance-panel']._html, '请在「树」中选择', '2. no active: placeholder');

// ---------------------------------------------------------------------------
// 3. Inherit from base group (each_period)
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', rebalanceMode: 'each_period', groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'D1', baseGroupId: 'bg_1', parentId: null, rebalanceOverride: null, isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-rebalance-panel');
panel.render();
var html = _domElements['derived-rebalance-panel']._html;
assertContains(html, '每期等权再平衡', '3. inherit: each_period');

// ---------------------------------------------------------------------------
// 4. Inherit from base group (recycle)
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', rebalanceMode: 'recycle', groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'D1', baseGroupId: 'bg_1', parentId: null, rebalanceOverride: null, isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-rebalance-panel');
panel.render();
assertContains(_domElements['derived-rebalance-panel']._html, '退出资金优先补新仓', '4. inherit: recycle');

// ---------------------------------------------------------------------------
// 5. Override mode — buy_and_hold
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', rebalanceMode: 'each_period', groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'D1', baseGroupId: 'bg_1', parentId: null, rebalanceOverride: 'buy_and_hold', isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-rebalance-panel');
panel.render();
html = _domElements['derived-rebalance-panel']._html;
assertContains(html, 'value="override" selected', '5. override: override selected');
assertContains(html, 'value="buy_and_hold" selected', '5. override: buy_and_hold selected in dropdown');

// ---------------------------------------------------------------------------
// 6. Switch inherit → override
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', rebalanceMode: 'recycle', groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'D1', baseGroupId: 'bg_1', parentId: null, rebalanceOverride: null, isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-rebalance-panel');
panel.render();

var select = _domElements['derived-rebalance-panel-inherit-toggle'];
select._value = 'override';
select._fire('change');

assertEquals(_dgUpdates[_dgUpdates.length - 1].patch.rebalanceOverride, 'recycle', '6. switch: inherits recycle from base');

// ---------------------------------------------------------------------------
// 7. Switch override → inherit
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', rebalanceMode: 'each_period', groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'D1', baseGroupId: 'bg_1', parentId: null, rebalanceOverride: 'buy_and_hold', isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-rebalance-panel');
panel.render();

var select2 = _domElements['derived-rebalance-panel-inherit-toggle'];
select2._value = 'inherit';
select2._fire('change');

assertEquals(_dgUpdates[_dgUpdates.length - 1].patch.rebalanceOverride, null, '7. revert: cleared');

// ---------------------------------------------------------------------------
// 8. Mode select change in override
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', rebalanceMode: 'buy_and_hold', groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'D1', baseGroupId: 'bg_1', parentId: null, rebalanceOverride: 'each_period', isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-rebalance-panel');
panel.render();

var ms = _domElements['derived-rebalance-panel-mode-select'];
assert(ms !== undefined, '8. mode select exists');
ms._value = 'recycle';
ms._fire('change');

assertEquals(_dgUpdates[_dgUpdates.length - 1].patch.rebalanceOverride, 'recycle', '8. mode: changed to recycle');

// ---------------------------------------------------------------------------
// 9. Parent chain inheritance
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', rebalanceMode: 'buy_and_hold', groupCount: 5 });
mockDG.push({ id: 'dg_p', name: 'Parent', baseGroupId: 'bg_1', parentId: null, rebalanceOverride: 'recycle', isAutoGenerated: false });
mockDG.push({ id: 'dg_c', name: 'Child', baseGroupId: 'bg_1', parentId: 'dg_p', rebalanceOverride: null, isAutoGenerated: false });
global._mockActiveDGId = 'dg_c';
_makeEl('derived-rebalance-panel');
panel.render();
assertContains(_domElements['derived-rebalance-panel']._html, '退出资金优先补新仓', '9. chain: child inherits parent recycle');

// ---------------------------------------------------------------------------
// 10. mount/unmount
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', rebalanceMode: 'buy_and_hold', groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'D1', baseGroupId: 'bg_1', parentId: null, rebalanceOverride: null, isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-rebalance-panel');
global._events = {};
panel.mount();
assert(global._events['activeDerivedNodeChanged'] !== undefined, '10. mount: event registered');
panel.unmount();
var anc = global._events['activeDerivedNodeChanged'];
assert(!anc || anc.length === 0, '10. unmount: cleaned');

// ---------------------------------------------------------------------------
// 11. Node change re-renders
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', rebalanceMode: 'buy_and_hold', groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'D1', baseGroupId: 'bg_1', parentId: null, rebalanceOverride: 'recycle', isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-rebalance-panel');
panel.render();
assertContains(_domElements['derived-rebalance-panel']._html, 'value="override"', '11. node1: override');
global._mockActiveDGId = null;
panel.render();
assertContains(_domElements['derived-rebalance-panel']._html, '请在「树」中选择', '11. null: placeholder');

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------

console.log('');
console.log('=== Results ===');
console.log('Passed: ' + passed);
console.log('Failed: ' + failed);

if (failed > 0) process.exit(1);
