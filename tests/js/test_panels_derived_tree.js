/**
 * test_panels_derived_tree.js — Node.js tests for panels/derived/tree.js
 */

var passed = 0, failed = 0;

function assert(condition, msg) {
    if (condition) { passed++; }
    else { console.log('FAIL: ' + msg); failed++; }
}

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
            // Parse HTML for id attributes and create mock elements
            var idRe = /\bid="([^"]+)"/g;
            var im;
            while ((im = idRe.exec(html)) !== null) {
                var elId = im[1];
                // Always recreate to clear stale state from previous forms
                _domElements[elId] = _makeEl(elId);
            }
        },
    },
};

// Cache for event-listeners on queried elements, keyed by selector + data-id
var _eventCache = {};

function _cacheKey(sel, did) { return sel + '|' + did; }

function _makeQueryEl(sel, did) {
    var key = _cacheKey(sel, did);
    if (_eventCache[key]) return _eventCache[key];
    var el = {
        _sel: sel,
        _did: did,
        _listeners: {},
        classList: { add: function() {}, remove: function() {} },
        style: {},
        getAttribute: function(attr) { return attr === 'data-dg-id' ? did : null; },
        addEventListener: function(evt, fn) {
            if (!this._listeners[evt]) this._listeners[evt] = [];
            var self = this;
            // Wrap so fn is called with correct 'this'
            this._listeners[evt].push(function(e) { return fn.call(self, e); });
        },
    };
    _eventCache[key] = el;
    return el;
}

// Also cache #derived-add-root-btn
var _addRootBtn = null;

function _makeEl(id) {
    var el = {
        id: id,
        _html: '',
        _listeners: {},
        _textContent: '',
        _value: '',
        get value() { return this._value; },
        set value(v) { this._value = v; },
        _disabled: false,
        _checked: false,
        _selectedIndex: -1,
        _options: [],
        _children: [],
        _datasetIds: [],
        get innerHTML() { return this._html; },
        set innerHTML(v) {
            this._html = v;
            // Parse data-dg-id from HTML
            this._datasetIds = [];
            var re = /data-dg-id="([^"]+)"/g;
            var m;
            while ((m = re.exec(v)) !== null) {
                this._datasetIds.push(m[1]);
            }
            // Detect disabled attribute
            var disRe = /id="([^"]+)"[^>]*\bdisabled\b/g;
            var dm;
            while ((dm = disRe.exec(v)) !== null) {
                if (_domElements[dm[1]]) {
                    _domElements[dm[1]]._disabled = true;
                }
            }
        },
        querySelectorAll: function(sel) {
            var ids = this._datasetIds || [];
            if (sel === '.derived-tree-node' || sel === '.derived-toggle' ||
                sel === '.derived-add-child-btn' || sel === '.derived-edit-btn' ||
                sel === '.derived-del-btn') {
                return ids.map(function(did) { return _makeQueryEl(sel, did); });
            }
            return [];
        },
        querySelector: function(sel) {
            if (sel.indexOf('[data-dg-id="') === 0) {
                var m = sel.match(/data-dg-id="([^"]+)"/);
                if (m) return _makeQueryEl('.derived-tree-node', m[1]);
            }
            if (sel === '#derived-add-root-btn') {
                if (!_addRootBtn) {
                    _addRootBtn = { _listeners: {}, addEventListener: function(evt, fn) {
                        if (!this._listeners[evt]) this._listeners[evt] = [];
                        var self = this;
                        this._listeners[evt].push(function(e) { return fn.call(self, e); });
                    }};
                }
                return _addRootBtn;
            }
            return null;
        },
        addEventListener: function(evt, fn) {
            if (!this._listeners[evt]) this._listeners[evt] = [];
            this._listeners[evt].push(fn);
        },
        remove: function() {
            delete _domElements[this.id];
        },
    };
    _domElements[id] = el;
    return el;
}

// Override document.getElementById to support auto-create for form elements
var origGetEl = global.document.getElementById;
global.document.getElementById = function(id) {
    if (_domElements[id]) return _domElements[id];
    // Auto-create elements referenced in form code
    if (id && (id.startsWith('dnf_') || id.startsWith('derived-'))) {
        return _makeEl(id);
    }
    return null;
};

