/**
 * test_ls_configs.js — Node.js tests for ls_configs.js
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
        datamodel: {
            groups: {
                get: function(id) { return window._dgStore[id] || null; },
                getAll: function() { return Object.keys(window._dgStore).map(function(k) { return window._dgStore[k]; }); }
            }
        },
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

window._dgStore = {}; // mock derived groups

function resetEvents() {
    window.GroupTest._lastEvent = null;
    window.GroupTest._events = [];
}

function seedDG(id) {
    window._dgStore[id] = { id: id, name: 'DG_' + id };
}

require('../../static/js/modules/single_factor_test/group_test/datamodel/ls_configs.js');

var ls = window.GroupTest.datamodel.ls_configs;

// Seed mock derived groups
seedDG('dg_001');
seedDG('dg_002');
window._dgStore.dg_001.shortAlias = 'A1';
window._dgStore.dg_002.shortAlias = 'A5';

// ---------------------------------------------------------------------------
// 1. validate
// ---------------------------------------------------------------------------

// reject empty
var r = ls.validate({});
assertEquals(r.valid, false, 'validate: reject empty');

// reject missing name
r = ls.validate({ longGroupId: 'dg_001', shortGroupId: 'dg_002' });
assertEquals(r.valid, false, 'validate: reject missing name');

// reject missing longGroupId
r = ls.validate({ name: 'test', shortGroupId: 'dg_002' });
assertEquals(r.valid, false, 'validate: reject missing longGroupId');

// reject missing shortGroupId
r = ls.validate({ name: 'test', longGroupId: 'dg_001' });
assertEquals(r.valid, false, 'validate: reject missing shortGroupId');

// reject non-existent longGroupId
r = ls.validate({ name: 'test', longGroupId: 'dg_bad', shortGroupId: 'dg_002' });
assertEquals(r.valid, false, 'validate: reject bad longGroupId');

// reject non-existent shortGroupId
r = ls.validate({ name: 'test', longGroupId: 'dg_001', shortGroupId: 'dg_bad' });
assertEquals(r.valid, false, 'validate: reject bad shortGroupId');

// reject invalid feeMode
r = ls.validate({ name: 'test', longGroupId: 'dg_001', shortGroupId: 'dg_002', feeMode: 'invalid' });
assertEquals(r.valid, false, 'validate: reject invalid feeMode');

// reject negative feeRate
r = ls.validate({ name: 'test', longGroupId: 'dg_001', shortGroupId: 'dg_002', feeRate: -0.1 });
assertEquals(r.valid, false, 'validate: reject negative feeRate');

// reject invalid rebalanceMode
r = ls.validate({ name: 'test', longGroupId: 'dg_001', shortGroupId: 'dg_002', rebalanceMode: 'invalid' });
assertEquals(r.valid, false, 'validate: reject invalid rebalanceMode');

// reject array metadata
r = ls.validate({ name: 'test', longGroupId: 'dg_001', shortGroupId: 'dg_002', metadata: [] });
assertEquals(r.valid, false, 'validate: reject array metadata');

// accept valid
r = ls.validate({ name: 'test', longGroupId: 'dg_001', shortGroupId: 'dg_002' });
assertEquals(r.valid, true, 'validate: accept valid');

// accept valid feeMode
r = ls.validate({ name: 'test', longGroupId: 'dg_001', shortGroupId: 'dg_002', feeMode: 'override' });
assertEquals(r.valid, true, 'validate: accept feeMode=override');

// ---------------------------------------------------------------------------
// 2. add
// ---------------------------------------------------------------------------

resetEvents();
var c1 = ls.add({ name: 'LS 1', longGroupId: 'dg_001', shortGroupId: 'dg_002' });
assert(c1.id.indexOf('ls_') === 0, 'add: id has ls_ prefix');
assertEquals(c1.name, 'LS 1', 'add: stores name');
assertEquals(c1.longGroupId, 'dg_001', 'add: stores longGroupId');
assertEquals(c1.shortGroupId, 'dg_002', 'add: stores shortGroupId');
assertEquals(c1.feeMode, 'inherit', 'add: feeMode defaults to inherit');
assertEquals(c1.feeRate, null, 'add: feeRate defaults to null');
assertEquals(c1.useCloseToday, null, 'add: useCloseToday defaults to null');
assertEquals(c1.rebalanceMode, null, 'add: rebalanceMode defaults to null');
assertEquals(c1.needsRegenerate, true, 'add: needsRegenerate defaults to true');
assertEquals(c1.metadata, {}, 'add: metadata defaults to {}');
assertEquals(c1.shortAlias, 'A1/A5', 'add: stores fixed shortAlias from legs');

// add with custom values
var c2 = ls.add({
    name: 'Custom LS',
    longGroupId: 'dg_002',
    shortGroupId: 'dg_001',
    feeMode: 'override',
    feeRate: 0.002,
    useCloseToday: true,
    rebalanceMode: 'buy_and_hold',
    metadata: { k: 'v' }
});
assertEquals(c2.feeMode, 'override', 'add: stores custom feeMode');
assertEquals(c2.feeRate, 0.002, 'add: stores custom feeRate');
assertEquals(c2.useCloseToday, true, 'add: stores custom useCloseToday');
assertEquals(c2.rebalanceMode, 'buy_and_hold', 'add: stores custom rebalanceMode');
assertEquals(c2.metadata, { k: 'v' }, 'add: stores custom metadata');

// add emits
var evt = window.GroupTest._lastEvent;
assertEquals(evt.event, 'lsConfigsChanged', 'add: emits lsConfigsChanged');
assertEquals(evt.data.action, 'add', 'add: event action is add');

// add throws on invalid
assertThrows(function() { ls.add({}); }, 'add: throws on invalid');

// ---------------------------------------------------------------------------
// 3. get
// ---------------------------------------------------------------------------

assertEquals(ls.get('non-existent'), null, 'get: null for missing');
var g1 = ls.get(c1.id);
assertEquals(g1.name, 'LS 1', 'get: returns correct item');
g1.name = 'Mutated';
assertEquals(ls.get(c1.id).name, 'LS 1', 'get: deep copy');

// ---------------------------------------------------------------------------
// 4. getAll
// ---------------------------------------------------------------------------

var all = ls.getAll();
assert(all.length === 2, 'getAll: returns 2 items');

// ---------------------------------------------------------------------------
// 5. update
// ---------------------------------------------------------------------------

var u1 = ls.update(c1.id, { name: 'Updated LS', feeMode: 'override' });
assertEquals(u1.name, 'Updated LS', 'update: patches name');
assertEquals(u1.feeMode, 'override', 'update: patches feeMode');
var uAlias = ls.update(c1.id, { longGroupId: 'dg_002', shortGroupId: 'dg_001' });
assertEquals(uAlias.shortAlias, 'A5/A1', 'update: recomputes fixed shortAlias when legs change');

// update emits
resetEvents();
ls.update(c1.id, { name: 'X' });
assertEquals(window.GroupTest._lastEvent.event, 'lsConfigsChanged', 'update: emits');
assertEquals(window.GroupTest._lastEvent.data.action, 'update', 'update: event action');

// update throws on invalid
assertThrows(function() { ls.update(c1.id, { longGroupId: 'dg_bad' }); }, 'update: throws on bad ref');
assertThrows(function() { ls.update('non-existent', { name: 'x' }); }, 'update: throws on missing');

// ---------------------------------------------------------------------------
// 6. markStale
// ---------------------------------------------------------------------------

// Set needsRegenerate false first via internal hack (mock a "fresh" state)
// Actually, let us just test markStale sets it to true
resetEvents();
var s1 = ls.markStale(c2.id);
assertEquals(s1.needsRegenerate, true, 'markStale: sets needsRegenerate');
assertEquals(window.GroupTest._lastEvent.event, 'lsConfigsChanged', 'markStale: emits');
assertEquals(window.GroupTest._lastEvent.data.action, 'markStale', 'markStale: event action');

assertThrows(function() { ls.markStale('non-existent'); }, 'markStale: throws on missing');

// ---------------------------------------------------------------------------
// 7. findByDerivedGroup
// ---------------------------------------------------------------------------

var refs = ls.findByDerivedGroup('dg_001');
assert(refs.length >= 1, 'findByDerivedGroup: finds references to dg_001');
var refs2 = ls.findByDerivedGroup('dg_nonexistent');
assertEquals(refs2.length, 0, 'findByDerivedGroup: empty for no refs');

// ---------------------------------------------------------------------------
// 8. remove
// ---------------------------------------------------------------------------

resetEvents();
var removed = ls.remove(c2.id);
assertEquals(removed.name, 'Custom LS', 'remove: returns removed item');
assertEquals(ls.get(c2.id), null, 'remove: item gone');
assertEquals(window.GroupTest._lastEvent.event, 'lsConfigsChanged', 'remove: emits');
assertEquals(window.GroupTest._lastEvent.data.action, 'remove', 'remove: event action');

assertThrows(function() { ls.remove('non-existent'); }, 'remove: throws on missing');

// ---------------------------------------------------------------------------
// 9. list
// ---------------------------------------------------------------------------

var summaries = ls.list();
assert(summaries.length === 1, 'list: 1 item after remove');
assertEquals(summaries[0].name, 'X', 'list: returns correct name');

// ---------------------------------------------------------------------------
// 10. _reset
// ---------------------------------------------------------------------------

ls._reset();
assertEquals(ls.getAll().length, 0, '_reset: clears all');

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------

console.log('\n=== Results ===');
console.log('Passed: ' + passed);
console.log('Failed: ' + failed);
if (failed > 0) process.exit(1);
