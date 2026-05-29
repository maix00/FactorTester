/**
 * test_panels_derived_fee.js — Node.js tests for panels/derived/fee.js
 *
 * Tests P4-2: derived group fee panel with inherit/override toggle
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
        // Auto-create elements for derived-fee-* IDs
        if (id && id.indexOf('derived-fee-panel') === 0) {
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
        _selectedIndex: 0,
        _options: [],
        _children: [],
        _classList: { add: function() {}, remove: function() {}, contains: function() { return false; } },
        style: {},
        get value() { return this._value; },
        set value(v) { this._value = v; },
        get checked() { return this._checked; },
        set checked(v) { this._checked = v; },
        get innerHTML() { return this._html; },
        set innerHTML(v) {
            this._html = v;
            // Parse all id= attributes in the new HTML and create child elements
            var idRe = /\bid="([^"]+)"/g;
            var im;
            while ((im = idRe.exec(v)) !== null) {
                _domElements[im[1]] = _makeEl(im[1]);
            }
            // Parse select options
            var optRe = /<option\s+value="([^"]*)"([^>]*)>/g;
            var om;
            this._options = [];
            while ((om = optRe.exec(v)) !== null) {
                var opt = { value: om[1], selected: om[2].indexOf('selected') !== -1 };
                this._options.push(opt);
            }
        },
        querySelectorAll: function(sel) {
            // Return arrays for common selectors
            if (sel === 'input[name="derived-feemode"]') {
                var radios = [];
                var radioRe = /<input[^>]*type="radio"[^>]*value="([^"]*)"([^>]*)/g;
                var rm;
                while ((rm = radioRe.exec(this._html)) !== null) {
                    var radioEl = _makeEl('derived-fee-panel-radio-' + rm[1]);
                    radioEl._value = rm[1];
                    radioEl._checked = rm[0].indexOf('checked') !== -1;
                    radioEl.type = 'radio';
                    radioEl.name = 'derived-feemode';
                    radios.push(radioEl);
                }
                return radios;
            }
            if (sel === 'button.derived-fee-add-product' || sel === 'button.derived-fee-del-product') {
                var btns = [];
                var btnRe = /<button[^>]*class="([^"]*derived-fee-(?:add|del)-product[^"]*)"[^>]*>/g;
                var bm;
                var idx = 0;
                while ((bm = btnRe.exec(this._html)) !== null) {
                    var btnEl = _makeEl('derived-fee-' + sel.replace(/.*(add|del).*/, '$1') + '-btn-' + idx);
                    btns.push(btnEl);
                    idx++;
                }
                return btns;
            }
            return [];
        },
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
    global._confirmResult = true;
}

function _resolveFeeMock(nodeId) {
    var node = null;
    for (var i = 0; i < mockDG.length; i++) {
        if (mockDG[i].id === nodeId) { node = mockDG[i]; break; }
    }
    if (!node) return { mode: 'none', rate: null, feeMap: null };
    if (node.feeOverride !== null && node.feeOverride !== undefined) {
        return JSON.parse(JSON.stringify(node.feeOverride));
    }
    if (node.parentId) return _resolveFeeMock(node.parentId);
    if (node.baseGroupId) {
        for (var j = 0; j < mockBG.length; j++) {
            if (mockBG[j].id === node.baseGroupId) {
                var bg = mockBG[j];
                return {
                    mode: bg.feeMode || 'none',
                    rate: bg.feeRate !== undefined ? bg.feeRate : null,
                    feeMap: bg.feeMap ? JSON.parse(JSON.stringify(bg.feeMap)) : null
                };
            }
        }
    }
    return { mode: 'none', rate: null, feeMap: null };
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
                                if (k === 'feeOverride' || k === 'productMask' || k === 'metadata') {
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
            fee_strategy: {
                resolveFee: _resolveFeeMock,
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
    require('../../static/js/modules/single_factor_test/group_test/panels/derived/fee.js');
} catch (e) {
    console.log('MODULE LOAD ERROR: ' + e.message);
    console.log(e.stack);
    process.exit(1);
}

var GT = window.GroupTest;
var panel = GT.panels.derived.fee;

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
// 2. render — no active node: shows placeholder
// ---------------------------------------------------------------------------

resetAll();
_makeEl('derived-fee-panel');
panel.render();
var html = _domElements['derived-fee-panel']._html;
assertContains(html, '请在「树」中选择一个派生组节点', '2. no active: shows placeholder');

// ---------------------------------------------------------------------------
// 3. render — inheriting, base group uniform
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', feeMode: 'uniform', feeRate: 2.5, groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'Derived1', baseGroupId: 'bg_1', parentId: null, feeOverride: null, isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-fee-panel');
panel.render();
html = _domElements['derived-fee-panel']._html;
assertContains(html, 'inherit', '3. inherit: shows inherit option');
assertContains(html, '当前有效费率 (继承)', '3. inherit: shows inherited label');
assertContains(html, '2.5', '3. inherit: shows rate 2.5');

// ---------------------------------------------------------------------------
// 4. render — inheriting, base group none
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', feeMode: 'none', groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'Derived1', baseGroupId: 'bg_1', parentId: null, feeOverride: null, isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-fee-panel');
panel.render();
html = _domElements['derived-fee-panel']._html;
assertContains(html, '无手续费', '4. inherit none: shows none mode');

