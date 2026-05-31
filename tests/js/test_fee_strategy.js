/**
 * test_fee_strategy.js — Node.js tests for fee_strategy.js
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
        _lastEvent: null,
        _events: [],
        state: {
            emit: function(event, data) {
                window.GroupTest._lastEvent = { event: event, data: data };
                window.GroupTest._events.push({ event: event, data: data });
            }
        },
        log: function() {}
    }
};

var GT = window.GroupTest;

// Load all prior datamodel modules
require('../../static/js/modules/single_factor_test/group_test/datamodel/base_groups.js');
require('../../static/js/modules/single_factor_test/group_test/datamodel/derived_graph.js');
require('../../static/js/modules/single_factor_test/group_test/datamodel/ls_configs.js');
require('../../static/js/modules/single_factor_test/group_test/panels/config/fee/strategy.js');

var bg = GT.datamodel.base_groups;
var dg = GT.datamodel.derived_graph;
var ls = GT.datamodel.ls_configs;
var fs = GT.datamodel.fee_strategy;

// ---------------------------------------------------------------------------
// Seed data
// ---------------------------------------------------------------------------

// Base group with uniform fee
var bg1 = bg.add({ name: 'BG Uniform', testerId: 't1', factorAlias: 'f1', groupCount: 5, feeMode: 'uniform', feeRate: 0.001 });
// Base group with per_product fee
var bg2 = bg.add({ name: 'BG PerProduct', testerId: 't2', factorAlias: 'f2', groupCount: 3, feeMode: 'per_product', feeMap: { 'IF/IF00': 0.0002, 'IC/IC00': 0.0003 } });
// Base group with none fee
var bg3 = bg.add({ name: 'BG None', testerId: 't3', factorAlias: 'f3', groupCount: 2, feeMode: 'none', useCloseToday: true, rebalanceMode: 'buy_and_hold' });

// Derived groups
var root = dg.add({ name: 'Root', baseGroupId: bg1 });
var child = dg.add({ name: 'Child', baseGroupId: bg1, parentId: root.id });
var grandchild = dg.add({ name: 'Grandchild', baseGroupId: bg1, parentId: child.id });

// Root with overrides
var root2 = dg.add({ name: 'Root2', baseGroupId: bg1, feeOverride: { mode: 'uniform', rate: 0.005, feeMap: null }, closeTodayOverride: false });

// Root with none base group
var root3 = dg.add({ name: 'Root3', baseGroupId: bg3 });

// ---------------------------------------------------------------------------
// 1. resolveFee — inheritance chain
// ---------------------------------------------------------------------------

// No override → inherits base group
var r = fs.resolveFee(grandchild.id);
assertEquals(r.mode, 'uniform', 'resolveFee: grandchild inherits uniform from base');
assertEquals(r.rate, 0.001, 'resolveFee: grandchild inherits rate 0.001');

// Override at root → child inherits
r = fs.resolveFee(child.id);
assertEquals(r.mode, 'uniform', 'resolveFee: child (no override) inherits from base');

// Override at root → grandchild inherits root's override
var grandchildOfRoot2 = dg.add({ name: 'GC2', baseGroupId: bg1, parentId: root2.id });
r = fs.resolveFee(grandchildOfRoot2.id);
assertEquals(r.rate, 0.005, 'resolveFee: grandchild inherits root override 0.005');

// FeeOverride on own node
var withOverride = dg.add({ name: 'FeeOverride', baseGroupId: bg1, parentId: root.id, feeOverride: { mode: 'uniform', rate: 0.009, feeMap: null } });
r = fs.resolveFee(withOverride.id);
assertEquals(r.rate, 0.009, 'resolveFee: node with own override uses it');

// Per-product base group
var rootPP = dg.add({ name: 'RootPP', baseGroupId: bg2 });
r = fs.resolveFee(rootPP.id);
assertEquals(r.mode, 'per_product', 'resolveFee: per_product mode');
assertEquals(r.feeMap, { 'IF/IF00': 0.0002, 'IC/IC00': 0.0003 }, 'resolveFee: per_product feeMap');

// None base group
r = fs.resolveFee(root3.id);
assertEquals(r.mode, 'none', 'resolveFee: none mode');
assertEquals(r.rate, null, 'resolveFee: none rate is null');

// Throws on missing
assertThrows(function() { fs.resolveFee('non-existent'); }, 'resolveFee: throws on missing');

// ---------------------------------------------------------------------------
// 2. resolveCloseToday
// ---------------------------------------------------------------------------

var ct = fs.resolveCloseToday(root3.id);
assertEquals(ct, true, 'resolveCloseToday: inherits true from base group');

var ct2 = fs.resolveCloseToday(root2.id);
assertEquals(ct2, false, 'resolveCloseToday: root2 has own override=false');

var ct3 = fs.resolveCloseToday(root.id);
assertEquals(ct3, false, 'resolveCloseToday: root (no override, no parent) returns default false');

// ---------------------------------------------------------------------------
// 3. resolveRebalance
// ---------------------------------------------------------------------------

var rb = fs.resolveRebalance(root3.id);
assertEquals(rb, 'buy_and_hold', 'resolveRebalance: inherits from base group');

var rb2 = fs.resolveRebalance(root.id);
assertEquals(rb2, 'each_period', 'resolveRebalance: returns default each_period');

// ---------------------------------------------------------------------------
// 4. uniformToCustom
// ---------------------------------------------------------------------------

var feeMap = fs.uniformToCustom(bg1, ['IF', 'IC', 'IH']);
assertEquals(feeMap, { 'IF': 0.001, 'IC': 0.001, 'IH': 0.001 }, 'uniformToCustom: expands rate to all products');

// Not uniform → null
var feeMap2 = fs.uniformToCustom(bg2, ['IF']);
assertEquals(feeMap2, null, 'uniformToCustom: returns null for per_product');

// None mode → null
var feeMap3 = fs.uniformToCustom(bg3, ['IF']);
assertEquals(feeMap3, null, 'uniformToCustom: returns null for none');

// Throws on missing bg
assertThrows(function() { fs.uniformToCustom('non-existent', []); }, 'uniformToCustom: throws on missing');

// Empty products
var feeMap4 = fs.uniformToCustom(bg1, []);
assertEquals(feeMap4, {}, 'uniformToCustom: empty products gives empty map');

// ---------------------------------------------------------------------------
// 5. collectFeeModifications
// ---------------------------------------------------------------------------

var mods = fs.collectFeeModifications(withOverride.id);
assert(mods.length === 1, 'collectFeeModifications: 1 override (own)');
assertEquals(mods[0].field, 'feeOverride', 'collectFeeModifications: feeOverride collected');

// Root2 has 2 overrides
var mods2 = fs.collectFeeModifications(root2.id);
assert(mods2.length >= 2, 'collectFeeModifications: root2 has 2 overrides');

// Root has a child withOverride, so should collect that
var mods3 = fs.collectFeeModifications(root.id);
assert(mods3.length === 1, 'collectFeeModifications: root collects child override');
assertEquals(mods3[0].nodeId, withOverride.id, 'collectFeeModifications: correct child override nodeId');

// Ensure a leaf with truly no overrides returns empty
var leafNoOverride = dg.add({ name: 'LeafNoOv', baseGroupId: bg1, parentId: root.id });
var mods4 = fs.collectFeeModifications(leafNoOverride.id);
assertEquals(mods4, [], 'collectFeeModifications: leaf with no overrides → empty');

// Throws on missing
assertThrows(function() { fs.collectFeeModifications('non-existent'); }, 'collectFeeModifications: throws on missing');

// ---------------------------------------------------------------------------
// 6. resolveLsFee
// ---------------------------------------------------------------------------

// Seed LS configs
var lsc1 = ls.add({ name: 'LS1', longGroupId: root2.id, shortGroupId: root.id, feeMode: 'override', feeRate: 0.01 });
var lsc2 = ls.add({ name: 'LS2', longGroupId: root.id, shortGroupId: root2.id, feeMode: 'inherit' });

// Override mode
var lsf = fs.resolveLsFee(lsc1.id);
assertEquals(lsf.mode, 'uniform', 'resolveLsFee: override mode uniform');
assertEquals(lsf.rate, 0.01, 'resolveLsFee: override uses own feeRate');

// Inherit mode
var lsf2 = fs.resolveLsFee(lsc2.id);
assertEquals(lsf2.rate, 0.001, 'resolveLsFee: inherit uses long group fee');

// Throws on missing
assertThrows(function() { fs.resolveLsFee('non-existent'); }, 'resolveLsFee: throws on missing');

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------

console.log('\n=== Results ===');
console.log('Passed: ' + passed);
console.log('Failed: ' + failed);
if (failed > 0) process.exit(1);
