/**
 * test_panels_base_list.js — Node.js tests for panels/base/list.js
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

// Create a mock container element
function _makeContainer(id) {
    var el = {
        id: id,
        _html: '',
        get innerHTML() { return this._html; },
        set innerHTML(v) {
            this._html = v;
            // Parse data-bg-id attributes from HTML for querySelectorAll
            this._dataIds = [];
            var re = /data-bg-id="([^"]+)"/g;
            var m;
            while ((m = re.exec(v)) !== null) {
                this._dataIds.push(m[1]);
            }
        },
        querySelectorAll: function(sel) {
            if (sel === '.grouptest-base-row') {
                var ids = this._dataIds || [];
                return ids.map(function(did) {
                    return {
                        getAttribute: function(attr) { return attr === 'data-bg-id' ? did : null; },
                        classList: { add: function() {}, remove: function() {} },
                        style: {},
                        addEventListener: function(evt, fn) {
                            // Store handler
                            this['_on_' + evt] = fn;
                        },
                    };
                });
            }
            if (sel === '.grouptest-edit-btn') {
                var ids = this._dataIds || [];
                return ids.map(function(did) {
                    return {
                        getAttribute: function(attr) { return attr === 'data-bg-id' ? did : null; },
                        addEventListener: function(evt, fn) {
                            this['_on_' + evt] = fn;
                        },
                    };
                });
            }
            if (sel === '.grouptest-del-btn') {
                var ids = this._dataIds || [];
                return ids.map(function(did) {
                    return {
                        getAttribute: function(attr) { return attr === 'data-bg-id' ? did : null; },
                        addEventListener: function(evt, fn) {
                            this['_on_' + evt] = fn;
                        },
                    };
                });
            }
            return [];
        },
        querySelector: function(sel) {
            if (sel.indexOf('[data-bg-id="') === 0) {
                // Extract id from selector
                var m = sel.match(/data-bg-id="([^"]+)"/);
                if (m) {
                    return {
                        getAttribute: function() { return m[1]; },
                        classList: { add: function() {}, remove: function() {} },
                        style: {},
                    };
                }
            }
            return null;
        },
    };
    _domElements[id] = el;
    return el;
}

function resetAll() {
    mockBG = [];
    _domElements = {};
    _bodyHTML = '';
    global._mockActiveBGId = null;
}

// ---------------------------------------------------------------------------
// Mock window.GroupTest
// ---------------------------------------------------------------------------

global._mockActiveBGId = null;
global.confirm = function() { return true; };
global.alert = function() {};

global.window = {
    GroupTest: {
        datamodel: {
            base_groups: {
                getAll: function() { return JSON.parse(JSON.stringify(mockBG)); },
                get: function(id) {
                    for (var i = 0; i < mockBG.length; i++) {
                        if (mockBG[i].id === id) return JSON.parse(JSON.stringify(mockBG[i]));
                    }
                    return null;
                },
                add: function(config) {
                    var id = 'bg_add_' + (mockBG.length + 1);
                    var item = JSON.parse(JSON.stringify(config));
                    item.id = id;
                    mockBG.push(item);
                    // emit
                    window.GroupTest.state.emit('baseGroupsChanged', { action: 'add', id: id });
                    return id;
                },
                update: function(id, patch) {
                    for (var i = 0; i < mockBG.length; i++) {
                        if (mockBG[i].id === id) {
                            Object.keys(patch).forEach(function(k) { mockBG[i][k] = patch[k]; });
                            window.GroupTest.state.emit('baseGroupsChanged', { action: 'update', id: id });
                            return JSON.parse(JSON.stringify(mockBG[i]));
                        }
                    }
                    throw new Error('not found');
                },
                remove: function(id) {
                    for (var i = 0; i < mockBG.length; i++) {
                        if (mockBG[i].id === id) {
                            mockBG.splice(i, 1);
                            window.GroupTest.state.emit('baseGroupsChanged', { action: 'remove', id: id });
                            return;
                        }
                    }
                    throw new Error('not found');
                },
            },
        },
        state: {
            emit: function() {},
            on: function() {},
            off: function() {},
            getActiveBaseGroupId: function() { return global._mockActiveBGId || null; },
            setActiveBaseGroupId: function(id) {
                global._mockActiveBGId = id;
            },
        },
        panels: {},
        log: function() {},
    },
};

// ---------------------------------------------------------------------------
// Load module
// ---------------------------------------------------------------------------

require('../../static/js/modules/single_factor_test/group_test/panels/base/list.js');

var GT = window.GroupTest;
var panel = GT.panels.base.list;

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
// 2. render — empty state
// ---------------------------------------------------------------------------

resetAll();
_makeContainer('base-groups-list');
panel.render();
var el = _domElements['base-groups-list'];
assert(el._html.indexOf('暂无基础组') !== -1, 'render empty: shows empty message');

// ---------------------------------------------------------------------------
// 3. render — with data
// ---------------------------------------------------------------------------

resetAll();
mockBG = [
    { id: 'bg_1', name: 'Group A', testerId: 't1', factorAlias: 'factor_a', groupCount: 5, groupIndex: 0, isAllGroups: false },
    { id: 'bg_2', name: 'Group B', testerId: 't2', factorAlias: 'factor_b', groupCount: 3, groupIndex: 1, isAllGroups: true },
];

var container = _makeContainer('base-groups-list');
panel.render();
var html = container._html;
assert(html.indexOf('Group A') !== -1, 'render: shows Group A name');
assert(html.indexOf('Group B') !== -1, 'render: shows Group B name');
assert(html.indexOf('factor_a') !== -1, 'render: shows factor_a');
assert(html.indexOf('t2') !== -1, 'render: shows testerId t2');
assert(html.indexOf('data-bg-id="bg_1"') !== -1, 'render: has data-bg-id for bg_1');
assert(html.indexOf('data-bg-id="bg_2"') !== -1, 'render: has data-bg-id for bg_2');

// ---------------------------------------------------------------------------
// 4. mount — sets up event handlers, renders
// ---------------------------------------------------------------------------

resetAll();
mockBG = [{ id: 'bg_x', name: 'x1', testerId: 't', factorAlias: 'f', groupCount: 2, groupIndex: 0, isAllGroups: false }];
_makeContainer('base-groups-list');
panel.mount();
assert(_domElements['base-groups-list']._html.indexOf('x1') !== -1, 'mount: renders data');
panel.unmount();

// ---------------------------------------------------------------------------
// 5. render after data changes (add → render → verify)
// ---------------------------------------------------------------------------

resetAll();
_makeContainer('base-groups-list');
panel.render();
assert(_domElements['base-groups-list']._html.indexOf('暂无基础组') !== -1, 'initial: empty');

// Add via mock
mockBG.push({ id: 'bg_new', name: 'NewGroup', testerId: 't1', factorAlias: 'f1', groupCount: 3, groupIndex: 0, isAllGroups: false });
panel.render();
assert(_domElements['base-groups-list']._html.indexOf('NewGroup') !== -1, 'after add: shows NewGroup');

// Remove
mockBG = [];
panel.render();
assert(_domElements['base-groups-list']._html.indexOf('暂无基础组') !== -1, 'after remove: shows empty state');

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------

console.log('\n=== Results ===');
console.log('Passed: ' + passed);
console.log('Failed: ' + failed);
if (failed > 0) process.exit(1);
