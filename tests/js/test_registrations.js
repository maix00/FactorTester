/**
 * test_registrations.js — Node.js tests for registrations.js
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

require('../../static/js/modules/single_factor_test/group_test/datamodel/registrations.js');

var reg = window.GroupTest.datamodel.registrations;

function reset() { reg._reset(); window.GroupTest._events = []; }

// ---------------------------------------------------------------------------
// 1. register
// ---------------------------------------------------------------------------

reset();
var r1 = reg.register('ls1', 'dg1', 'long');
assertEquals(r1, { groupId: 'dg1', side: 'long', weight: 1.0 }, 'register: default weight=1.0');

var r2 = reg.register('ls1', 'dg2', 'short', 0.5);
assertEquals(r2, { groupId: 'dg2', side: 'short', weight: 0.5 }, 'register: custom weight');

// Duplicate updates
var r1b = reg.register('ls1', 'dg1', 'long', 2.0);
assertEquals(r1b.weight, 2.0, 'register: duplicate updates weight');

// Throws on bad side
assertThrows(function() { reg.register('ls1', 'dg3', 'bad'); }, 'register: throws on invalid side');

// Throws on bad weight
assertThrows(function() { reg.register('ls1', 'dg3', 'long', 0); }, 'register: throws on weight <= 0');
assertThrows(function() { reg.register('ls1', 'dg3', 'long', -1); }, 'register: throws on negative weight');

// Event
var evt = window.GroupTest._events[window.GroupTest._events.length - 1];
assertEquals(evt.event, 'registrationsChanged', 'register: emits');

// ---------------------------------------------------------------------------
// 2. getRegistrations
// ---------------------------------------------------------------------------

var regs = reg.getRegistrations('ls1');
assert(regs.length === 2, 'getRegistrations: 2 entries for ls1');

// Deep copy
regs[0].weight = 999;
var regs2 = reg.getRegistrations('ls1');
assert(regs2[0].weight !== 999, 'getRegistrations: deep copy');

// Empty
assertEquals(reg.getRegistrations('nonexistent'), [], 'getRegistrations: empty for unknown');

// ---------------------------------------------------------------------------
// 3. getRegistrationsForGroup
// ---------------------------------------------------------------------------

reg.register('ls2', 'dg1', 'short', 0.7);
var refs = reg.getRegistrationsForGroup('dg1');
assert(refs.length === 2, 'getRegistrationsForGroup: dg1 referenced 2 times');
var sides = refs.map(function(r) { return r.side; }).sort();
assertEquals(sides, ['long', 'short'], 'getRegistrationsForGroup: correct sides');

var refs2 = reg.getRegistrationsForGroup('nonexistent');
assertEquals(refs2, [], 'getRegistrationsForGroup: empty for unreferenced');

// ---------------------------------------------------------------------------
// 4. unregister
// ---------------------------------------------------------------------------

reset();
reg.register('ls1', 'dg1', 'long');
reg.register('ls1', 'dg1', 'short');
reg.register('ls1', 'dg2', 'long');

// Unregister specific side
reg.unregister('ls1', 'dg1', 'long');
var regs3 = reg.getRegistrations('ls1');
assert(regs3.length === 2, 'unregister: 2 remaining after removing long side');
assert(regs3.every(function(r) { return !(r.groupId === 'dg1' && r.side === 'long'); }), 'unregister: dg1/long removed');

// Unregister all sides
reg.unregister('ls1', 'dg1');
var regs4 = reg.getRegistrations('ls1');
assert(regs4.length === 1, 'unregister: 1 remaining after removing all dg1 sides');

// Throws on nonexistent
assertThrows(function() { reg.unregister('ls1', 'nonexistent'); }, 'unregister: throws on nonexistent group');
assertThrows(function() { reg.unregister('nonexistent', 'dg1'); }, 'unregister: throws on nonexistent LS');

// ---------------------------------------------------------------------------
// 5. removeAllForLs
// ---------------------------------------------------------------------------

reset();
reg.register('ls1', 'dg1', 'long');
reg.register('ls1', 'dg2', 'short');
reg.register('ls2', 'dg3', 'long');

reg.removeAllForLs('ls1');
assertEquals(reg.getRegistrations('ls1'), [], 'removeAllForLs: ls1 cleared');
assert(reg.getRegistrations('ls2').length === 1, 'removeAllForLs: ls2 unaffected');

// ---------------------------------------------------------------------------
// 6. removeAllForGroup
// ---------------------------------------------------------------------------

reset();
reg.register('ls1', 'dg1', 'long');
reg.register('ls1', 'dg2', 'short');
reg.register('ls2', 'dg1', 'short');
reg.register('ls3', 'dg1', 'long');

var count = reg.removeAllForGroup('dg1');
assertEquals(count, 3, 'removeAllForGroup: removed 3 registrations');
assertEquals(reg.getRegistrationsForGroup('dg1'), [], 'removeAllForGroup: dg1 fully cleared');
assert(reg.getRegistrations('ls1').length === 1, 'removeAllForGroup: ls1 has dg2 remaining');

// Nonexistent → 0
assertEquals(reg.removeAllForGroup('nonexistent'), 0, 'removeAllForGroup: returns 0 for unknown');

// ---------------------------------------------------------------------------
// 7. getRegisteredLsIds
// ---------------------------------------------------------------------------

reset();
reg.register('ls_a', 'dg1', 'long');
reg.register('ls_b', 'dg2', 'short');

var ids = reg.getRegisteredLsIds().sort();
assertEquals(ids, ['ls_a', 'ls_b'], 'getRegisteredLsIds: returns all ls ids');

// ---------------------------------------------------------------------------
// 8. getAll
// ---------------------------------------------------------------------------

var all = reg.getAll();
assert(all.length === 2, 'getAll: 2 LS configs');

// ---------------------------------------------------------------------------
// 9. _reset
// ---------------------------------------------------------------------------

reg._reset();
assertEquals(reg.getRegisteredLsIds(), [], '_reset: clears all');

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------

console.log('\n=== Results ===');
console.log('Passed: ' + passed);
console.log('Failed: ' + failed);
if (failed > 0) process.exit(1);
