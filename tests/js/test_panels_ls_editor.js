/**
 * test_panels_ls_editor.js — Node.js tests for panels/add/ls.js
 */

var passed = 0, failed = 0;

function $(id) { return _domElements[id] || null; }

function assert(condition, msg) {
    if (condition) { passed++; }
    else { console.log('FAIL: ' + msg); failed++; }
}

function assertContains(str, substr, msg) {
    if (typeof str === 'string' && str.indexOf(substr) !== -1) { passed++; }
    else { console.log('FAIL: ' + msg + '\n  expected to contain: ' + substr + '\n  actual: ' + String(str).substring(0, 500)); failed++; }
}

// ---------------------------------------------------------------------------
// Mock DOM
// ---------------------------------------------------------------------------

var _domElements = {};

global.document = {
    getElementById: function(id) {
        if (_domElements[id]) return _domElements[id];
        if (id && (id.indexOf('ls-config-editor') === 0 || id.indexOf('lsed-') === 0)) {
            return _makeEl(id);
        }
        return null;
    },
};

function _makeEl(id) {
    var el = {
        id: id,
        _html: '',
        _value: '',
        _options: [],
        _listeners: {},
        style: {},
        get value() { return this._value; },
        set value(v) { this._value = v; },
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

global.alert = function(msg) { global._lastAlert = msg; };

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

var mockLS = [];
var mockDG = [];

function resetAll() {
    mockLS = [];
    mockDG = [];
    _domElements = {};
    global._lastAlert = null;
    global._mockActiveLSId = null;
}

global._mockActiveLSId = null;
global._events = {};

// ---------------------------------------------------------------------------
// Mock window.GroupTest
// ---------------------------------------------------------------------------

global.window = {
    GroupTest: {
        datamodel: {
            derived_graph: {
                get: function(id) {
                    for (var i = 0; i < mockDG.length; i++) {
                        if (mockDG[i].id === id) return mockDG[i];
                    }
                    return null;
                },
            },
            ls_configs: {
                get: function(id) {
                    for (var i = 0; i < mockLS.length; i++) {
                        if (mockLS[i].id === id) return JSON.parse(JSON.stringify(mockLS[i]));
                    }
                    return null;
                },
                update: function(id, patch) {
                    for (var i = 0; i < mockLS.length; i++) {
                        if (mockLS[i].id === id) {
                            Object.keys(patch).forEach(function(k) { mockLS[i][k] = patch[k]; });
                            return JSON.parse(JSON.stringify(mockLS[i]));
                        }
                    }
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
                var i = arr.indexOf(fn);
                if (i !== -1) arr.splice(i, 1);
            },
            emit: function() {},
            getActiveLSConfigId: function() { return global._mockActiveLSId; },
        },
        panels: {},
        log: function() {},
    },
};

// ---------------------------------------------------------------------------
// Load module
// ---------------------------------------------------------------------------

try {
    require('../../static/js/modules/single_factor_test/group_test/panels/add/ls.js');
} catch (e) {
    console.log('MODULE LOAD ERROR: ' + e.message);
    console.log(e.stack);
    process.exit(1);
}

var GT = window.GroupTest;
var panel = GT.panels.add.ls;

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
// 2. No active config
// ---------------------------------------------------------------------------

resetAll();
_makeEl('ls-config-editor');
panel.render();
assertContains(_domElements['ls-config-editor']._html, '请在左侧列表中选择', '2. no active: placeholder');

// ---------------------------------------------------------------------------
// 3. Display config with all defaults
// ---------------------------------------------------------------------------

resetAll();
mockDG.push({ id: 'dg_long', name: 'LongGroup' }, { id: 'dg_short', name: 'ShortGroup' });
mockLS.push({
    id: 'ls_1', name: 'Test LS', longGroupId: 'dg_long', shortGroupId: 'dg_short',
    feeMode: 'inherit', feeRate: null, useCloseToday: null, rebalanceMode: null,
    needsRegenerate: false, metadata: {},
});
global._mockActiveLSId = 'ls_1';
_makeEl('ls-config-editor');
panel.render();
var html = _domElements['ls-config-editor']._html;
assertContains(html, 'Test LS', '3. display: name');
assertContains(html, 'LongGroup', '3. display: long group');
assertContains(html, 'ShortGroup', '3. display: short group');
assertContains(html, '就绪', '3. display: ready badge');

// ---------------------------------------------------------------------------
// 4. Needs regenerate badge
// ---------------------------------------------------------------------------

resetAll();
mockDG.push({ id: 'dg_l', name: 'L' }, { id: 'dg_s', name: 'S' });
mockLS.push({ id: 'ls_stale', name: 'Stale', longGroupId: 'dg_l', shortGroupId: 'dg_s',
    feeMode: 'inherit', feeRate: null, useCloseToday: null, rebalanceMode: null,
    needsRegenerate: true, metadata: {} });
global._mockActiveLSId = 'ls_stale';
_makeEl('ls-config-editor');
panel.render();
assertContains(_domElements['ls-config-editor']._html, '待更新', '4. badge: stale');

// ---------------------------------------------------------------------------
// 5. Fee mode: override with rate
// ---------------------------------------------------------------------------

resetAll();
mockDG.push({ id: 'dg_l', name: 'L' }, { id: 'dg_s', name: 'S' });
mockLS.push({ id: 'ls_fee', name: 'Fee Config', longGroupId: 'dg_l', shortGroupId: 'dg_s',
    feeMode: 'override', feeRate: 0.00023, useCloseToday: null, rebalanceMode: null,
    needsRegenerate: false, metadata: {} });
global._mockActiveLSId = 'ls_fee';
_makeEl('ls-config-editor');
panel.render();
html = _domElements['ls-config-editor']._html;
assertContains(html, '覆盖费率', '5. fee: mode label');
assertContains(html, 'lsed-feeRate', '5. fee: rate input exists');
assertContains(html, '0.00023', '5. fee: rate value');

// ---------------------------------------------------------------------------
// 6. Close-today: true
// ---------------------------------------------------------------------------

resetAll();
mockDG.push({ id: 'dg_l', name: 'L' }, { id: 'dg_s', name: 'S' });
mockLS.push({ id: 'ls_ct', name: 'CT Config', longGroupId: 'dg_l', shortGroupId: 'dg_s',
    feeMode: 'inherit', feeRate: null, useCloseToday: true, rebalanceMode: null,
    needsRegenerate: false, metadata: {} });
global._mockActiveLSId = 'ls_ct';
_makeEl('ls-config-editor');
panel.render();
assertContains(_domElements['ls-config-editor']._html, '平今仓', '6. close-today: true');

// ---------------------------------------------------------------------------
// 7. Close-today: false
// ---------------------------------------------------------------------------

resetAll();
mockDG.push({ id: 'dg_l', name: 'L' }, { id: 'dg_s', name: 'S' });
mockLS.push({ id: 'ls_ct2', name: 'CT2', longGroupId: 'dg_l', shortGroupId: 'dg_s',
    feeMode: 'inherit', feeRate: null, useCloseToday: false, rebalanceMode: null,
    needsRegenerate: false, metadata: {} });
global._mockActiveLSId = 'ls_ct2';
_makeEl('ls-config-editor');
panel.render();
assertContains(_domElements['ls-config-editor']._html, '平昨仓', '7. close-today: false');

// ---------------------------------------------------------------------------
// 8. Rebalance mode
// ---------------------------------------------------------------------------

resetAll();
mockDG.push({ id: 'dg_l', name: 'L' }, { id: 'dg_s', name: 'S' });
mockLS.push({ id: 'ls_rb', name: 'RB', longGroupId: 'dg_l', shortGroupId: 'dg_s',
    feeMode: 'inherit', feeRate: null, useCloseToday: null, rebalanceMode: 'buy_and_hold',
    needsRegenerate: false, metadata: {} });
global._mockActiveLSId = 'ls_rb';
_makeEl('ls-config-editor');
panel.render();
assertContains(_domElements['ls-config-editor']._html, '买入持有', '8. rebalance: buy_and_hold');

// ---------------------------------------------------------------------------
// 9. Fee mode change triggers update
// ---------------------------------------------------------------------------

resetAll();
mockDG.push({ id: 'dg_l', name: 'L' }, { id: 'dg_s', name: 'S' });
mockLS.push({ id: 'ls_fm', name: 'FM', longGroupId: 'dg_l', shortGroupId: 'dg_s',
    feeMode: 'inherit', feeRate: null, useCloseToday: null, rebalanceMode: null,
    needsRegenerate: false, metadata: {} });
global._mockActiveLSId = 'ls_fm';
_makeEl('ls-config-editor');
panel.render();

var feeSel = $('lsed-feeMode');
assert(feeSel !== null, '9. fee select: exists');
feeSel._value = 'override';
feeSel._listeners['change'][0]();
assert(mockLS[0].feeMode === 'override', '9. fee select: updated to override');

// ---------------------------------------------------------------------------
// 10. Close-today toggle
// ---------------------------------------------------------------------------

resetAll();
mockDG.push({ id: 'dg_l', name: 'L' }, { id: 'dg_s', name: 'S' });
mockLS.push({ id: 'ls_ct3', name: 'CT3', longGroupId: 'dg_l', shortGroupId: 'dg_s',
    feeMode: 'inherit', feeRate: null, useCloseToday: null, rebalanceMode: null,
    needsRegenerate: false, metadata: {} });
global._mockActiveLSId = 'ls_ct3';
_makeEl('ls-config-editor');
panel.render();

var ctBtn = $('lsed-closeToday-toggle');
assert(ctBtn !== null, '10. toggle: exists');
ctBtn._listeners['click'][0]();
assert(mockLS[0].useCloseToday === true, '10. toggle: null→true');

// ---------------------------------------------------------------------------
// 11. Rebalance mode change
// ---------------------------------------------------------------------------

resetAll();
mockDG.push({ id: 'dg_l', name: 'L' }, { id: 'dg_s', name: 'S' });
mockLS.push({ id: 'ls_rb2', name: 'RB2', longGroupId: 'dg_l', shortGroupId: 'dg_s',
    feeMode: 'inherit', feeRate: null, useCloseToday: null, rebalanceMode: null,
    needsRegenerate: false, metadata: {} });
global._mockActiveLSId = 'ls_rb2';
_makeEl('ls-config-editor');
panel.render();

var rebalSel = $('lsed-rebalanceMode');
assert(rebalSel !== null, '11. rebal: exists');
rebalSel._value = 'recycle';
rebalSel._listeners['change'][0]();
assert(mockLS[0].rebalanceMode === 'recycle', '11. rebal: updated');

// ---------------------------------------------------------------------------
// 12. Mount/unmount
// ---------------------------------------------------------------------------

resetAll();
mockDG.push({ id: 'dg_l', name: 'L' }, { id: 'dg_s', name: 'S' });
mockLS.push({ id: 'ls_m', name: 'Mount', longGroupId: 'dg_l', shortGroupId: 'dg_s',
    feeMode: 'inherit', feeRate: null, useCloseToday: null, rebalanceMode: null,
    needsRegenerate: false, metadata: {} });
global._mockActiveLSId = 'ls_m';
_makeEl('ls-config-editor');
global._events = {};
panel.mount();
assert(global._events['activeLSConfigChanged'] !== undefined, '12. mount: event');
assert(global._events['lsConfigsChanged'] !== undefined, '12. mount: ls event');
panel.unmount();
assert(!global._events['activeLSConfigChanged'] || global._events['activeLSConfigChanged'].length === 0, '12. unmount: cleaned');

// ---------------------------------------------------------------------------
// 13. Node change re-renders
// ---------------------------------------------------------------------------

resetAll();
mockDG.push({ id: 'dg_l', name: 'L' }, { id: 'dg_s', name: 'S' });
mockLS.push({ id: 'ls_a', name: 'ConfigA', longGroupId: 'dg_l', shortGroupId: 'dg_s',
    feeMode: 'inherit', feeRate: null, useCloseToday: null, rebalanceMode: null,
    needsRegenerate: false, metadata: {} });
mockLS.push({ id: 'ls_b', name: 'ConfigB', longGroupId: 'dg_l', shortGroupId: 'dg_s',
    feeMode: 'override', feeRate: 0.001, useCloseToday: null, rebalanceMode: null,
    needsRegenerate: true, metadata: {} });
global._mockActiveLSId = 'ls_a';
_makeEl('ls-config-editor');
panel.render();
assertContains(_domElements['ls-config-editor']._html, 'ConfigA', '13. render A');
global._mockActiveLSId = 'ls_b';
panel.render();
html = _domElements['ls-config-editor']._html;
assertContains(html, 'ConfigB', '13. render B');
assertContains(html, '待更新', '13. B: stale');
assertContains(html, '0.001', '13. B: fee rate');
global._mockActiveLSId = null;
panel.render();
assertContains(_domElements['ls-config-editor']._html, '请在左侧列表中选择', '13. none: placeholder');

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------

console.log('');
console.log('=== Results ===');
console.log('Passed: ' + passed);
console.log('Failed: ' + failed);

if (failed > 0) process.exit(1);