global.confirm = function() { return true; };
global.alert = function() {};

// ---------------------------------------------------------------------------
// Mock datamodel: derived_graph
// ---------------------------------------------------------------------------

var _nodes = [];
var _idCounter = 0;

function _uuid() { _idCounter++; return 'dg_' + _idCounter; }

var mockDerivedGraph = {
    get: function(id) {
        for (var i = 0; i < _nodes.length; i++) {
            if (_nodes[i].id === id) return JSON.parse(JSON.stringify(_nodes[i]));
        }
        return null;
    },
    getAll: function() {
        return JSON.parse(JSON.stringify(_nodes));
    },
    getTree: function() {
        // Build tree from flat _nodes
        function build(id) {
            for (var i = 0; i < _nodes.length; i++) {
                if (_nodes[i].id === id) {
                    var node = JSON.parse(JSON.stringify(_nodes[i]));
                    node.children = [];
                    for (var j = 0; j < _nodes.length; j++) {
                        if (_nodes[j].parentId === id) {
                            node.children.push(build(_nodes[j].id));
                        }
                    }
                    return node;
                }
            }
            return null;
        }
        var roots = [];
        for (var i = 0; i < _nodes.length; i++) {
            if (!_nodes[i].parentId) {
                roots.push(build(_nodes[i].id));
            }
        }
        return roots;
    },
    add: function(config) {
        var node = {
            id: _uuid(),
            name: config.name,
            parentId: config.parentId || null,
            baseGroupId: config.baseGroupId,
            isAutoGenerated: config.isAutoGenerated || false,
            productMask: config.productMask || {},
            feeOverride: null,
            closeTodayOverride: null,
            rebalanceOverride: null,
            metadata: {},
        };
        _nodes.push(node);
        window.GroupTest.state.emit('derivedGraphChanged', { action: 'add', id: node.id });
        return JSON.parse(JSON.stringify(node));
    },
    update: function(id, patch) {
        for (var i = 0; i < _nodes.length; i++) {
            if (_nodes[i].id === id) {
                Object.keys(patch).forEach(function(k) { _nodes[i][k] = patch[k]; });
                window.GroupTest.state.emit('derivedGraphChanged', { action: 'update', id: id });
                return JSON.parse(JSON.stringify(_nodes[i]));
            }
        }
        throw new Error('not found');
    },
    remove: function(id) {
        // Cascade remove descendants
        function collectDescendants(parentId) {
            var ids = [parentId];
            for (var i = 0; i < _nodes.length; i++) {
                if (_nodes[i].parentId === parentId) {
                    ids = ids.concat(collectDescendants(_nodes[i].id));
                }
            }
            return ids;
        }
        var toRemove = collectDescendants(id);
        _nodes = _nodes.filter(function(n) { return toRemove.indexOf(n.id) === -1; });
        window.GroupTest.state.emit('derivedGraphChanged', { action: 'remove', id: id, removedIds: toRemove });
    },
    list: function() {
        return _nodes.map(function(n) { return { id: n.id, name: n.name, parentId: n.parentId, baseGroupId: n.baseGroupId }; });
    },
    _reset: function() { _nodes = []; _idCounter = 0; },
};

// ---------------------------------------------------------------------------
// Mock datamodel: base_groups
// ---------------------------------------------------------------------------

var _baseGroups = [];

var mockBaseGroups = {
    getAll: function() { return JSON.parse(JSON.stringify(_baseGroups)); },
    get: function(id) {
        for (var i = 0; i < _baseGroups.length; i++) {
            if (_baseGroups[i].id === id) return JSON.parse(JSON.stringify(_baseGroups[i]));
        }
        return null;
    },
};

// ---------------------------------------------------------------------------
// Mock window.GroupTest
// ---------------------------------------------------------------------------

global._mockActiveDerivedId = null;

var _listeners = {};