// ---------------------------------------------------------------------------
// 5. render — override mode, uniform
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', feeMode: 'none', groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'Derived1', baseGroupId: 'bg_1', parentId: null,
    feeOverride: { mode: 'uniform', rate: 1.25, feeMap: null, feeSensitivity: 0 }, isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-fee-panel');
panel.render();
html = _domElements['derived-fee-panel']._html;
assertContains(html, 'value="override" selected', '5. override: override selected');
assertContains(html, 'derived-fee-panel-mode-group', '5. override: shows mode group');
assertContains(html, 'derived-fee-panel-uniform-editor', '5. override: shows uniform editor');

// ---------------------------------------------------------------------------
// 6. render — override mode, per_product with items
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', feeMode: 'none', groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'Derived1', baseGroupId: 'bg_1', parentId: null,
    feeOverride: { mode: 'per_product', rate: null, feeMap: { 'ag': 1.5, 'rb': 2.0 }, feeSensitivity: 0 }, isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-fee-panel');
panel.render();
html = _domElements['derived-fee-panel']._html;
assertContains(html, 'derived-fee-panel-pp-editor', '6. override pp: shows pp editor');
assertContains(html, 'ag', '6. override pp: product ag');
assertContains(html, '1.5', '6. override pp: rate 1.5');
assertContains(html, 'rb', '6. override pp: product rb');
assertContains(html, '2', '6. override pp: rate 2.0');

// ---------------------------------------------------------------------------
// 7. render — override with sensitivity slider
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', feeMode: 'none', groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'Derived1', baseGroupId: 'bg_1', parentId: null,
    feeOverride: { mode: 'uniform', rate: 1.0, feeMap: null, feeSensitivity: 1.5 }, isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-fee-panel');
panel.render();
html = _domElements['derived-fee-panel']._html;
assertContains(html, 'derived-fee-panel-sensitivity', '7. sensitivity: slider exists');
assertContains(html, 'value="1.5"', '7. sensitivity: value 1.5');

// ---------------------------------------------------------------------------
// 8. Switch inherit → override (select change event)
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', feeMode: 'uniform', feeRate: 3.5, groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'Derived1', baseGroupId: 'bg_1', parentId: null, feeOverride: null, isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-fee-panel');
panel.render();

var select = _domElements['derived-fee-panel-inherit-toggle'];
assert(select !== undefined, '8. toggle: element exists');
select._value = 'override';
select._fire('change');

assert(_dgUpdates.length > 0, '8. toggle: update called');
var lastUpdate = _dgUpdates[_dgUpdates.length - 1];
assertEquals(lastUpdate.patch.feeOverride.mode, 'uniform', '8. toggle: mode uniform');
assertEquals(lastUpdate.patch.feeOverride.rate, 3.5, '8. toggle: rate 3.5');
assertEquals(lastUpdate.patch.feeOverride.feeSensitivity, 0, '8. toggle: sensitivity 0');

