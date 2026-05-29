/**
 * test_panels_base_rebalance.js — Node.js tests for panels/base/rebalance.js
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
// Mock state
// ---------------------------------------------------------------------------

var mockBG = [];
var _uiUpdateCalls = [];

function resetAll() {
    mockBG = [];
    _uiUpdateCalls = [];
    global._mockActiveBGId = null;
    _domElements = {};
    _bodyHTML = '';
    global._events = {};
}

// ---------------------------------------------------------------------------
// Mock DOM
// ---------------------------------------------------------------------------

var _domElements = {};

global.document = {
    getElementById: function(id) {
        var el = _domElements[id];
        return el || null;
    },
    body: { insertAdjacentHTML: function(pos, html) { _bodyHTML += html; } },
};

function _makeEl(id) {
    var el = {
        id: id, _html: '', _listeners: {}, _textContent: '', _value: '',
        get innerHTML() { return this._html; },
        set innerHTML(v) {
            this._html = v;
            // Scan for child ids and create them
            var re = /id="([^"]+)"/g;
            var m;
            while ((m = re.exec(v)) !== null) {
                var childId = m[1];
                if (!_domElements[childId]) {
                    _domElements[childId] = _makeEl(childId);
                }
            }
        },
        get textContent() { return this._textContent; },
        set textContent(v) { this._textContent = v; },
        get value() { return this._value; },
        set value(v) { this._value = v; },
        addEventListener: function(evt, fn) {
            if (!this._listeners[evt]) this._listeners[evt] = [];
            this._listeners[evt].push(fn);
        },
        _fire: function(evt, e) {
            var fns = this._listeners[evt] || [];
            for (var i = 0; i < fns.length; i++) fns[i](e || {});
        },
        querySelector: function() { return null; },
        querySelectorAll: function() { return []; },
    };
    _domElements[id] = el;
    return el;
}

global.confirm = function() { return true; };
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
                update: function(id, patch) {
                    _uiUpdateCalls.push({ id: id, patch: JSON.parse(JSON.stringify(patch)) });
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
    },
};

// ---------------------------------------------------------------------------
// Load module
// ---------------------------------------------------------------------------

require('../../static/js/modules/single_factor_test/group_test/panels/base/rebalance.js');

var GT = window.GroupTest;
var panel = GT.panels.base.rebalance;

// ---------------------------------------------------------------------------
// 1. Module exports
// ---------------------------------------------------------------------------

resetAll();
assert(typeof panel === 'object', 'exports: panel is object');
assert(typeof panel.mount === 'function', 'exports: mount');
assert(typeof panel.unmount === 'function', 'exports: unmount');
assert(typeof panel.refresh === 'function', 'exports: refresh');
assert(typeof panel.render === 'function', 'exports: render');

// ---------------------------------------------------------------------------
// 2. render — no active group
// ---------------------------------------------------------------------------

resetAll();
_makeEl('base-rebalance');
panel.render();
var html = _domElements['base-rebalance']._html;
assert(html.indexOf('请先在基础组列表中选择一个基础组') !== -1, 'no active: placeholder');

// ---------------------------------------------------------------------------
// 3. render — default buy_and_hold
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Test', testerId: 't', factorAlias: 'f', groupCount: 5, rebalanceMode: 'buy_and_hold' });
global._mockActiveBGId = 'bg_1';
_makeEl('base-rebalance');
panel.render();
html = _domElements['base-rebalance']._html;
assert(html.indexOf('组内持仓不动') !== -1, 'buy_and_hold: label shown');
assert(html.indexOf('rb-mode-select') !== -1, 'buy_and_hold: select exists');

// ---------------------------------------------------------------------------
// 4. render — each_period
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_2', name: 'Test', testerId: 't', factorAlias: 'f', groupCount: 5, rebalanceMode: 'each_period' });
global._mockActiveBGId = 'bg_2';
_makeEl('base-rebalance');
panel.render();
html = _domElements['base-rebalance']._html;
assert(html.indexOf('每期等权再平衡') !== -1, 'each_period: label shown');
assert(html.indexOf('换手通常最高') !== -1, 'each_period: description shown');

// ---------------------------------------------------------------------------
// 5. render — recycle
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_3', name: 'Test', testerId: 't', factorAlias: 'f', groupCount: 5, rebalanceMode: 'recycle' });
global._mockActiveBGId = 'bg_3';
_makeEl('base-rebalance');
panel.render();
html = _domElements['base-rebalance']._html;
assert(html.indexOf('退出资金优先补新仓') !== -1, 'recycle: label shown');

// ---------------------------------------------------------------------------
// 6. render — missing rebalanceMode defaults to buy_and_hold
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_4', name: 'Test', testerId: 't', factorAlias: 'f', groupCount: 5 });
global._mockActiveBGId = 'bg_4';
_makeEl('base-rebalance');
panel.render();
html = _domElements['base-rebalance']._html;
assert(html.indexOf('组内持仓不动') !== -1, 'default: buy_and_hold as default');

// ---------------------------------------------------------------------------
// 7. select change updates description + saves
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_5', name: 'Test', testerId: 't', factorAlias: 'f', groupCount: 5, rebalanceMode: 'buy_and_hold' });
global._mockActiveBGId = 'bg_5';
_makeEl('base-rebalance');
panel.render();

var select = _domElements['rb-mode-select'];
assert(select !== undefined, 'select: element exists');

// Simulate selecting 'each_period'
select._value = 'each_period';
select._fire('change');

assertEquals(_uiUpdateCalls.length, 1, 'select: 1 update call');
assert(_uiUpdateCalls[0].patch.rebalanceMode === 'each_period', 'select: rebalanceMode updated to each_period');

// Description should change
var desc = _domElements['rb-mode-desc'];
assert(desc._textContent.indexOf('换手通常最高') !== -1, 'select: description updated');

// ---------------------------------------------------------------------------
// 8. mount lifecycle
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Test', testerId: 't', factorAlias: 'f', groupCount: 5, rebalanceMode: 'each_period' });
global._mockActiveBGId = 'bg_1';
_makeEl('base-rebalance');
panel.mount();
assert(global._events['baseGroupsChanged'].length >= 1, 'mount: registered baseGroupsChanged');
assert(global._events['activeBaseGroupChanged'].length >= 1, 'mount: registered activeBaseGroupChanged');
assert(_domElements['base-rebalance']._html.indexOf('每期等权再平衡') !== -1, 'mount: rendered');

panel.unmount();
assert(global._events['baseGroupsChanged'].length === 0, 'unmount: cleared baseGroupsChanged');
assert(global._events['activeBaseGroupChanged'].length === 0, 'unmount: cleared activeBaseGroupChanged');

// ---------------------------------------------------------------------------
// 9. activeBaseGroupChanged triggers re-render
// ---------------------------------------------------------------------------

resetAll();
_makeEl('base-rebalance');
panel.mount();
mockBG.push({ id: 'bg_6', name: 'G6', testerId: 't', factorAlias: 'f', groupCount: 3, rebalanceMode: 'recycle' });
global._mockActiveBGId = 'bg_6';
GT.state.emit('activeBaseGroupChanged', { id: 'bg_6' });
assert(_domElements['base-rebalance']._html.indexOf('退出资金优先补新仓') !== -1, 'after select: shows recycle');

panel.unmount();

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------

console.log('\n=== Results ===');
console.log('Passed: ' + passed);
console.log('Failed: ' + failed);
if (failed > 0) process.exit(1);
