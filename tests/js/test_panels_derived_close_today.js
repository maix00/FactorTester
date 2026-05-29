/**
 * test_panels_derived_close_today.js — Node.js tests for panels/derived/close_today.js
 *
 * Tests P4-3: derived group close-today panel with inherit/override toggle
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
        if (id && id.indexOf('derived-close-today-panel') === 0) {
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
        _classList: { add: function() {}, remove: function() {}, contains: function() { return false; } },
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

global.confirm = function(msg) { return true; };
global.alert = function(msg) {};

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
            emit: function(evt, data) {},
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
    require('../../static/js/modules/single_factor_test/group_test/panels/derived/close_today.js');
} catch (e) {
    console.log('MODULE LOAD ERROR: ' + e.message);
    console.log(e.stack);
    process.exit(1);
}

var GT = window.GroupTest;
var panel = GT.panels.derived.close_today;

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
_makeEl('derived-close-today-panel');
panel.render();
var html = _domElements['derived-close-today-panel']._html;
assertContains(html, '请在「树」中选择一个派生组节点', '2. no active: shows placeholder');

// ---------------------------------------------------------------------------
// 3. Inherit from base group (useCloseToday=true)
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', useCloseToday: true, groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'Derived1', baseGroupId: 'bg_1', parentId: null, closeTodayOverride: null, isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-close-today-panel');
panel.render();
html = _domElements['derived-close-today-panel']._html;
assertContains(html, '继承', '3. inherit: shows inherit option');
assertContains(html, '当前有效值 (继承)', '3. inherit: shows inherited label');
assertContains(html, '平今仓', '3. inherit: useCloseToday=true shows 平今仓');

// ---------------------------------------------------------------------------
// 4. Inherit from base group (useCloseToday=false)
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', useCloseToday: false, groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'Derived1', baseGroupId: 'bg_1', parentId: null, closeTodayOverride: null, isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-close-today-panel');
panel.render();
html = _domElements['derived-close-today-panel']._html;
assertContains(html, '平昨仓', '4. inherit: useCloseToday=false shows 平昨仓');

// ---------------------------------------------------------------------------
// 5. Override mode — closeTodayOverride=true
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', useCloseToday: false, groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'Derived1', baseGroupId: 'bg_1', parentId: null, closeTodayOverride: true, isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-close-today-panel');
panel.render();
html = _domElements['derived-close-today-panel']._html;
assertContains(html, 'value="override" selected', '5. override: override selected');
assertContains(html, '平今仓', '5. override: shows 平今仓');
assertContains(html, '切换为平昨仓', '5. override: toggle button shows 切换为平昨仓');

// ---------------------------------------------------------------------------
// 6. Override mode — closeTodayOverride=false
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', useCloseToday: true, groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'Derived1', baseGroupId: 'bg_1', parentId: null, closeTodayOverride: false, isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-close-today-panel');
panel.render();
html = _domElements['derived-close-today-panel']._html;
assertContains(html, '平昨仓', '6. override false: shows 平昨仓');
assertContains(html, '切换为平今仓', '6. override false: toggle button shows 切换为平今仓');

// ---------------------------------------------------------------------------
// 7. Switch inherit → override
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', useCloseToday: true, groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'Derived1', baseGroupId: 'bg_1', parentId: null, closeTodayOverride: null, isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-close-today-panel');
panel.render();

var select = _domElements['derived-close-today-panel-inherit-toggle'];
assert(select !== undefined, '7. toggle: element exists');
select._value = 'override';
select._fire('change');

assert(_dgUpdates.length > 0, '7. toggle: update called');
assertEquals(_dgUpdates[_dgUpdates.length - 1].patch.closeTodayOverride, true, '7. toggle: inherited true value');

// ---------------------------------------------------------------------------
// 8. Switch override → inherit
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', useCloseToday: true, groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'Derived1', baseGroupId: 'bg_1', parentId: null, closeTodayOverride: true, isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-close-today-panel');
panel.render();

var select2 = _domElements['derived-close-today-panel-inherit-toggle'];
select2._value = 'inherit';
select2._fire('change');

assertEquals(_dgUpdates[_dgUpdates.length - 1].patch.closeTodayOverride, null, '8. revert: closeTodayOverride cleared');

// ---------------------------------------------------------------------------
// 9. Toggle button flips value
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', useCloseToday: false, groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'Derived1', baseGroupId: 'bg_1', parentId: null, closeTodayOverride: false, isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-close-today-panel');
panel.render();

var btn = _domElements['derived-close-today-panel-toggle-btn'];
assert(btn !== undefined, '9. btn: element exists');
btn._fire('click');

assertEquals(_dgUpdates[_dgUpdates.length - 1].patch.closeTodayOverride, true, '9. btn: flipped to true');

// ---------------------------------------------------------------------------
// 10. Parent chain: child inherits from parent override
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', useCloseToday: false, groupCount: 5 });
mockDG.push({ id: 'dg_parent', name: 'Parent', baseGroupId: 'bg_1', parentId: null, closeTodayOverride: true, isAutoGenerated: false });
mockDG.push({ id: 'dg_child', name: 'Child', baseGroupId: 'bg_1', parentId: 'dg_parent', closeTodayOverride: null, isAutoGenerated: false });
global._mockActiveDGId = 'dg_child';
_makeEl('derived-close-today-panel');
panel.render();
html = _domElements['derived-close-today-panel']._html;
assertContains(html, '平今仓', '10. chain: child inherits parent override=true');

// ---------------------------------------------------------------------------
// 11. Base group name in source
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'TestBase', useCloseToday: true, groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'D1', baseGroupId: 'bg_1', parentId: null, closeTodayOverride: null, isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-close-today-panel');
panel.render();
html = _domElements['derived-close-today-panel']._html;
assertContains(html, 'TestBase', '11. source: base group name visible');

// ---------------------------------------------------------------------------
// 12. mount registers events
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', useCloseToday: false, groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'D1', baseGroupId: 'bg_1', parentId: null, closeTodayOverride: null, isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-close-today-panel');
global._events = {};
panel.mount();
assert(global._events['activeDerivedNodeChanged'] !== undefined, '12. mount: event registered');
assert(global._events['derivedGraphChanged'] !== undefined, '12. mount: graph event registered');

// ---------------------------------------------------------------------------
// 13. unmount cleans up
// ---------------------------------------------------------------------------

panel.unmount();
var anc = global._events['activeDerivedNodeChanged'];
assert(!anc || anc.length === 0, '13. unmount: listeners cleaned');

// ---------------------------------------------------------------------------
// 14. Active node change re-renders
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', useCloseToday: false, groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'D1', baseGroupId: 'bg_1', parentId: null, closeTodayOverride: null, isAutoGenerated: true });
mockDG.push({ id: 'dg_2', name: 'D2', baseGroupId: 'bg_1', parentId: null, closeTodayOverride: true, isAutoGenerated: false });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-close-today-panel');
panel.render();
assertContains(_domElements['derived-close-today-panel']._html, '当前有效值 (继承)', '14. node1: inherit');

global._mockActiveDGId = 'dg_2';
panel.render();
assertContains(_domElements['derived-close-today-panel']._html, 'value="override"', '14. node2: override');

global._mockActiveDGId = null;
panel.render();
assertContains(_domElements['derived-close-today-panel']._html, '请在「树」中选择', '14. none: placeholder');

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------

console.log('');
console.log('=== Results ===');
console.log('Passed: ' + passed);
console.log('Failed: ' + failed);

if (failed > 0) process.exit(1);