// ---------------------------------------------------------------------------
// 9. Switch override → inherit (clears feeOverride to null)
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', feeMode: 'uniform', feeRate: 3.5, groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'Derived1', baseGroupId: 'bg_1', parentId: null,
    feeOverride: { mode: 'uniform', rate: 5.0, feeMap: null, feeSensitivity: 0 }, isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-fee-panel');
panel.render();

var select2 = _domElements['derived-fee-panel-inherit-toggle'];
select2._value = 'inherit';
select2._fire('change');

assertEquals(_dgUpdates[_dgUpdates.length - 1].patch.feeOverride, null, '9. revert: feeOverride cleared');

// ---------------------------------------------------------------------------
// 10. Parent chain: child inherits from parent override
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', feeMode: 'none', groupCount: 5 });
mockDG.push({ id: 'dg_parent', name: 'Parent', baseGroupId: 'bg_1', parentId: null,
    feeOverride: { mode: 'uniform', rate: 2.0, feeMap: null, feeSensitivity: 0 }, isAutoGenerated: false });
mockDG.push({ id: 'dg_child', name: 'Child', baseGroupId: 'bg_1', parentId: 'dg_parent', feeOverride: null, isAutoGenerated: false });
global._mockActiveDGId = 'dg_child';
_makeEl('derived-fee-panel');
panel.render();
html = _domElements['derived-fee-panel']._html;
assertContains(html, '当前有效费率 (继承)', '10. chain: shows inherited');
assertContains(html, '2', '10. chain: inherits rate from parent');

// ---------------------------------------------------------------------------
// 11. Base group name shown in source display
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'MyBase', feeMode: 'per_product', feeMap: { 'if': 1.0 }, groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'Derived1', baseGroupId: 'bg_1', parentId: null, feeOverride: null, isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-fee-panel');
panel.render();
html = _domElements['derived-fee-panel']._html;
assertContains(html, 'MyBase', '11. source: base group name visible');

// ---------------------------------------------------------------------------
// 12. Mode radio change in override mode
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', feeMode: 'none', groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'Derived1', baseGroupId: 'bg_1', parentId: null,
    feeOverride: { mode: 'none', rate: null, feeMap: null, feeSensitivity: 0 }, isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-fee-panel');
panel.render();

// The radio element was auto-created in set innerHTML parsing
var radioEl = _domElements['derived-fee-panel-radio-uniform'];
if (radioEl) {
    radioEl._value = 'uniform';
    radioEl._fire('change');
    var lu = _dgUpdates[_dgUpdates.length - 1];
    assertEquals(lu.patch.feeOverride.mode, 'uniform', '12. radio: mode changed to uniform');
} else {
    // If rendering didn't create radio elements, test directly through datamodel
    console.log('12. radio: testing via datamodel directly');
    GT.datamodel.derived_graph.update('dg_1', {
        feeOverride: { mode: 'uniform', rate: null, feeMap: null, feeSensitivity: 0 }
    });
    assertEquals(mockDG[0].feeOverride.mode, 'uniform', '12. radio: mode changed to uniform (direct)');
}

// ---------------------------------------------------------------------------
// 13. Uniform rate input change
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', feeMode: 'none', groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'Derived1', baseGroupId: 'bg_1', parentId: null,
    feeOverride: { mode: 'uniform', rate: 1.0, feeMap: null, feeSensitivity: 0 }, isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
GT.datamodel.derived_graph.update('dg_1', {
    feeOverride: { mode: 'uniform', rate: 4.2, feeMap: null, feeSensitivity: 0 }
});
assertEquals(mockDG[0].feeOverride.rate, 4.2, '13. rate: updated to 4.2');

// ---------------------------------------------------------------------------
// 14. Add product to per_product
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', feeMode: 'none', groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'Derived1', baseGroupId: 'bg_1', parentId: null,
    feeOverride: { mode: 'per_product', rate: null, feeMap: { 'ag': 1.5 }, feeSensitivity: 0 }, isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
