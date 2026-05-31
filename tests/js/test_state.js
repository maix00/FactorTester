/**
 * test_state.js — Node.js tests for state.js (emit/on + selection + lookup)
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
// Mock datamodel (state depends on datamodel for lookup)
// ---------------------------------------------------------------------------

global.window = {
    GroupTest: {
        datamodel: {
            groups: {
                _items: {},
                get: function(id) { return this._items[id] || null; },
            },
            ls_configs: {
                _items: {},
                get: function(id) { return this._items[id] || null; },
            },
        },
        log: function() {},
    }
};

// Load state.js (will overwrite GT.state)
require('../../static/js/modules/single_factor_test/group_test/state.js');

var GT = window.GroupTest;

// ---------------------------------------------------------------------------
// 1. Legacy API preserved
// ---------------------------------------------------------------------------

GT.state._resetAll();
GT.state.setActiveSubmission('sub1');
assertEquals(GT.state.active.submissionId, 'sub1', 'legacy: setActiveSubmission');

GT.state.setActiveFactor('sub1', 'factor_a');
assertEquals(GT.state.getActiveFactor('sub1'), 'factor_a', 'legacy: getActiveFactor');

GT.state.cacheResult('sub1', 'factor_a', { data: 42 });
assertEquals(GT.state.getCachedResult('sub1', 'factor_a'), { data: 42 }, 'legacy: getCachedResult');

// ---------------------------------------------------------------------------
// 2. emit / on
// ---------------------------------------------------------------------------

GT.state._resetAll();

var emitted = [];
GT.state.on('foo', function(d) { emitted.push({ event: 'foo', data: d }); });
GT.state.emit('foo', { val: 1 });
GT.state.emit('foo', { val: 2 });
assert(emitted.length === 2, 'emit/on: received both events');
assertEquals(emitted[0], { event: 'foo', data: { val: 1 } }, 'emit/on: first event correct');

// Emit with no listeners — no crash
GT.state.emit('no_listeners', {});

// Multiple listeners
var count = 0;
GT.state.on('multi', function() { count++; });
GT.state.on('multi', function() { count++; });
GT.state.emit('multi');
assert(count === 2, 'emit/on: multiple listeners called');

// ---------------------------------------------------------------------------
// 3. off
// ---------------------------------------------------------------------------

GT.state._resetAll();

var cb1Called = 0, cb2Called = 0;
function cb1() { cb1Called++; }
function cb2() { cb2Called++; }

GT.state.on('test_off', cb1);
GT.state.on('test_off', cb2);
GT.state.emit('test_off');
assert(cb1Called === 1 && cb2Called === 1, 'off: both called before off');

// Remove cb1
GT.state.off('test_off', cb1);
GT.state.emit('test_off');
assert(cb1Called === 1, 'off: cb1 not called after off');
assert(cb2Called === 2, 'off: cb2 still called');

// Remove all
GT.state.off('test_off');
GT.state.emit('test_off');
assert(cb2Called === 2, 'off: cb2 not called after full off');

// ---------------------------------------------------------------------------
// 4. Selection
// ---------------------------------------------------------------------------

GT.state._resetAll();

assertEquals(GT.state.getActiveMainTab(), 'base', 'selection: default mainTab');
assertEquals(GT.state.getActiveBaseGroupId(), null, 'selection: default baseGroup');

var tabChangeData = null;
GT.state.on('mainTabChanged', function(d) { tabChangeData = d; });
GT.state.setActiveMainTab('derived');
assertEquals(GT.state.getActiveMainTab(), 'derived', 'selection: mainTab changed');
assertEquals(tabChangeData, { tab: 'derived' }, 'selection: mainTab emit');

GT.state.setActiveBaseGroupId('bg_123');
assertEquals(GT.state.getActiveBaseGroupId(), 'bg_123', 'selection: baseGroupId set');

GT.state.setActiveDerivedNodeId('dg_456');
assertEquals(GT.state.getActiveDerivedNodeId(), 'dg_456', 'selection: derivedNodeId set');

GT.state.setActiveLsConfigId('ls_789');
assertEquals(GT.state.getActiveLsConfigId(), 'ls_789', 'selection: lsConfigId set');

// ---------------------------------------------------------------------------
// 5. Lookup
// ---------------------------------------------------------------------------

GT.state._resetAll();

// Seed datamodel
GT.datamodel.groups._items['bg_x'] = { id: 'bg_x', name: 'base_1' };
GT.datamodel.groups._items['dg_y'] = { id: 'dg_y', name: 'derived_1' };
GT.datamodel.ls_configs._items['ls_z'] = { id: 'ls_z', name: 'ls_1' };

assertEquals(GT.state.getBaseGroup('bg_x'), { id: 'bg_x', name: 'base_1' }, 'lookup: getBaseGroup found');
assertEquals(GT.state.getBaseGroup('nonexistent'), null, 'lookup: getBaseGroup not found');
assertEquals(GT.state.getDerivedNode('dg_y'), { id: 'dg_y', name: 'derived_1' }, 'lookup: getDerivedNode found');
assertEquals(GT.state.getLsConfig('ls_z'), { id: 'ls_z', name: 'ls_1' }, 'lookup: getLsConfig found');

// ---------------------------------------------------------------------------
// 6. Listener error isolation
// ---------------------------------------------------------------------------

GT.state._resetAll();
var safeCount = 0;
GT.state.on('error_test', function() { throw new Error('boom'); });
GT.state.on('error_test', function() { safeCount++; });
GT.state.emit('error_test');
assert(safeCount === 1, 'error isolation: second listener still called');

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------

console.log('\n=== Results ===');
console.log('Passed: ' + passed);
console.log('Failed: ' + failed);
if (failed > 0) process.exit(1);
