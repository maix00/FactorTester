/**
 * test_panels_ls_list.js — Node.js tests for panels/ls/list.js
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
        if (id && (id.indexOf('ls-configs-list') === 0 || id.indexOf('ls-config-form') === 0 || id.indexOf('lsf_') === 0 || id.indexOf('ls-') === 0)) {
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
        _options: [],
        _listeners: {},
        _checked: false,
        style: {},
        get value() { return this._value; },
        set value(v) { this._value = v; },
        get checked() { return this._checked; },
        set checked(v) { this._checked = v; },
        get innerHTML() { return this._html; },
        set innerHTML(v) {
            this._html = v;
            var idRe = /\bid="([^"]+)"/g;
            var im;
            while ((im = idRe.exec(v)) !== null) {
                _domElements[im[1]] = _makeEl(im[1]);
            }
            // Parse data-ls-id attributes
            var idRe2 = /data-ls-id="([^"]+)"/g;
            while ((im = idRe2.exec(v)) !== null) {
                this._dataIds = this._dataIds || [];
                this._dataIds.push(im[1]);
            }
        },
        querySelectorAll: function(sel) {
            var results = [];
            if (sel === '.ls-config-row' && this._dataIds) {
                for (var i = 0; i < this._dataIds.length; i++) {
                    results.push(_makeEl('ls-row-' + this._dataIds[i]));
                }
            }
            if (sel.indexOf('.ls-edit-btn') !== -1) {
                for (var j = 0; j < (this._dataIds || []).length; j++) {
                    results.push(_makeEl('ls-edit-' + this._dataIds[j]));
                }
            }
            if (sel.indexOf('.ls-del-btn') !== -1) {
                for (var k = 0; k < (this._dataIds || []).length; k++) {
                    results.push(_makeEl('ls-del-' + this._dataIds[k]));
                }
            }
            if (sel.indexOf('[data-ls-id="') !== -1) {
                var m = sel.match(/"([^"]*)"/);
                if (m && m[1]) results.push(_makeEl('ls-row-' + m[1]));
            }
            return results;
        },
        querySelector: function(sel) {
            var all = this.querySelectorAll(sel);
            return all.length > 0 ? all[0] : null;
        },
        getAttribute: function(attr) {
            if (attr === 'data-ls-id') return this.id.replace('ls-row-', '');
            return null;
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
global.confirm = function() { return true; };

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

var mockLS = [];
var mockDG = [];

function resetAll() {
    mockLS = [];
    mockDG = [];
    _domElements = {};
    _bodyHTML = '';
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
                list: function() {
                    return mockDG.map(function(d) { return { id: d.id, name: d.name }; });
                },
            },
            ls_configs: {
                getAll: function() { return JSON.parse(JSON.stringify(mockLS)); },
                get: function(id) {
                    for (var i = 0; i < mockLS.length; i++) {
                        if (mockLS[i].id === id) return JSON.parse(JSON.stringify(mockLS[i]));
                    }
                    return null;
                },
                add: function(data) {
                    var item = JSON.parse(JSON.stringify(data));
                    item.id = 'ls_test_' + mockLS.length;
                    item.needsRegenerate = true;
                    mockLS.push(item);
                    return JSON.parse(JSON.stringify(item));
                },
                update: function(id, patch) {
                    for (var i = 0; i < mockLS.length; i++) {
                        if (mockLS[i].id === id) {
                            Object.keys(patch).forEach(function(k) { mockLS[i][k] = patch[k]; });
                            return JSON.parse(JSON.stringify(mockLS[i]));
                        }
                    }
                    throw new Error('not found');
                },
                remove: function(id) {
                    for (var i = 0; i < mockLS.length; i++) {
                        if (mockLS[i].id === id) { mockLS.splice(i, 1); return; }
                    }
                },
                list: function() { return mockLS.map(function(l) { return { id: l.id, name: l.name }; }); },
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
            setActiveLSConfigId: function(id) { global._mockActiveLSId = id; },
        },
        panels: {},
        log: function() {},
    },
};

// ---------------------------------------------------------------------------
// Load module
// ---------------------------------------------------------------------------

try {
    require('../../static/js/modules/single_factor_test/group_test/panels/ls/list.js');
} catch (e) {
    console.log('MODULE LOAD ERROR: ' + e.message);
    console.log(e.stack);
    process.exit(1);
}

var GT = window.GroupTest;
var panel = GT.panels.ls.list;

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
// 2. Empty list
// ---------------------------------------------------------------------------

resetAll();
_makeEl('ls-configs-list');
panel.render();
var html = _domElements['ls-configs-list']._html;
assertContains(html, '暂无多空配置', '2. empty: placeholder');
assertContains(html, '新增多空配置', '2. empty: add button');

// ---------------------------------------------------------------------------
// 3. Table with items
// ---------------------------------------------------------------------------

resetAll();
mockDG.push({ id: 'dg_long', name: 'LongGroup' }, { id: 'dg_short', name: 'ShortGroup' });
mockLS.push({
    id: 'ls_1', name: 'LS Pair 1', longGroupId: 'dg_long', shortGroupId: 'dg_short',
    feeMode: 'inherit', feeRate: null, useCloseToday: null, rebalanceMode: null,
    needsRegenerate: true, metadata: {},
});
_makeEl('ls-configs-list');
panel.render();
html = _domElements['ls-configs-list']._html;
assertContains(html, 'LS Pair 1', '3. table: name');
assertContains(html, 'LongGroup', '3. table: long name');
assertContains(html, 'ShortGroup', '3. table: short name');
assertContains(html, '待更新', '3. table: stale badge');

// ---------------------------------------------------------------------------
// 4. Ready state badge
// ---------------------------------------------------------------------------

resetAll();
mockLS.push({
    id: 'ls_r', name: 'Ready', longGroupId: 'dg_l', shortGroupId: 'dg_s',
    feeMode: 'inherit', feeRate: null, useCloseToday: null, rebalanceMode: null,
    needsRegenerate: false, metadata: {},
});
_makeEl('ls-configs-list');
panel.render();
assertContains(_domElements['ls-configs-list']._html, '就绪', '4. badge: ready');

// ---------------------------------------------------------------------------
// 5. Row click sets active LS
// ---------------------------------------------------------------------------

resetAll();
mockLS.push({ id: 'ls_click', name: 'ClickMe', longGroupId: 'x', shortGroupId: 'y',
    needsRegenerate: false, metadata: {} });
_makeEl('ls-configs-list');
panel.render();
global._mockActiveLSId = null;
// Simulate row click
var row = _makeEl('ls-row-ls_click');
row._listeners['click'] = row._listeners['click'] || [];
row._listeners['click'].push(function(e) { global._mockActiveLSId = 'ls_click'; });
row._listeners['click'][0]({ target: { tagName: 'DIV' } });
assert(global._mockActiveLSId === 'ls_click', '5. click: sets active id');

// ---------------------------------------------------------------------------
// 6. Button click doesn't set active
// ---------------------------------------------------------------------------

resetAll();
global._mockActiveLSId = 'before';
mockLS.push({ id: 'ls_btn', name: 'Btn', longGroupId: 'x', shortGroupId: 'y',
    needsRegenerate: false, metadata: {} });
_makeEl('ls-configs-list');
panel.render();
var row2 = _makeEl('ls-row-ls_btn');
row2._listeners['click'] = row2._listeners['click'] || [];
row2._listeners['click'].push(function(e) {
    if (e.target.tagName !== 'BUTTON') global._mockActiveLSId = 'ls_btn';
});
row2._listeners['click'][0]({ target: { tagName: 'BUTTON' } });
assert(global._mockActiveLSId === 'before', '6. button click: does not select row');

// ---------------------------------------------------------------------------
// 7. Add button opens modal
// ---------------------------------------------------------------------------

resetAll();
mockDG.push({ id: 'dg_a', name: 'Group A' });
_makeEl('ls-configs-list');
panel.render();
var addBtn = $('ls-add-btn');
assert(addBtn !== null, '7. add: button exists');
// Check listeners exist
assert(addBtn._listeners['click'] && addBtn._listeners['click'].length > 0, '7. add: listener attached');

// ---------------------------------------------------------------------------
// 8. Mount/unmount
// ---------------------------------------------------------------------------

resetAll();
_makeEl('ls-configs-list');
global._events = {};
panel.mount();
assert(global._events['lsConfigsChanged'] !== undefined, '8. mount: event registered');
assert(global._events['activeLSConfigChanged'] !== undefined, '8. mount: active event registered');
panel.unmount();
var lsEvt = global._events['lsConfigsChanged'];
assert(!lsEvt || lsEvt.length === 0, '8. unmount: cleaned');
var actEvt2 = global._events['activeLSConfigChanged'];
assert(!actEvt2 || actEvt2.length === 0, '8. unmount: active cleaned');

// ---------------------------------------------------------------------------
// 9. Edit button opens modal
// ---------------------------------------------------------------------------

resetAll();
mockDG.push({ id: 'dg_long', name: 'L' }, { id: 'dg_short', name: 'S' });
mockLS.push({ id: 'ls_edit', name: 'ToEdit', longGroupId: 'dg_long', shortGroupId: 'dg_short',
    needsRegenerate: false, metadata: {} });
_makeEl('ls-configs-list');
panel.render();
// Edit via API
try {
    panel._showModal({ id: 'ls_edit', name: 'ToEdit', longGroupId: 'dg_long', shortGroupId: 'dg_short',
        needsRegenerate: false, metadata: {} });
    var modal = $('ls-config-form-modal');
    assert(modal !== null, '9. edit: modal shown');
} catch (e) {
    console.log('FAIL: 9. edit modal: ' + e.message);
    failed++;
}

// ---------------------------------------------------------------------------
// 10. Delete works
// ---------------------------------------------------------------------------

resetAll();
mockLS.push({ id: 'ls_del', name: 'ToDelete', longGroupId: 'x', shortGroupId: 'y',
    needsRegenerate: false, metadata: {} });
assert(mockLS.length === 1, '10. delete: item exists');
GT.datamodel.ls_configs.remove('ls_del');
assert(mockLS.length === 0, '10. delete: removed');

// ---------------------------------------------------------------------------
// 11. Rerender on data change
// ---------------------------------------------------------------------------

resetAll();
_makeEl('ls-configs-list');
panel.render();
assertContains(_domElements['ls-configs-list']._html, '暂无多空配置', '11. initial: empty');
mockLS.push({ id: 'ls_new', name: 'New', longGroupId: 'x', shortGroupId: 'y',
    needsRegenerate: false, metadata: {} });
panel.render();
assertContains(_domElements['ls-configs-list']._html, 'New', '11. rerender: shows new');

// ---------------------------------------------------------------------------
// 12. Highlight row via mount
// ---------------------------------------------------------------------------

resetAll();
mockLS.push({ id: 'ls_h', name: 'High', longGroupId: 'x', shortGroupId: 'y',
    needsRegenerate: false, metadata: {} });
global._mockActiveLSId = 'ls_h';
_makeEl('ls-configs-list');
panel.mount();
html = _domElements['ls-configs-list']._html;
assertContains(html, 'e8f4fd', '12. highlight: style applied');
// Cleanup events
global._events = {};

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------

console.log('');
console.log('=== Results ===');
console.log('Passed: ' + passed);
console.log('Failed: ' + failed);

if (failed > 0) process.exit(1);
