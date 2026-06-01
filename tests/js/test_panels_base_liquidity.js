/**
 * test_panels_base_liquidity.js — Node.js tests for panels/config/liquidity.js
 */

var assert = require('assert');

var _domElements = {};
var _events = {};
var _dirty = {};
var mockGroup = null;

function _makeEl(id) {
    var el = {
        id: id,
        _html: '',
        _listeners: {},
        _value: '',
        get innerHTML() { return this._html; },
        set innerHTML(v) { this._html = v; },
        get value() { return this._value; },
        set value(v) { this._value = v; },
        addEventListener: function(evt, fn) {
            if (!this._listeners[evt]) this._listeners[evt] = [];
            this._listeners[evt].push(fn);
        },
        _fire: function(evt) {
            var fns = (this._listeners[evt] || []).slice();
            for (var i = 0; i < fns.length; i++) fns[i]({});
        },
    };
    _domElements[id] = el;
    return el;
}

function reset() {
    _domElements = {};
    _events = {};
    _dirty = {};
    mockGroup = null;
}

global.document = {
    getElementById: function(id) {
        if (_domElements[id]) return _domElements[id];
        if (id === 'liquidity-mode-select' || id === 'liquidity-percent-input' || id === 'liquidity-percent-row') {
            return _makeEl(id);
        }
        return null;
    },
};

global.window = {
    GroupTest: {
        panels: {},
        log: function() {},
        state: {
            on: function(evt, fn) {
                if (!_events[evt]) _events[evt] = [];
                _events[evt].push(fn);
            },
            off: function(evt, fn) {
                var arr = _events[evt] || [];
                var idx = arr.indexOf(fn);
                if (idx >= 0) arr.splice(idx, 1);
            },
        },
    },
    GT_CONFIG_REGISTRY: {
        register: function(def, containerId) {
            this.def = def;
            this.containerId = containerId;
        },
        getReferenceGroup: function() { return mockGroup; },
        setDirty: function(key, value) { _dirty[key] = value; },
        getDirty: function(key, fallback) { return Object.prototype.hasOwnProperty.call(_dirty, key) ? _dirty[key] : fallback; },
        hasDirty: function() { return Object.keys(_dirty).length > 0; },
        rollbackDirty: function() { _dirty = {}; },
    },
};

require('../../static/js/modules/single_factor_test/group_test/panels/config/liquidity.js');

var panel = window.GroupTest.panels.config.liquidity;

reset();
_makeEl('config-liquidity');
panel.render();
assert.ok(_domElements['config-liquidity'].innerHTML.indexOf('请先选择一个分组') >= 0);

reset();
mockGroup = { id: 'g1', liquidityMode: 'infinite', liquidityPercent: 100 };
_makeEl('config-liquidity');
panel.render();
assert.ok(_domElements['config-liquidity'].innerHTML.indexOf('无限流动性') >= 0);
assert.ok(_domElements['config-liquidity'].innerHTML.indexOf('默认不使用成交量约束') >= 0);

reset();
mockGroup = { id: 'g2', liquidityMode: 'percent', liquidityPercent: 12.5 };
_makeEl('config-liquidity');
panel.render();
assert.ok(_domElements['config-liquidity'].innerHTML.indexOf('12.5%') >= 0);

var input = _domElements['liquidity-percent-input'];
input.value = '25';
input._fire('change');
assert.strictEqual(_dirty.liquidityPercent, 25);

var cols = panel.getTableColumns();
assert.strictEqual(cols[0].render({ liquidityMode: 'percent', liquidityPercent: 30 }), '30%成交量');
assert.strictEqual(cols[0].render({ liquidityMode: 'infinite' }), '无限');

var chips = panel.getChips({ liquidityMode: 'percent', liquidityPercent: 10 });
assert.ok(chips[0].html.indexOf('10%') >= 0);

console.log('PASS: liquidity panel');
