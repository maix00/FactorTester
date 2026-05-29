/**
 * test_panels_base_close_today.js — Node.js tests for panels/base/close_today.js
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
var _bodyHTML = '';

global.document = {
    getElementById: function(id) {
        var el = _domElements[id];
        if (!el) return null;
        // Auto-create child elements from innerHTML references
        // (for buttons/inputs referenced by getElementById after render)
        return el;
    },
    body: {
        insertAdjacentHTML: function(pos, html) {
            _bodyHTML += html;
        },
    },
};

function _makeEl(id) {
    var el = {
        id: id, _html: '', _listeners: {}, _textContent: '',
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

require('../../static/js/modules/single_factor_test/group_test/panels/base/close_today.js');

var GT = window.GroupTest;
var panel = GT.panels.base.close_today;

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
_makeEl('base-close-today');
panel.render();
var html = _domElements['base-close-today']._html;
assert(html.indexOf('请先在基础组列表中选择一个基础组') !== -1, 'no active: placeholder');

// ---------------------------------------------------------------------------
// 3. render — useCloseToday=false (平昨仓)
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Test', testerId: 't', factorAlias: 'f', groupCount: 5, useCloseToday: false });
global._mockActiveBGId = 'bg_1';
_makeEl('base-close-today');
panel.render();
html = _domElements['base-close-today']._html;
assert(html.indexOf('平昨仓') !== -1, 'false: shows 平昨仓');
assert(html.indexOf('切换为平今仓') !== -1, 'false: shows switch-to-close-today button');

// ---------------------------------------------------------------------------
// 4. render — useCloseToday=true (平今仓)
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_2', name: 'Test', testerId: 't', factorAlias: 'f', groupCount: 5, useCloseToday: true });
global._mockActiveBGId = 'bg_2';
_makeEl('base-close-today');
panel.render();
html = _domElements['base-close-today']._html;
assert(html.indexOf('平今仓') !== -1, 'true: shows 平今仓');
assert(html.indexOf('切换为平昨仓') !== -1, 'true: shows switch-to-close-yesterday button');

// ---------------------------------------------------------------------------
// 5. toggle — click button updates datamodel
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_3', name: 'Test', testerId: 't', factorAlias: 'f', groupCount: 5, useCloseToday: false });
global._mockActiveBGId = 'bg_3';
_makeEl('base-close-today');
panel.render();

// Simulate click
var btn = _domElements['ct-toggle-btn'];
assert(btn !== undefined, 'toggle: button exists');
btn._fire('click');
assertEquals(_uiUpdateCalls.length, 1, 'toggle: 1 update call');
assert(_uiUpdateCalls[0].patch.useCloseToday === true, 'toggle: sets useCloseToday to true');

// Toggle back
_uiUpdateCalls = [];
mockBG[0].useCloseToday = true;
panel.render();
btn = _domElements['ct-toggle-btn'];
btn._fire('click');
assert(_uiUpdateCalls[0].patch.useCloseToday === false, 'toggle: sets useCloseToday to false');

// ---------------------------------------------------------------------------
// 6. mount lifecycle
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Test', testerId: 't', factorAlias: 'f', groupCount: 5, useCloseToday: false });
global._mockActiveBGId = 'bg_1';
_makeEl('base-close-today');
panel.mount();
assert(global._events['baseGroupsChanged'].length >= 1, 'mount: registered baseGroupsChanged');
assert(global._events['activeBaseGroupChanged'].length >= 1, 'mount: registered activeBaseGroupChanged');
assert(_domElements['base-close-today']._html.indexOf('平昨仓') !== -1, 'mount: rendered');

panel.unmount();
assert(global._events['baseGroupsChanged'].length === 0, 'unmount: cleared baseGroupsChanged');
assert(global._events['activeBaseGroupChanged'].length === 0, 'unmount: cleared activeBaseGroupChanged');

// ---------------------------------------------------------------------------
// 7. activeBaseGroupChanged triggers re-render
// ---------------------------------------------------------------------------

resetAll();
_makeEl('base-close-today');
panel.mount();
assert(_domElements['base-close-today']._html.indexOf('请先在') !== -1, 'before: placeholder');

mockBG.push({ id: 'bg_4', name: 'G4', testerId: 't', factorAlias: 'f', groupCount: 3, useCloseToday: true });
global._mockActiveBGId = 'bg_4';
GT.state.emit('activeBaseGroupChanged', { id: 'bg_4' });
assert(_domElements['base-close-today']._html.indexOf('平今仓') !== -1, 'after select: shows 平今仓');

panel.unmount();

// ---------------------------------------------------------------------------
// 8. unmount ignores events
// ---------------------------------------------------------------------------

resetAll();
_makeEl('base-close-today');
panel.mount();
panel.unmount();
var htmlBefore = _domElements['base-close-today']._html;
mockBG.push({ id: 'bg_5', name: 'G5', testerId: 't', factorAlias: 'f', groupCount: 2, useCloseToday: true });
GT.state.emit('baseGroupsChanged', {});
assertEquals(_domElements['base-close-today']._html, htmlBefore, 'unmounted: no reaction');

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------

console.log('\n=== Results ===');
console.log('Passed: ' + passed);
console.log('Failed: ' + failed);
if (failed > 0) process.exit(1);