global.window = {
    GroupTest: {
        datamodel: {
            derived_graph: mockDerivedGraph,
            base_groups: mockBaseGroups,
        },
        state: {
            _listeners: _listeners,
            on: function(event, cb) {
                if (!_listeners[event]) _listeners[event] = [];
                _listeners[event].push(cb);
            },
            off: function(event, cb) {
                if (!_listeners[event]) return;
                _listeners[event] = _listeners[event].filter(function(f) { return f !== cb; });
            },
            emit: function(event, data) {
                (_listeners[event] || []).forEach(function(f) { f(data); });
            },
            getActiveDerivedNodeId: function() { return global._mockActiveDerivedId || null; },
            setActiveDerivedNodeId: function(id) {
                global._mockActiveDerivedId = id;
                this.emit('activeDerivedNodeChanged', { id: id });
            },
            _registrations: {},
        },
        panels: {},
        log: function() {},
    },
};

// ---------------------------------------------------------------------------
// Load module
// ---------------------------------------------------------------------------

// Use relative path from tests/js/ to static/js/
require('../../static/js/modules/single_factor_test/group_test/panels/derived/tree.js');

var GT = window.GroupTest;
var panel = GT.panels.derived.tree;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function resetAll() {
    _nodes = [];
    _idCounter = 0;
    _baseGroups = [];
    _domElements = {};
    _eventCache = {};
    _addRootBtn = null;
    _bodyHTML = '';
    _listeners = {};
    global._mockActiveDerivedId = null;
    global.confirm = function() { return true; };
}

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
// 2. render — empty state
// ---------------------------------------------------------------------------

resetAll();
_makeEl('derived-tree');
panel.render();
var container = _domElements['derived-tree'];
assert(container && container._html.indexOf('暂无派生组') !== -1, 'render empty: shows empty message');

// ---------------------------------------------------------------------------
// 3. render — tree with root nodes
// ---------------------------------------------------------------------------

resetAll();
_baseGroups = [{ id: 'bg1', name: 'Base 1', testerId: 't1', factorAlias: 'f1', groupCount: 5 }];
_nodes = [
    { id: 'dg1', name: 'Root Node', parentId: null, baseGroupId: 'bg1', isAutoGenerated: true },
    { id: 'dg2', name: 'Child A', parentId: 'dg1', baseGroupId: 'bg1', isAutoGenerated: false },
    { id: 'dg3', name: 'Child B', parentId: 'dg1', baseGroupId: 'bg1', isAutoGenerated: false },
];

_makeEl('derived-tree');
panel.render();
var container = _domElements['derived-tree'];
var html = container._html;
assert(html.indexOf('Root Node') !== -1, 'tree: shows root node');
assert(html.indexOf('Child A') !== -1, 'tree: shows child A');
assert(html.indexOf('Child B') !== -1, 'tree: shows child B');
assert(html.indexOf('🤖 自动') !== -1, 'tree: auto badge on root');
assert(html.indexOf('✏️ 手动') !== -1, 'tree: manual badge on child');

// ---------------------------------------------------------------------------
// 4. expand/collapse toggle
// ---------------------------------------------------------------------------

resetAll();
_nodes = [
    { id: 'dg1', name: 'Parent', parentId: null, baseGroupId: 'bg1', isAutoGenerated: false },
    { id: 'dg2', name: 'Child', parentId: 'dg1', baseGroupId: 'bg1', isAutoGenerated: false },
];
_baseGroups = [{ id: 'bg1', name: 'Base 1' }];
container = _makeEl('derived-tree');
panel.render();
// First render: should show both (not collapsed)
assert(container._html.indexOf('Child') !== -1, 'expand: initially expanded');
assert(container._html.indexOf('▼') !== -1, 'expand: shows ▼ toggle');

// Find toggle element and click it
var toggles = container.querySelectorAll('.derived-toggle');
var clicked = false;
for (var t = 0; t < toggles.length; t++) {
    var tg = toggles[t];
    if (tg.getAttribute('data-dg-id') === 'dg1') {
        // Simulate toggle click
        tg._listeners.click[0]({ stopPropagation: function() {} });
        clicked = true;
        break;
    }
}
assert(clicked, 'toggle: found toggle for dg1');

// After toggle, Child should not appear (collapsed)
var html2 = container._html;
assert(html2.indexOf('Child') === -1, 'collapse: Child hidden after toggle');
assert(html2.indexOf('▶') !== -1, 'collapse: shows ▶ toggle');

