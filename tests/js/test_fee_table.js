/**
 * test_fee_table.js — Node.js tests for fee_table.js
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

function assertThrows(fn, msg) {
    try { fn(); console.log('FAIL: ' + msg + ' (no throw)'); failed++; }
    catch (_) { passed++; }
}

// ---------------------------------------------------------------------------
// Mock
// ---------------------------------------------------------------------------

global.window = {
    GroupTest: {
        datamodel: {},
        _events: [],
        state: { emit: function(e, d) { window.GroupTest._events.push({ event: e, data: d }); } },
        log: function() {}
    }
};

require('../../static/js/modules/single_factor_test/group_test/datamodel/fee_table.js');

var ft = window.GroupTest.datamodel.fee_table;

function reset() { ft._reset(); window.GroupTest._events = []; }

// ---------------------------------------------------------------------------
// 1. setTable + getTable
// ---------------------------------------------------------------------------

reset();
ft.setTable({ 'product/A': 0.001, 'product/B': 0.002 });
assertEquals(ft.getTable(), { 'product/A': 0.001, 'product/B': 0.002 }, 'setTable/getTable: round-trip');

// Empty table
ft.setTable({});
assertEquals(ft.getTable(), {}, 'setTable: empty');

// null → empty
ft.setTable(null);
assertEquals(ft.getTable(), {}, 'setTable: null → empty');

// Filters negative rates
ft.setTable({ 'product/A': 0.001, 'product/B': -1, 'product/C': 0.003 });
assertEquals(ft.getTable(), { 'product/A': 0.001, 'product/C': 0.003 }, 'setTable: filters negative rates');

// ---------------------------------------------------------------------------
// 2. updateFee + getFee
// ---------------------------------------------------------------------------

reset();
ft.setTable({ 'product/A': 0.001 });
ft.updateFee('product/A', 0.005);
assertEquals(ft.getFee('product/A'), 0.005, 'updateFee: updates existing');

ft.updateFee('product/B', 0.003);
assertEquals(ft.getFee('product/B'), 0.003, 'updateFee: adds new product');

// Invalid
assertThrows(function() { ft.updateFee('', 0.001); }, 'updateFee: throws on empty path');
assertThrows(function() { ft.updateFee('product/X', -0.1); }, 'updateFee: throws on negative rate');

// Undefined product
assertEquals(ft.getFee('nonexistent'), undefined, 'getFee: undefined for unknown');

// Event
var evt = window.GroupTest._events[window.GroupTest._events.length - 1];
assertEquals(evt.event, 'feeTableChanged', 'updateFee: emits event');

// ---------------------------------------------------------------------------
// 3. removeProduct
// ---------------------------------------------------------------------------

reset();
ft.setTable({ 'product/A': 0.001, 'product/B': 0.002 });
ft.removeProduct('product/A');
assertEquals(ft.getTable(), { 'product/B': 0.002 }, 'removeProduct: removes existing');
assertEquals(ft.getFee('product/A'), undefined, 'removeProduct: getFee returns undefined');

// ---------------------------------------------------------------------------
// 4. getProductPaths
// ---------------------------------------------------------------------------

reset();
ft.setTable({ 'a': 0.1, 'b': 0.2 });
assertEquals(ft.getProductPaths().sort(), ['a', 'b'], 'getProductPaths: returns keys');

// ---------------------------------------------------------------------------
// 5. getModifications
// ---------------------------------------------------------------------------

reset();
ft.setTable({ 'p1': 0.001, 'p2': 0.002, 'p3': 0.003 });

// Modify, add, remove
ft.updateFee('p1', 0.005);       // modified
ft.updateFee('p4', 0.004);       // added
ft.removeProduct('p3');          // removed

var mods = ft.getModifications();
assertEquals(mods.modified, { 'p1': { old: 0.001, new: 0.005 } }, 'getModifications: modified');
assertEquals(mods.added, { 'p4': 0.004 }, 'getModifications: added');
assertEquals(mods.removed, { 'p3': 0.003 }, 'getModifications: removed');

// No modifications after reset
ft._reset();
ft.setTable({ 'p1': 0.001 });
var mods2 = ft.getModifications();
assertEquals(mods2, { modified: {}, added: {}, removed: {} }, 'getModifications: empty after fresh set');

// ---------------------------------------------------------------------------
// 6. hasModifications
// ---------------------------------------------------------------------------

reset();
ft.setTable({ 'p1': 0.001 });
assert(!ft.hasModifications(), 'hasModifications: false when clean');
ft.updateFee('p1', 0.005);
assert(ft.hasModifications(), 'hasModifications: true after change');

// ---------------------------------------------------------------------------
// 7. resetToOriginal
// ---------------------------------------------------------------------------

reset();
ft.setTable({ 'p1': 0.001, 'p2': 0.002 });
ft.updateFee('p1', 0.005);
ft.updateFee('p3', 0.003);

var count = ft.resetToOriginal();
assertEquals(count, 2, 'resetToOriginal: reverted 2 changes');
assertEquals(ft.getTable(), { 'p1': 0.001, 'p2': 0.002 }, 'resetToOriginal: restored original');

// Reset with no original → empty
ft._reset();
assertEquals(ft.resetToOriginal(), 0, 'resetToOriginal: 0 if no original');

// ---------------------------------------------------------------------------
// 8. Event emission
// ---------------------------------------------------------------------------

reset();
ft.setTable({ 'p1': 0.001 });
var evts = window.GroupTest._events;
assert(evts.some(function(e) { return e.event === 'feeTableChanged' && e.data.action === 'setTable'; }), 'event: setTable');
ft.updateFee('p1', 0.005);
assert(evts.some(function(e) { return e.event === 'feeTableChanged' && e.data.action === 'updateFee'; }), 'event: updateFee');
ft.removeProduct('p1');
assert(evts.some(function(e) { return e.event === 'feeTableChanged' && e.data.action === 'removeProduct'; }), 'event: removeProduct');

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------

console.log('\n=== Results ===');
console.log('Passed: ' + passed);
console.log('Failed: ' + failed);
if (failed > 0) process.exit(1);
