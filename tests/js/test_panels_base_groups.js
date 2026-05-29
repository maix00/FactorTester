/**
 * test_panels_base_groups.js — Node.js tests for panels/base/groups.js
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
        id: id, _html: '', _listeners: {}, _textContent: '', _value: '', _disabled: false, _checked: false,
        get innerHTML() { return this._html; },
        set innerHTML(v) {
            this._html = v;
            var re = /id="([^"]+)"/g;
            var m;
            while ((m = re.exec(v)) !== null) {
                var childId = m[1];
                if (!_domElements[childId]) {
                    _domElements[childId] = _makeEl(childId);
                }
            }
            // Detect disabled attribute for child elements
            var disRe = /id="([^"]+)"[^>]*\bdisabled\b/g;
            var dm;
            while ((dm = disRe.exec(v)) !== null) {
                var disId = dm[1];
                if (_domElements[disId]) {
                    _domElements[disId]._disabled = true;
                }
            }
        },
        get textContent() { return this._textContent; },
        set textContent(v) { this._textContent = v; },
        get value() { return this._value; },
        set value(v) { this._value = v; },
        get disabled() { return this._disabled; },
        set disabled(v) { this._disabled = v; },
        get checked() { return this._checked; },
        set checked(v) { this._checked = v; },
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

require('../../static/js/modules/single_factor_test/group_test/panels/base/groups.js');

var GT = window.GroupTest;
var panel = GT.panels.base.groups;

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
_makeEl('base-groups-settings');
panel.render();
var html = _domElements['base-groups-settings']._html;
assert(html.indexOf('请先在基础组列表中选择一个基础组') !== -1, 'no active: placeholder');

// ---------------------------------------------------------------------------
// 3. render — normal group (not isAllGroups)
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Test', testerId: 't', factorAlias: 'f', groupCount: 7, groupIndex: 2, isAllGroups: false, startDate: '', endDate: '' });
global._mockActiveBGId = 'bg_1';
_makeEl('base-groups-settings');
panel.render();
html = _domElements['base-groups-settings']._html;
assert(html.indexOf('gs-group-count') !== -1, 'normal: groupCount input exists');
assert(html.indexOf('gs-group-index') !== -1, 'normal: groupIndex input exists');
assert(html.indexOf('gs-all-groups') !== -1, 'normal: allGroups checkbox exists');
assert(html.indexOf('value="7"') !== -1, 'normal: groupCount = 7');
assert(html.indexOf('value="2"') !== -1, 'normal: groupIndex = 2');
// Inputs should NOT be disabled when isAllGroups=false
var gcInput = _domElements['gs-group-count'];
assert(gcInput._disabled === false, 'normal: groupCount not disabled');

// ---------------------------------------------------------------------------
// 4. render — isAllGroups=true disables groupCount/groupIndex
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_2', name: 'Test', testerId: 't', factorAlias: 'f', groupCount: 5, groupIndex: 0, isAllGroups: true });
global._mockActiveBGId = 'bg_2';
_makeEl('base-groups-settings');
panel.render();
gcInput = _domElements['gs-group-count'];
assert(gcInput._disabled === true, 'allGroups: groupCount disabled');

// ---------------------------------------------------------------------------
// 5. render — time range fields
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_3', name: 'Test', testerId: 't', factorAlias: 'f', groupCount: 5, groupIndex: 0, startDate: '2024-01-01', endDate: '2024-12-31' });
global._mockActiveBGId = 'bg_3';
_makeEl('base-groups-settings');
panel.render();
html = _domElements['base-groups-settings']._html;
assert(html.indexOf('gs-start-date') !== -1, 'time: startDate input exists');
assert(html.indexOf('gs-end-date') !== -1, 'time: endDate input exists');
assert(html.indexOf('value="2024-01-01"') !== -1, 'time: startDate value');
assert(html.indexOf('value="2024-12-31"') !== -1, 'time: endDate value');

// ---------------------------------------------------------------------------
// 6. save on groupCount change
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_4', name: 'Test', testerId: 't', factorAlias: 'f', groupCount: 5, groupIndex: 0 });
global._mockActiveBGId = 'bg_4';
_makeEl('base-groups-settings');
panel.render();

var gcInput = _domElements['gs-group-count'];
gcInput._value = '8';
gcInput._fire('change');
assert(_uiUpdateCalls.length === 1, 'save: 1 update on groupCount change');
assert(_uiUpdateCalls[0].patch.groupCount === 8, 'save: groupCount = 8');

// ---------------------------------------------------------------------------
// 7. save on groupIndex change
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_5', name: 'Test', testerId: 't', factorAlias: 'f', groupCount: 5, groupIndex: 0 });
global._mockActiveBGId = 'bg_5';
_makeEl('base-groups-settings');
panel.render();

var giInput = _domElements['gs-group-index'];
giInput._value = '3';
giInput._fire('change');
assert(_uiUpdateCalls[0].patch.groupIndex === 3, 'save: groupIndex = 3');

// ---------------------------------------------------------------------------
// 8. allGroups toggle disables count/index
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_6', name: 'Test', testerId: 't', factorAlias: 'f', groupCount: 5, groupIndex: 0, isAllGroups: false });
global._mockActiveBGId = 'bg_6';
_makeEl('base-groups-settings');
panel.render();

var agCheck = _domElements['gs-all-groups'];
agCheck._checked = true;
agCheck._fire('change');
assert(_domElements['gs-group-count']._disabled === true, 'allGroups toggle: groupCount disabled');
assert(_domElements['gs-group-index']._disabled === true, 'allGroups toggle: groupIndex disabled');

// ---------------------------------------------------------------------------
// 9. sync button
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_7', name: 'Test', testerId: 't', factorAlias: 'f', groupCount: 5, groupIndex: 2, isAllGroups: false, strategyGroupCount: 10, strategyIsAllGroups: true });
global._mockActiveBGId = 'bg_7';
_makeEl('base-groups-settings');
panel.render();

var syncBtn = _domElements['gs-sync-btn'];
assert(syncBtn !== undefined, 'sync: button exists');
syncBtn._fire('click');
assert(_uiUpdateCalls.length >= 1, 'sync: update called');
assert(_uiUpdateCalls[0].patch.groupCount === 10, 'sync: groupCount pulled from strategy');
assert(_uiUpdateCalls[0].patch.groupIndex === 0, 'sync: groupIndex reset to 0');
assert(_uiUpdateCalls[0].patch.isAllGroups === true, 'sync: isAllGroups pulled from strategy');

// ---------------------------------------------------------------------------
// 10. mount lifecycle
// ---------------------------------------------------------------------------

resetAll();
mockBG.push({ id: 'bg_1', name: 'Test', testerId: 't', factorAlias: 'f', groupCount: 5, groupIndex: 0 });
global._mockActiveBGId = 'bg_1';
_makeEl('base-groups-settings');
panel.mount();
assert(global._events['baseGroupsChanged'].length >= 1, 'mount: registered baseGroupsChanged');
assert(global._events['activeBaseGroupChanged'].length >= 1, 'mount: registered activeBaseGroupChanged');
assert(_domElements['base-groups-settings']._html.indexOf('gs-group-count') !== -1, 'mount: rendered');

panel.unmount();
assert(global._events['baseGroupsChanged'].length === 0, 'unmount: cleared');
assert(global._events['activeBaseGroupChanged'].length === 0, 'unmount: cleared');

// ---------------------------------------------------------------------------
// 11. activeBaseGroupChanged triggers re-render
// ---------------------------------------------------------------------------

resetAll();
_makeEl('base-groups-settings');
panel.mount();
assert(_domElements['base-groups-settings']._html.indexOf('请先在') !== -1, 'before: placeholder');

mockBG.push({ id: 'bg_8', name: 'G8', testerId: 't', factorAlias: 'f', groupCount: 12, groupIndex: 3, isAllGroups: false });
global._mockActiveBGId = 'bg_8';
GT.state.emit('activeBaseGroupChanged', { id: 'bg_8' });
assert(_domElements['base-groups-settings']._html.indexOf('value="12"') !== -1, 'after select: groupCount = 12');

panel.unmount();

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------

console.log('\n=== Results ===');
console.log('Passed: ' + passed);
console.log('Failed: ' + failed);
if (failed > 0) process.exit(1);