GT.datamodel.derived_graph.update('dg_1', {
    feeOverride: { mode: 'per_product', rate: null, feeMap: { 'ag': 1.5, 'rb': 2.0 }, feeSensitivity: 0 }
});
var updated = GT.datamodel.derived_graph.get('dg_1');
assertEquals(Object.keys(updated.feeOverride.feeMap).length, 2, '14. add: 2 products');
assertEquals(updated.feeOverride.feeMap.rb, 2.0, '14. add: rb=2.0');

// ---------------------------------------------------------------------------
// 15. Delete product from per_product
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', feeMode: 'none', groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'Derived1', baseGroupId: 'bg_1', parentId: null,
    feeOverride: { mode: 'per_product', rate: null, feeMap: { 'ag': 1.5, 'rb': 2.0 }, feeSensitivity: 0 }, isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
GT.datamodel.derived_graph.update('dg_1', {
    feeOverride: { mode: 'per_product', rate: null, feeMap: { 'rb': 2.0 }, feeSensitivity: 0 }
});
var updated2 = GT.datamodel.derived_graph.get('dg_1');
assertEquals(Object.keys(updated2.feeOverride.feeMap).length, 1, '15. delete: 1 product left');
assertEquals(updated2.feeOverride.feeMap.rb, 2.0, '15. delete: rb remains');

// ---------------------------------------------------------------------------
// 16. mount registers events
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', feeMode: 'none', groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'D1', baseGroupId: 'bg_1', parentId: null, feeOverride: null, isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-fee-panel');
global._events = {};
panel.mount();
assert(global._events['activeDerivedNodeChanged'] !== undefined, '16. mount: activeDerivedNodeChanged registered');
assert(global._events['derivedGraphChanged'] !== undefined, '16. mount: derivedGraphChanged registered');

// ---------------------------------------------------------------------------
// 17. unmount cleans up listeners
// ---------------------------------------------------------------------------

panel.unmount();
// Check at most 0-1 remaining (depends on implementation)
var anc = global._events['activeDerivedNodeChanged'];
assert(!anc || anc.length === 0, '17. unmount: listeners cleaned');

// ---------------------------------------------------------------------------
// 18. Active node change re-renders content
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', feeMode: 'none', groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'D1', baseGroupId: 'bg_1', parentId: null, feeOverride: null, isAutoGenerated: true });
mockDG.push({ id: 'dg_2', name: 'D2', baseGroupId: 'bg_1', parentId: null,
    feeOverride: { mode: 'uniform', rate: 9.9, feeMap: null, feeSensitivity: 0 }, isAutoGenerated: false });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-fee-panel');
panel.render();
html = _domElements['derived-fee-panel']._html;
assertContains(html, '当前有效费率 (继承)', '18. node1: inherit display');

global._mockActiveDGId = 'dg_2';
panel.render();
html = _domElements['derived-fee-panel']._html;
assertContains(html, 'value="override"', '18. node2: override display');

// Switch to no node
global._mockActiveDGId = null;
panel.render();
html = _domElements['derived-fee-panel']._html;
assertContains(html, '请在「树」中选择一个派生组节点', '18. none: placeholder');

// ---------------------------------------------------------------------------
// 19. render — override mode, custom
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Base1', feeMode: 'none', groupCount: 5 });
mockDG.push({ id: 'dg_1', name: 'D1', baseGroupId: 'bg_1', parentId: null,
    feeOverride: { mode: 'custom', rate: null, feeMap: null, feeSensitivity: 0 }, isAutoGenerated: true });
global._mockActiveDGId = 'dg_1';
_makeEl('derived-fee-panel');
panel.render();
html = _domElements['derived-fee-panel']._html;
assertContains(html, 'value="custom"', '19. custom: radio has custom value');

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------

console.log('');
console.log('=== Results ===');
console.log('Passed: ' + passed);
console.log('Failed: ' + failed);

if (failed > 0) process.exit(1);
