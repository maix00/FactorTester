/**
 * test_settings_snapshot.js — Node.js tests for settings_snapshot.js
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
// Mock (all datamodel modules)
// ---------------------------------------------------------------------------

global.window = {
    GroupTest: {
        datamodel: {},
        _events: [],
        state: { emit: function(e, d) { window.GroupTest._events.push({ event: e, data: d }); } },
        log: function() {}
    }
};

var GT = window.GroupTest;

// Load all datamodel modules
require('../../static/js/modules/single_factor_test/group_test/datamodel/base_groups.js');
require('../../static/js/modules/single_factor_test/group_test/datamodel/derived_graph.js');
require('../../static/js/modules/single_factor_test/group_test/datamodel/ls_configs.js');
require('../../static/js/modules/single_factor_test/group_test/datamodel/registrations.js');
require('../../static/js/modules/single_factor_test/group_test/datamodel/settings_snapshot.js');

var settings = GT.datamodel.settings;

function resetAll() {
    GT.datamodel.base_groups._reset();
    GT.datamodel.derived_graph._reset();
    GT.datamodel.ls_configs._reset();
    GT.datamodel.registrations._reset();
    GT._events = [];
}

// ---------------------------------------------------------------------------
// 1. emptySnapshot
// ---------------------------------------------------------------------------

resetAll();
var empty = settings.emptySnapshot();
assertEquals(Object.keys(empty).sort(), ['baseGroups', 'derivedGraph', 'lsConfigs', 'registrations'], 'emptySnapshot: correct keys');
assert(Array.isArray(empty.baseGroups), 'emptySnapshot: baseGroups is array');

// ---------------------------------------------------------------------------
// 2. snapshot (empty)
// ---------------------------------------------------------------------------

resetAll();
assertEquals(settings.snapshot(), { baseGroups: [], derivedGraph: [], lsConfigs: [], registrations: [] }, 'snapshot: empty state');

// ---------------------------------------------------------------------------
// 3. snapshot + apply round-trip
// ---------------------------------------------------------------------------

resetAll();

// Build state
GT.datamodel.base_groups.add({ name: 'base1', testerId: 't1', factorAlias: 'f1', groupCount: 3, dayPeriods: 5, feeMode: 'uniform', feeRate: 0.001 });
GT.datamodel.base_groups.add({ name: 'base2', testerId: 't2', factorAlias: 'f2', groupCount: 2, dayPeriods: 10, feeMode: 'per_product', feeRate: null, feeMap: {} });

GT.datamodel.derived_graph.add({ name: 'top', label: 'Top N', baseGroupId: GT.datamodel.base_groups.getAll()[0].id, autoMode: 'union' });
GT.datamodel.derived_graph.add({ name: 'bottom', label: 'Bottom M', baseGroupId: GT.datamodel.base_groups.getAll()[1].id, autoMode: 'intersect' });

var dgAll = GT.datamodel.derived_graph.getAll();
GT.datamodel.ls_configs.add({ name: 'ls1', longGroupId: dgAll[0].id, shortGroupId: dgAll[1].id, feeMode: 'inherit' });

GT.datamodel.registrations.register(GT.datamodel.ls_configs.getAll()[0].id, dgAll[0].id, 'long', 1.0);
GT.datamodel.registrations.register(GT.datamodel.ls_configs.getAll()[0].id, dgAll[1].id, 'short', 0.5);

// Snapshot
var snap = settings.snapshot();
assert(snap.baseGroups.length === 2, 'snapshot: 2 base groups');
assert(snap.derivedGraph.length === 2, 'snapshot: 2 derived groups');
assert(snap.lsConfigs.length === 1, 'snapshot: 1 LS config');
assert(snap.registrations.length === 1, 'snapshot: 1 registration entry');

// Reset and apply
resetAll();
assertEquals(settings.snapshot().baseGroups, [], 'resetAll: base_groups cleared');

var result = settings.apply(snap);
assertEquals(result.applied, { baseGroups: 2, derivedGraph: 2, lsConfigs: 1, registrations: 1 }, 'apply: counts correct');

// Verify round-trip (IDs differ but data counts match)
var snap2 = settings.snapshot();
assert(snap2.baseGroups.length === 2, 'round-trip: 2 base groups');
assert(snap2.derivedGraph.length === 2, 'round-trip: 2 derived groups');
assert(snap2.lsConfigs.length === 1, 'round-trip: 1 LS config');
assert(snap2.registrations.length === 1, 'round-trip: 1 registration entry');
// Verify cross-references are consistent (IDs may differ from original)
var snap2Dg = snap2.derivedGraph;
var snap2Bg = snap2.baseGroups;
assert(snap2Dg.every(function(d) { return snap2Bg.some(function(b) { return b.id === d.baseGroupId; }); }), 'round-trip: derived → base refs valid');
assert(snap2.lsConfigs[0].longGroupId && snap2.lsConfigs[0].shortGroupId, 'round-trip: LS config has groups');

// ---------------------------------------------------------------------------
// 4. diff
// ---------------------------------------------------------------------------

var snapA = { baseGroups: [{ id: 'a' }], derivedGraph: [], lsConfigs: [], registrations: [] };
var snapB = { baseGroups: [{ id: 'a' }, { id: 'b' }], derivedGraph: [], lsConfigs: [], registrations: [] };
var d1 = settings.diff(snapA, snapB);
assertEquals(d1.keys, ['baseGroups'], 'diff: detects baseGroups change');
assertEquals(d1.details.baseGroups, { oldCount: 1, newCount: 2 }, 'diff: baseGroups count diff');

var snapC = { baseGroups: [], derivedGraph: [], lsConfigs: [{ id: 'ls1' }], registrations: [] };
var d2 = settings.diff(snapB, snapC);
assertEquals(d2.keys.sort(), ['baseGroups', 'lsConfigs'], 'diff: detects two changes');

// No diff
var d3 = settings.diff(snapA, snapA);
assertEquals(d3.keys, [], 'diff: zero differences for identical');

// ---------------------------------------------------------------------------
// 5. apply with errors (missing datamodel)
// ---------------------------------------------------------------------------

resetAll();
var oldBase = GT.datamodel.base_groups;
delete GT.datamodel.base_groups;
var snapForError = { baseGroups: [{ name: 'b1', testerId: 't1', factorAlias: 'f1', groupCount: 3, dayPeriods: 5, feeMode: 'uniform', feeRate: 0.001 }], derivedGraph: [], lsConfigs: [], registrations: [] };
var r1 = settings.apply(snapForError);
GT.datamodel.base_groups = oldBase;
assert(r1.errors.length > 0, 'apply: errors when datamodel missing');

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------

console.log('\n=== Results ===');
console.log('Passed: ' + passed);
console.log('Failed: ' + failed);
if (failed > 0) process.exit(1);
