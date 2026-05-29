/**
 * test_panels_derived_summary.js — Node.js tests for panels/derived/summary.js
 *
 * Tests P4-6: derived group summary panel
 */

var passed = 0, failed = 0;

function assert(condition, msg) {
    if (condition) { passed++; }
    else { console.log('FAIL: ' + msg); failed++; }
}

function assertContains(str, substr, msg) {
    if (typeof str === 'string' && str.indexOf(substr) !== -1) { passed++; }
    else { console.log('FAIL: ' + msg + '\n  expected to contain: ' + substr + '\n  actual: ' + String(str).substring(0, 500)); failed++; }
}

function assertNotContains(str, substr, msg) {
    if (typeof str === 'string' && str.indexOf(substr) === -1) { passed++; }
    else { console.log('FAIL: ' + msg + '\n  should NOT contain: ' + substr); failed++; }
}

// ---------------------------------------------------------------------------
// Mock DOM
// ---------------------------------------------------------------------------

var _domElements = {};

global.document = {
    getElementById: function(id) {
        if (_domElements[id]) return _domElements[id];
        if (id && id.indexOf('derived-summary-panel') === 0) {
            return _makeEl(id);
        }
        return null;
    },
};

function _makeEl(id) {
    var el = {
        id: id,
        _html: '',
        _listeners: {},
        style: {},
        get innerHTML() { return this._html; },
        set innerHTML(v) {
            this._html = v;
            var idRe = /\bid="([^"]+)"/g;
            var im;
            while ((im = idRe.exec(v)) !== null) {
                _domElements[im[1]] = _makeEl(im[1]);
            }
        },
        addEventListener: function(evt, fn) {
            if (!this._listeners[evt]) this._listeners[evt] = [];
            var self = this;
            this._listeners[evt].push(function(e) { return fn.call(self, e); });
        },
        removeEventListener: function() {},
        remove: function() { delete _domElements[this.id]; },
    };
    _domElements[id] = el;
    return el;
}

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

var mockDG = [];
var mockBG = [];

function resetAll() {
    mockDG = [];
    mockBG = [];
    _domElements = {};
    global._mockActiveDGId = null;
}

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
            getActiveDerivedNodeId: function() { return global._mockActiveDGId; },
        },
        panels: {},
        log: function() {},
    },
};

// ---------------------------------------------------------------------------
// Load module
// ---------------------------------------------------------------------------

try {
    require('../../static/js/modules/single_factor_test/group_test/panels/derived/summary.js');
} catch (e) {
    console.log('MODULE LOAD ERROR: ' + e.message);
    console.log(e.stack);
    process.exit(1);
}

var GT = window.GroupTest;
var panel = GT.panels.derived.summary;

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
_makeEl('derived-summary-panel');
panel.render();
assertContains(_domElements['derived-summary-panel']._html, '请在「树」中选择', '2. no active: placeholder');

// ---------------------------------------------------------------------------
// 3. Manual node, no overrides
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: '主要品种', products: ['ag'], groupCount: 5 });
mockDG.push({ id: 'dg_1', name: '手动组1', baseGroupId: 'bg_1', parentId: null, isAutoGenerated: false,
    feeOverride: undefined, closeTodayOverride: undefined, rebalanceModeOverride: undefined, productMask: {} });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-summary-panel');
panel.render();
var html = _domElements['derived-summary-panel']._html;
assertContains(html, '手动组1', '3. name');
assertContains(html, '手动创建', '3. type: manual');
assertNotContains(html, '项覆盖', '3. no override count');

// ---------------------------------------------------------------------------
// 4. Auto-generated node
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', products: [], groupCount: 5 });
mockDG.push({ id: 'dg_a', name: 'Auto1', baseGroupId: 'bg_1', parentId: null, isAutoGenerated: true,
    feeOverride: undefined, closeTodayOverride: undefined, rebalanceModeOverride: undefined, productMask: {} });
global._mockActiveDGId = 'dg_a';
_makeEl('derived-summary-panel');
panel.render();
html = _domElements['derived-summary-panel']._html;
assertContains(html, '自动生成', '4. type: auto');

// ---------------------------------------------------------------------------
// 5. Node with all overrides
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', products: [], groupCount: 5 });
mockDG.push({ id: 'dg_ov', name: 'OverrideNode', baseGroupId: 'bg_1', parentId: null, isAutoGenerated: false,
    feeOverride: { mode: 'uniform', uniformRate: 0.0001 },
    closeTodayOverride: true,
    rebalanceModeOverride: 'each_period',
    productMask: { 'ag': true, 'cu': true, 'rb': true } });
global._mockActiveDGId = 'dg_ov';
_makeEl('derived-summary-panel');
panel.render();
html = _domElements['derived-summary-panel']._html;
assertContains(html, '4 项覆盖', '5. override count: 4');
assertContains(html, '费率', '5. override: fee');
assertContains(html, 'uniform', '5. override: fee mode');
assertContains(html, '平今', '5. override: close today');
assertContains(html, '每期再平衡', '5. override: rebalance');
assertContains(html, 'ag', '5. override: product');