// Click again to expand
toggles = container.querySelectorAll('.derived-toggle');
for (var u = 0; u < toggles.length; u++) {
    var tg2 = toggles[u];
    if (tg2.getAttribute('data-dg-id') === 'dg1') {
        tg2._listeners.click[0]({ stopPropagation: function() {} });
        break;
    }
}
assert(container._html.indexOf('Child') !== -1, 're-expand: Child visible again');

// ---------------------------------------------------------------------------
// 5. node selection — clicking a row
// ---------------------------------------------------------------------------

resetAll();
_nodes = [
    { id: 'dg1', name: 'Node 1', parentId: null, baseGroupId: 'bg1', isAutoGenerated: false },
];
_baseGroups = [{ id: 'bg1', name: 'Base 1' }];
container = _makeEl('derived-tree');
panel.render();

var rows = container.querySelectorAll('.derived-tree-node');
var rowClicked = false;
for (var r = 0; r < rows.length; r++) {
    if (rows[r].getAttribute('data-dg-id') === 'dg1') {
        rows[r]._listeners.click[0]({ target: { tagName: 'TD' } });
        rowClicked = true;
        break;
    }
}
assert(rowClicked, 'select: row clicked');
assert(global._mockActiveDerivedId === 'dg1', 'select: activeId set to dg1');

// ---------------------------------------------------------------------------
// 6. add child via button
// ---------------------------------------------------------------------------

resetAll();
_nodes = [
    { id: 'dg1', name: 'Root', parentId: null, baseGroupId: 'bg1', isAutoGenerated: false },
];
_baseGroups = [{ id: 'bg1', name: 'Base 1' }];
container = _makeEl('derived-tree');
panel.render();

// Click add-child on dg1
var addBtns = container.querySelectorAll('.derived-add-child-btn');
var btnClicked = false;
for (var a = 0; a < addBtns.length; a++) {
    if (addBtns[a].getAttribute('data-dg-id') === 'dg1') {
        addBtns[a]._listeners.click[0]({ stopPropagation: function() {} });
        btnClicked = true;
        break;
    }
}
assert(btnClicked, 'add child: button clicked');
// Should have opened form — check for form DOM
assert(_domElements['dnf_name'] !== undefined, 'add child: form opened (dnf_name exists)');
assert(_bodyHTML.indexOf('新增派生组') !== -1, 'add child: form title correct');

// ---------------------------------------------------------------------------
// 7. edit — opens form with pre-filled data
// ---------------------------------------------------------------------------

resetAll();
_nodes = [
    { id: 'dg1', name: 'Edit Me', parentId: null, baseGroupId: 'bg1', isAutoGenerated: false },
];
_baseGroups = [{ id: 'bg1', name: 'Base 1' }];
container = _makeEl('derived-tree');
panel.render();

var editBtns = container.querySelectorAll('.derived-edit-btn');
var editClicked = false;
for (var e = 0; e < editBtns.length; e++) {
    if (editBtns[e].getAttribute('data-dg-id') === 'dg1') {
        editBtns[e]._listeners.click[0]({ stopPropagation: function() {} });
        editClicked = true;
        break;
    }
}
assert(editClicked, 'edit: button clicked');
assert(_domElements['dnf_name'] && _domElements['dnf_name']._value === 'Edit Me', 'edit: form pre-filled with name');
assert(_bodyHTML.indexOf('编辑派生组') !== -1, 'edit: form title correct');

// ---------------------------------------------------------------------------
// 8. edit save
// ---------------------------------------------------------------------------

resetAll();
_nodes = [
    { id: 'dg1', name: 'Original', parentId: null, baseGroupId: 'bg1', isAutoGenerated: false },
];
_baseGroups = [{ id: 'bg1', name: 'Base 1' }];
container = _makeEl('derived-tree');
panel.render();

// Open edit form
var editBtns2 = container.querySelectorAll('.derived-edit-btn');
for (var e2 = 0; e2 < editBtns2.length; e2++) {
    if (editBtns2[e2].getAttribute('data-dg-id') === 'dg1') {
        editBtns2[e2]._listeners.click[0]({ stopPropagation: function() {} });
        break;
    }
}
// Change name and save
_domElements['dnf_name']._value = 'Renamed';
// Trigger save button
var saveBtn = _domElements['dnf_save'];
assert(saveBtn !== undefined, 'edit save: save button exists');
saveBtn._listeners.click[0]();

