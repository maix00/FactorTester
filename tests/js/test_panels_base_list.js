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
                batchKey: function(testerId, factorAlias, groupCount) {
                    return String(testerId) + '|' + factorAlias + '|' + groupCount;
                },
                extractLetter: function(shortAlias) {
                    if (!shortAlias) return null;
                    var m = shortAlias.match(/^([A-Z]+)/);
                    return m ? m[1] : null;
                },
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
    GT_CONFIG_REGISTRY: {
        _items: {},
        register: function(def, containerId) {
            this._items[def.name] = { def: def, containerId: containerId };
        },
        getAll: function() { return Object.values(this._items); },
        getTableColumns: function() {
            var cols = [];
            Object.values(this._items).forEach(function(entry) {
                if (entry.def.panel && entry.def.panel.getTableColumns) {
                    cols = cols.concat(entry.def.panel.getTableColumns());
                }
            });
            return cols;
        },
        toPanelEntry: function(name, label, containerId) {
            return { name: name, label: label, containerId: containerId, category: 3, panel: this._items[name].def.panel };
        },
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
// 3. render — with data (single-group batches = numeric alias, no expand arrow)
// ---------------------------------------------------------------------------

resetAll();
mockBG = [
    { id: 'bg_1', name: 'Group A', shortAlias: '1', testerId: 't1', factorAlias: 'factor_a', groupCount: 5, groupIndex: 1, isAllGroups: false, feeMode: 'none', rebalanceMode: 'each_period' },
    { id: 'bg_2', name: 'Group B', shortAlias: '2', testerId: 't2', factorAlias: 'factor_b', groupCount: 3, groupIndex: 2, isAllGroups: false, feeMode: 'none', rebalanceMode: 'each_period' },
];

var container = _makeContainer('base-groups-list');
panel.render();
var html = container._html;
// New list shows shortAlias (numeric alias) and factor, not "name"
assert(html.indexOf('factor_a') !== -1, 'render: shows factor_a');
assert(html.indexOf('factor_b') !== -1, 'render: shows factor_b');
assert(html.indexOf('t2') !== -1, 'render: shows testerId t2');
// ShortAlias (numeric) appears in the alias cell
assert(html.indexOf('>1<') !== -1 || html.indexOf('>1</') !== -1, 'render: shows shortAlias 1');
assert(html.indexOf('>2<') !== -1 || html.indexOf('>2</') !== -1, 'render: shows shortAlias 2');
// Group index/count
assert(html.indexOf('1/5') !== -1, 'render: shows 1/5');
assert(html.indexOf('2/3') !== -1, 'render: shows 2/3');
// data-bg-id only on expanded child rows (single-group batches are not expanded)
// Batch header has data-batch-key
assert(html.indexOf('data-batch-key=') !== -1, 'render: has data-batch-key');

// ---------------------------------------------------------------------------
// 4. mount — sets up event handlers, renders
// ---------------------------------------------------------------------------

resetAll();
mockBG = [{ id: 'bg_x', name: 'x1', shortAlias: '1', testerId: 't', factorAlias: 'f', groupCount: 2, groupIndex: 1, isAllGroups: false, feeMode: 'none', rebalanceMode: 'each_period' }];
_makeContainer('base-groups-list');
panel.mount();
assert(_domElements['base-groups-list']._html.indexOf('factor_a') === -1, 'mount: no stale factor_a');
assert(_domElements['base-groups-list']._html.indexOf('>f<') !== -1 || _domElements['base-groups-list']._html.indexOf('>f</') !== -1, 'mount: renders factor f');
panel.unmount();

// ---------------------------------------------------------------------------
// 5. render after data changes (add → render → verify)
// ---------------------------------------------------------------------------

resetAll();
_makeContainer('base-groups-list');
panel.render();
assert(_domElements['base-groups-list']._html.indexOf('暂无基础组') !== -1, 'initial: empty');

// Add via mock
mockBG.push({ id: 'bg_new', name: 'NewGroup', shortAlias: '1', testerId: 't1', factorAlias: 'f1', groupCount: 3, groupIndex: 1, isAllGroups: false, feeMode: 'none', rebalanceMode: 'each_period' });
panel.render();
assert(_domElements['base-groups-list']._html.indexOf('f1') !== -1, 'after add: shows factor f1');
assert(_domElements['base-groups-list']._html.indexOf('1/3') !== -1, 'after add: shows 1/3');

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