// ---------------------------------------------------------------------------
// 6. Partial overrides
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', products: [], groupCount: 5 });
mockDG.push({ id: 'dg_part', name: 'Partial', baseGroupId: 'bg_1', parentId: null, isAutoGenerated: false,
    feeOverride: { mode: 'per_product', perProductRates: {} },
    closeTodayOverride: undefined,
    rebalanceModeOverride: 'buy_and_hold',
    productMask: {} });
global._mockActiveDGId = 'dg_part';
_makeEl('derived-summary-panel');
panel.render();
html = _domElements['derived-summary-panel']._html;
assertContains(html, '2 项覆盖', '6. override count: 2');
assertContains(html, '买入持有', '6. rebalance: buy and hold');
assertContains(html, 'per_product', '6. fee: per_product');
assertNotContains(html, '平今', '6. no close today');

// ---------------------------------------------------------------------------
// 7. Parent chain display
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', products: [], groupCount: 5 });
mockDG.push({ id: 'dg_p', name: 'Parent', baseGroupId: 'bg_1', parentId: null, isAutoGenerated: true,
    feeOverride: undefined, closeTodayOverride: undefined, rebalanceModeOverride: undefined, productMask: {} });
mockDG.push({ id: 'dg_c', name: 'Child', baseGroupId: 'bg_1', parentId: 'dg_p', isAutoGenerated: false,
    feeOverride: { mode: 'uniform', uniformRate: 0.0005 },
    closeTodayOverride: undefined, rebalanceModeOverride: undefined, productMask: {} });
global._mockActiveDGId = 'dg_c';
_makeEl('derived-summary-panel');
panel.render();
html = _domElements['derived-summary-panel']._html;
assertContains(html, 'Parent', '7. parent name');
assertContains(html, '1 项覆盖', '7. child has 1 override');

// ---------------------------------------------------------------------------
// 8. Mount/unmount
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', products: [], groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'D1', baseGroupId: 'bg_1', parentId: null, isAutoGenerated: true,
    feeOverride: undefined, closeTodayOverride: undefined, rebalanceModeOverride: undefined, productMask: {} });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-summary-panel');
global._events = {};
panel.mount();
assert(global._events['activeDerivedNodeChanged'] !== undefined, '8. mount: event registered');
assertContains(_domElements['derived-summary-panel']._html, 'D1', '8. mount: rendered');
panel.unmount();
var anc = global._events['activeDerivedNodeChanged'];
assert(!anc || anc.length === 0, '8. unmount: cleaned');

// ---------------------------------------------------------------------------
// 9. Node change re-render
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', products: [], groupCount: 5 });
mockDG.push({ id: 'dg_a', name: 'NodeA', baseGroupId: 'bg_1', parentId: null, isAutoGenerated: false,
    feeOverride: { mode: 'uniform', uniformRate: 0.001 },
    closeTodayOverride: false,
    rebalanceModeOverride: undefined,
    productMask: {} });
mockDG.push({ id: 'dg_b', name: 'NodeB', baseGroupId: 'bg_1', parentId: null, isAutoGenerated: true,
    feeOverride: undefined, closeTodayOverride: undefined, rebalanceModeOverride: undefined, productMask: {} });
global._mockActiveDGId = 'dg_a';
_makeEl('derived-summary-panel');
panel.render();
html = _domElements['derived-summary-panel']._html;
assertContains(html, 'NodeA', '9. render A');
assertContains(html, '2 项覆盖', '9. A has 2 overrides');
global._mockActiveDGId = 'dg_b';
panel.render();
html = _domElements['derived-summary-panel']._html;
assertContains(html, 'NodeB', '9. render B');
assertNotContains(html, '项覆盖', '9. B no overrides');

// ---------------------------------------------------------------------------
// 10. Large product mask truncation
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', products: [], groupCount: 5 });
var bigMask = {};
for (var i = 0; i < 10; i++) { bigMask['p' + i] = true; }
mockDG.push({ id: 'dg_big', name: 'Big', baseGroupId: 'bg_1', parentId: null, isAutoGenerated: false,
    feeOverride: undefined, closeTodayOverride: undefined, rebalanceModeOverride: undefined,
    productMask: bigMask });
global._mockActiveDGId = 'dg_big';
_makeEl('derived-summary-panel');
panel.render();
html = _domElements['derived-summary-panel']._html;
assertContains(html, '...', '10. truncation ellipsis');
assertContains(html, '10 个', '10. count shown');

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------

console.log('');
console.log('=== Results ===');
console.log('Passed: ' + passed);
console.log('Failed: ' + failed);

if (failed > 0) process.exit(1);