assert(_nodes[0].name === 'Renamed', 'edit save: name changed to Renamed');

// ---------------------------------------------------------------------------
// 9. add root node — opens form with no parent
// ---------------------------------------------------------------------------

resetAll();
_nodes = [
    { id: 'dg1', name: 'Existing', parentId: null, baseGroupId: 'bg1', isAutoGenerated: false },
];
_baseGroups = [{ id: 'bg1', name: 'Base 1' }];
container = _makeEl('derived-tree');
panel.render();

var addRootBtn = container.querySelector('#derived-add-root-btn');
assert(addRootBtn !== null, 'add root: button exists');
addRootBtn._listeners.click[0]();

assert(_domElements['dnf_name'] !== undefined, 'add root: form opened');
assert(_bodyHTML.indexOf('新增派生组') !== -1, 'add root: form title correct');
// Should have baseGroupId selector for new nodes
assert(_domElements['dnf_baseGroupId'] !== undefined, 'add root: baseGroupId selector exists');

// ---------------------------------------------------------------------------
// 10. save new root node
// ---------------------------------------------------------------------------

resetAll();
_nodes = [];
_baseGroups = [{ id: 'bg1', name: 'Base 1' }];
container = _makeEl('derived-tree');
panel.render();

var addRootBtn2 = container.querySelector('#derived-add-root-btn');
addRootBtn2._listeners.click[0]();

_domElements['dnf_name']._value = 'New Root';
_domElements['dnf_baseGroupId']._options = ['bg1'];
_domElements['dnf_baseGroupId']._value = 'bg1';

_domElements['dnf_save']._listeners.click[0]();

assert(_nodes.length === 1, 'add root save: 1 node created');
assert(_nodes[0].name === 'New Root', 'add root save: name correct');
assert(_nodes[0].parentId === null, 'add root save: parentId is null');
assert(_nodes[0].baseGroupId === 'bg1', 'add root save: baseGroupId correct');

// ---------------------------------------------------------------------------
// 11. delete — auto-generated (cascade)
// ---------------------------------------------------------------------------

resetAll();
global.confirm = function() { return true; };
_nodes = [
    { id: 'dg1', name: 'Auto', parentId: null, baseGroupId: 'bg1', isAutoGenerated: true },
    { id: 'dg2', name: 'Child A', parentId: 'dg1', baseGroupId: 'bg1', isAutoGenerated: false },
    { id: 'dg3', name: 'Child B', parentId: 'dg1', baseGroupId: 'bg1', isAutoGenerated: false },
];
_baseGroups = [{ id: 'bg1', name: 'Base 1' }];
container = _makeEl('derived-tree');
panel.render();

assert(_nodes.length === 3, 'delete: pre-condition 3 nodes');

var delBtns = container.querySelectorAll('.derived-del-btn');
for (var d = 0; d < delBtns.length; d++) {
    if (delBtns[d].getAttribute('data-dg-id') === 'dg1') {
        delBtns[d]._listeners.click[0]({ stopPropagation: function() {} });
        break;
    }
}
assert(_nodes.length === 0, 'delete auto: cascade removed all 3 nodes');

// ---------------------------------------------------------------------------
// 12. delete — confirm=no (does nothing)
// ---------------------------------------------------------------------------

resetAll();
global.confirm = function() { return false; };
_nodes = [
    { id: 'dg1', name: 'Keep', parentId: null, baseGroupId: 'bg1', isAutoGenerated: false },
];
_baseGroups = [{ id: 'bg1', name: 'Base 1' }];
container = _makeEl('derived-tree');
panel.render();

var delBtns2 = container.querySelectorAll('.derived-del-btn');
for (var d2 = 0; d2 < delBtns2.length; d2++) {
    if (delBtns2[d2].getAttribute('data-dg-id') === 'dg1') {
        delBtns2[d2]._listeners.click[0]({ stopPropagation: function() {} });
        break;
    }
}
assert(_nodes.length === 1, 'delete cancel: node not removed');
assert(_nodes[0].id === 'dg1', 'delete cancel: dg1 still exists');

// ---------------------------------------------------------------------------
// 13. close form
// ---------------------------------------------------------------------------

