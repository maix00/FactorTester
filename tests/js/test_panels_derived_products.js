/**
 * test_panels_derived_products.js — Node.js tests for panels/derived/products.js
 *
 * Tests P4-5: derived group products display panel
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
var _bodyHTML = '';

global.document = {
    getElementById: function(id) {
        if (_domElements[id]) return _domElements[id];
        if (id && id.indexOf('derived-products-panel') === 0) {
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
        querySelectorAll: function() { return []; },
        querySelector: function() { return null; },
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

global.alert = function() {};

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

var mockDG = [];
var mockBG = [];

function resetAll() {
    mockDG = [];
    mockBG = [];
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
        },
        panels: {},
        log: function() {},
    },
};

// ---------------------------------------------------------------------------
// Load module
// ---------------------------------------------------------------------------

try {
    require('../../static/js/modules/single_factor_test/group_test/panels/derived/products.js');
} catch (e) {
    console.log('MODULE LOAD ERROR: ' + e.message);
    console.log(e.stack);
    process.exit(1);
}

var GT = window.GroupTest;
var panel = GT.panels.derived.products;

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
_makeEl('derived-products-panel');
panel.render();
assertContains(_domElements['derived-products-panel']._html, '请在「树」中选择', '2. no active: placeholder');

// ---------------------------------------------------------------------------
// 3. Products from base group
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', products: ['ag', 'rb', 'cu'], groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'D1', baseGroupId: 'bg_1', parentId: null, productMask: {}, isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-products-panel');
panel.render();
var html = _domElements['derived-products-panel']._html;
assertContains(html, 'Base1', '3. source: base group name');
assertContains(html, 'ag', '3. product: ag');
assertContains(html, 'rb', '3. product: rb');
assertContains(html, 'cu', '3. product: cu');
assertContains(html, '3 个', '3. count: 3');

// ---------------------------------------------------------------------------
// 4. Override productMask
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', products: ['ag', 'rb', 'cu', 'zn'], groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'D1', baseGroupId: 'bg_1', parentId: null,
    productMask: { 'if': true, 'ic': true }, isAutoGenerated: false });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-products-panel');
panel.render();
html = _domElements['derived-products-panel']._html;
assertContains(html, '当前节点覆盖', '4. override: label');
assertContains(html, 'if', '4. override: if');
assertContains(html, 'ic', '4. override: ic');
assertNotContains(html, 'ag', '4. override: no base products');

// ---------------------------------------------------------------------------
// 5. Empty products
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', products: [], groupCount: 0 });
mockDG.push({ id: 'dg_1', name: 'D1', baseGroupId: 'bg_1', parentId: null, productMask: {}, isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-products-panel');
panel.render();
assertContains(_domElements['derived-products-panel']._html, '无品种配置', '5. empty: shows empty message');

// ---------------------------------------------------------------------------
// 6. Inherit from parent chain
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', products: ['base_only'], groupCount: 5 });
mockDG.push({ id: 'dg_p', name: 'Parent', baseGroupId: 'bg_1', parentId: null,
    productMask: { 'p1': true, 'p2': true }, isAutoGenerated: false });
mockDG.push({ id: 'dg_c', name: 'Child', baseGroupId: 'bg_1', parentId: 'dg_p', productMask: {}, isAutoGenerated: false });
global._mockActiveDGId = 'dg_c';
_makeEl('derived-products-panel');
panel.render();
html = _domElements['derived-products-panel']._html;
assertContains(html, 'p1', '6. chain: p1 from parent');
assertContains(html, 'p2', '6. chain: p2 from parent');
assertNotContains(html, 'base_only', '6. chain: not base products');

// ---------------------------------------------------------------------------
// 7. mount/unmount
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', products: ['ag'], groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'D1', baseGroupId: 'bg_1', parentId: null, productMask: {}, isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-products-panel');
global._events = {};
panel.mount();
assert(global._events['activeDerivedNodeChanged'] !== undefined, '7. mount: event registered');
panel.unmount();
var anc = global._events['activeDerivedNodeChanged'];
assert(!anc || anc.length === 0, '7. unmount: cleaned');

// ---------------------------------------------------------------------------
// 8. Node change re-renders
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', products: ['x', 'y'], groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'D1', baseGroupId: 'bg_1', parentId: null, productMask: { 'z': true }, isAutoGenerated: false });
mockDG.push({ id: 'dg_2', name: 'D2', baseGroupId: 'bg_1', parentId: null, productMask: {}, isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-products-panel');
panel.render();
assertContains(_domElements['derived-products-panel']._html, 'z', '8. node1: override');
global._mockActiveDGId = 'dg_2';
panel.render();
assertContains(_domElements['derived-products-panel']._html, 'x', '8. node2: from base');
global._mockActiveDGId = null;
panel.render();
assertContains(_domElements['derived-products-panel']._html, '请在「树」中选择', '8. none: placeholder');

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------

console.log('');
console.log('=== Results ===');
console.log('Passed: ' + passed);
console.log('Failed: ' + failed);

if (failed > 0) process.exit(1);