resetAll();
_nodes = [{ id: 'dg1', name: 'X', parentId: null, baseGroupId: 'bg1', isAutoGenerated: false }];
_baseGroups = [{ id: 'bg1', name: 'Base 1' }];
container = _makeEl('derived-tree');
panel.render();

// Open form
var editBtns3 = container.querySelectorAll('.derived-edit-btn');
for (var e3 = 0; e3 < editBtns3.length; e3++) {
    if (editBtns3[e3].getAttribute('data-dg-id') === 'dg1') {
        editBtns3[e3]._listeners.click[0]({ stopPropagation: function() {} });
        break;
    }
}
assert(_domElements['dnf_name'] !== undefined, 'close form: form open');

// Click cancel
_domElements['dnf_cancel']._listeners.click[0]();
assert(_domElements['dnf_name'] === undefined, 'close form: form removed');

// ---------------------------------------------------------------------------
// 14. mount/unmount lifecycle
// ---------------------------------------------------------------------------

resetAll();
_nodes = [{ id: 'dg1', name: 'Test', parentId: null, baseGroupId: 'bg1', isAutoGenerated: false }];
_baseGroups = [{ id: 'bg1', name: 'Base 1' }];
_makeEl('derived-tree');

panel.mount();
assert(_listeners['derivedGraphChanged'] && _listeners['derivedGraphChanged'].length === 1, 'mount: derivedGraphChanged listener registered');
assert(_listeners['activeDerivedNodeChanged'] && _listeners['activeDerivedNodeChanged'].length === 1, 'mount: activeDerivedNodeChanged listener registered');
assert(_domElements['derived-tree']._html.indexOf('Test') !== -1, 'mount: rendered');

panel.unmount();
assert(_listeners['derivedGraphChanged'].length === 0, 'unmount: derivedGraphChanged listener removed');
assert(_listeners['activeDerivedNodeChanged'].length === 0, 'unmount: activeDerivedNodeChanged listener removed');

// ---------------------------------------------------------------------------
// 15. deep tree (3 levels)
// ---------------------------------------------------------------------------

resetAll();
_nodes = [
    { id: 'r1', name: 'L0', parentId: null, baseGroupId: 'bg1', isAutoGenerated: false },
    { id: 'r2', name: 'L1-A', parentId: 'r1', baseGroupId: 'bg1', isAutoGenerated: false },
    { id: 'r3', name: 'L1-B', parentId: 'r1', baseGroupId: 'bg1', isAutoGenerated: false },
    { id: 'r4', name: 'L2', parentId: 'r2', baseGroupId: 'bg1', isAutoGenerated: false },
];
_baseGroups = [{ id: 'bg1', name: 'Base 1' }];
container = _makeEl('derived-tree');
panel.render();

var html3 = container._html;
assert(html3.indexOf('L0') !== -1, 'deep: L0 visible');
assert(html3.indexOf('L1-A') !== -1, 'deep: L1-A visible');
assert(html3.indexOf('L1-B') !== -1, 'deep: L1-B visible');
assert(html3.indexOf('L2') !== -1, 'deep: L2 visible');
// L2 should have 48px indent (level 2 * 24)
assert(html3.indexOf('width:48px') !== -1, 'deep: L2 has correct indent');

// ---------------------------------------------------------------------------
// 16. registrations count shown in badge
// ---------------------------------------------------------------------------

resetAll();
GT.state._registrations = {
    'group_1': [
        { derivedGroupId: 'dg1' },
        { derivedGroupId: 'dg1' },
        { derivedGroupId: 'dg2' },
    ],
};
_nodes = [
    { id: 'dg1', name: 'HasRegs', parentId: null, baseGroupId: 'bg1', isAutoGenerated: false },
    { id: 'dg2', name: 'OneReg', parentId: null, baseGroupId: 'bg1', isAutoGenerated: false },
];
_baseGroups = [{ id: 'bg1', name: 'Base 1' }];
container = _makeEl('derived-tree');
panel.render();

assert(container._html.indexOf('已登记x2') !== -1, 'badge: shows 2 registrations for dg1');
assert(container._html.indexOf('已登记x1') !== -1, 'badge: shows 1 registration for dg2');

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------

console.log('\n=== Results ===');
console.log('Passed: ' + passed);
console.log('Failed: ' + failed);
if (failed > 0) process.exit(1);
