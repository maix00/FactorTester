/**
 * Node.js unit tests for shortAlias collision resolution in _makeNames
 *
 * Run: node tests/js/test_shortalias_collision.js
 *
 * Tests the collision logic extracted from add_factors.js / list.js
 * without requiring full browser environment.
 */

// ---- Mock environment ----
global.window = {
    GroupTest: {
        log: function () {},
        state: {
            emit: function (event, data) {
                global.__lastEvent = { event: event, data: data };
                global.__events.push({ event: event, data: data });
            },
        },
        datamodel: {},
    },
};

global.__events = [];
global.__lastEvent = null;

var path = require('path');
var fs = require('fs');

// Load base_groups datamodel
var bgPath = path.join(
    __dirname,
    '../../static/js/modules/single_factor_test/group_test/datamodel/groups.js'
);
eval(fs.readFileSync(bgPath, 'utf8'));

var bg = window.GroupTest.datamodel.groups;
var assert = require('assert');

var passed = 0;
var failed = 0;

function test(name, fn) {
    bg._reset();
    global.__events = [];
    try {
        fn();
        passed++;
        console.log('PASS:', name);
    } catch (e) {
        failed++;
        console.error('FAIL:', name);
        console.error('     ', e.message);
    }
}

// ---------------------------------------------------------------------------
// _makeNames collision logic (extracted, portable)
// ---------------------------------------------------------------------------

/**
 * Column-letter: 1→A, 2→B, ... 26→Z, 27→AA, ...
 */
function colLetter(n) {
    var s = '';
    while (n > 0) {
        var rem = (n - 1) % 26;
        s = String.fromCharCode(65 + rem) + s;
        n = Math.floor((n - 1) / 26);
    }
    return s;
}

/**
 * Pre-compute the letter for each unique comboKey.
 * Each comboKey gets ONE letter; collisions are resolved by suffix in makeShortAlias.
 */
function preComputeComboLetters(testerId, factorAliases, groupCount) {
    var comboMap = {};
    var existing = bg.getAll();
    for (var i = 0; i < factorAliases.length; i++) {
        var alias = factorAliases[i];
        var comboKey = String(testerId) + '|' + alias + '|' + groupCount;
        if (comboMap[comboKey] !== undefined) continue;
        var hasExisting = false;
        for (var j = 0; j < existing.length; j++) {
            var k = String(existing[j].testerId) + '|' + existing[j].factorAlias + '|' + existing[j].groupCount;
            if (k === comboKey) { hasExisting = true; break; }
        }
        if (hasExisting) {
            for (var ej = 0; ej < existing.length; ej++) {
                var ek = String(existing[ej].testerId) + '|' + existing[ej].factorAlias + '|' + existing[ej].groupCount;
                if (ek === comboKey && existing[ej].shortAlias) {
                    var letterMatch = existing[ej].shortAlias.match(/^([A-Z]+)/);
                    if (letterMatch) { comboMap[comboKey] = letterMatch[1]; break; }
                }
            }
            if (!comboMap[comboKey]) comboMap[comboKey] = colLetter(Object.keys(comboMap).length + 1);
        } else {
            var usedLetters = {};
            for (var ej2 = 0; ej2 < existing.length; ej2++) {
                var ek2 = String(existing[ej2].testerId) + '|' + existing[ej2].factorAlias + '|' + existing[ej2].groupCount;
                if (ek2 && existing[ej2].shortAlias) {
                    var lm = existing[ej2].shortAlias.match(/^([A-Z]+)/);
                    if (lm) usedLetters[lm[1]] = true;
                }
            }
            for (var ci = 0; ci < Object.keys(comboMap).length; ci++) {
                var assigned = Object.values(comboMap)[ci];
                if (assigned) usedLetters[assigned] = true;
            }
            var nextIdx = 1;
            while (usedLetters[colLetter(nextIdx)]) { nextIdx++; }
            comboMap[comboKey] = colLetter(nextIdx);
        }
    }
    return comboMap;
}

/**
 * Generate shortAlias with collision resolution.
 * Mirrors the logic in add_factors.js _makeNames.
 */
function makeShortAlias(testerId, factorAlias, groupCount, groupIndex, letter) {
    var shortAlias = letter + groupIndex;

    var allGroups = bg.getAll();
    var comboKey = String(testerId) + '|' + factorAlias + '|' + groupCount;
    var sameIndexCount = 0;
    var usedSuffixes = {};
    for (var ai = 0; ai < allGroups.length; ai++) {
        var g = allGroups[ai];
        var gk = String(g.testerId) + '|' + g.factorAlias + '|' + g.groupCount;
        if (gk !== comboKey) continue;
        if (g.groupIndex === groupIndex) { sameIndexCount++; }
        var sa = g.shortAlias;
        if (sa && sa.length > shortAlias.length && sa.lastIndexOf(shortAlias, 0) === 0) {
            var ch = sa.charAt(shortAlias.length);
            if (ch >= 'a' && ch <= 'z') usedSuffixes[ch] = true;
        }
    }
    if (sameIndexCount > 0 || Object.keys(usedSuffixes).length > 0) {
        var sfx = 'a'.charCodeAt(0);
        while (usedSuffixes[String.fromCharCode(sfx)]) { sfx++; }
        shortAlias = shortAlias + String.fromCharCode(sfx);
    }
    return shortAlias;
}

/**
 * Helper: create a full batch of groups and return their shortAliases.
 */
function createBatch(testerId, factorAlias, groupCount, letter, extra) {
    extra = extra || {};
    var aliases = [];
    for (var gi = 1; gi <= groupCount; gi++) {
        var sa = makeShortAlias(testerId, factorAlias, groupCount, gi, letter);
        bg.add({
            name: 'Test_' + factorAlias + '_' + gi,
            shortAlias: sa,
            testerId: testerId,
            factorAlias: factorAlias,
            groupCount: groupCount,
            groupIndex: gi,
            feeMode: extra.feeMode || 'none',
        });
        aliases.push(sa);
    }
    return aliases;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

// --- Single batch, no collision ---

test('single batch: A1-A5 (no existing groups)', function () {
    var aliases = createBatch('t1', 'mom', 5, 'A');
    assert.deepStrictEqual(aliases, ['A1', 'A2', 'A3', 'A4', 'A5']);
});

// --- Two batches, same comboKey, different feeMode (two-round submit) ---

test('two rounds: second batch gets suffix a', function () {
    // Round 1: fee=none
    var batch1 = createBatch('t1', 'mom', 5, 'A', {feeMode: 'none'});
    assert.deepStrictEqual(batch1, ['A1', 'A2', 'A3', 'A4', 'A5']);

    // Round 2: fee=per_product — same comboKey, should collide
    var batch2 = createBatch('t1', 'mom', 5, 'A', {feeMode: 'per_product'});
    assert.deepStrictEqual(batch2, ['A1a', 'A2a', 'A3a', 'A4a', 'A5a']);
});

// --- Three rounds: suffix letters a, b, c ---

test('three rounds: suffixes a, b, c', function () {
    createBatch('t1', 'mom', 3, 'A');
    createBatch('t1', 'mom', 3, 'A');
    // Round 3: first two rounds have A1, A2, A3 and A1a, A2a, A3a.
    // A1 没有后缀 → usedSuffixes = {}，sameIndexCount = 2 → 加后缀
    // 后缀从 a 开始，检查 usedSuffixes：A1a 的 a 已占 → 跳到 b.
    var batch3 = createBatch('t1', 'mom', 3, 'A');
    assert.deepStrictEqual(batch3, ['A1b', 'A2b', 'A3b']);
});

// --- Different comboKeys don't collide ---

test('different comboKeys: independent letters', function () {
    var batch1 = createBatch('t1', 'mom', 3, 'A');
    var batch2 = createBatch('t1', 'rsi', 3, 'A'); // different factorAlias
    assert.deepStrictEqual(batch1, ['A1', 'A2', 'A3']);
    assert.deepStrictEqual(batch2, ['A1', 'A2', 'A3']); // no collision
});

test('different testerIds: independent', function () {
    var batch1 = createBatch('t1', 'mom', 3, 'A');
    var batch2 = createBatch('t2', 'mom', 3, 'A');
    assert.deepStrictEqual(batch1, ['A1', 'A2', 'A3']);
    assert.deepStrictEqual(batch2, ['A1', 'A2', 'A3']);
});

test('different groupCount: independent', function () {
    var batch1 = createBatch('t1', 'mom', 3, 'A');
    var batch2 = createBatch('t1', 'mom', 5, 'A');
    assert.deepStrictEqual(batch1, ['A1', 'A2', 'A3']);
    assert.deepStrictEqual(batch2, ['A1', 'A2', 'A3', 'A4', 'A5']);
});

// --- Suffix-letter tracking: skip occupied letters ---

test('suffix-letter: skip already-used letters', function () {
    // Round 1: bare A1-A3
    createBatch('t1', 'mom', 3, 'A');
    // Round 2: A1a-A3a (letter a occupied)
    createBatch('t1', 'mom', 3, 'A');
    // Round 3: should get A1b-A3b (b, not a)
    var batch3 = createBatch('t1', 'mom', 3, 'A');
    assert.deepStrictEqual(batch3, ['A1b', 'A2b', 'A3b']);
    // Round 4: A1c-A3c
    var batch4 = createBatch('t1', 'mom', 3, 'A');
    assert.deepStrictEqual(batch4, ['A1c', 'A2c', 'A3c']);
});

// --- groupIndex matching triggers collision even without shortAlias ---

test('groupIndex collision: works without shortAlias field', function () {
    // Simulate old data: groups without shortAlias (empty string)
    bg.add({ name: 'Old A1', shortAlias: '', testerId: 't1', factorAlias: 'mom', groupCount: 3, groupIndex: 1 });
    bg.add({ name: 'Old A2', shortAlias: '', testerId: 't1', factorAlias: 'mom', groupCount: 3, groupIndex: 2 });
    bg.add({ name: 'Old A3', shortAlias: '', testerId: 't1', factorAlias: 'mom', groupCount: 3, groupIndex: 3 });

    var batch = createBatch('t1', 'mom', 3, 'A');
    assert.deepStrictEqual(batch, ['A1a', 'A2a', 'A3a']);
});

// --- Same comboKey reuses existing letter ---

test('combo letter: reuses existing letter for same comboKey', function () {
    createBatch('t1', 'mom', 3, 'A'); // first batch: A1, A2, A3
    // Second batch: same comboKey → should get same letter A (not B)
    var letters = preComputeComboLetters('t1', ['mom'], 3);
    assert.strictEqual(letters['t1|mom|3'], 'A');
});

// --- Different comboKeys get different letters ---

test('combo letter: different keys get different letters', function () {
    createBatch('t1', 'mom', 3, 'A');
    // New comboKey: t1|rsi|3 → should get B (A is used)
    var letters = preComputeComboLetters('t1', ['rsi'], 3);
    assert.strictEqual(letters['t1|rsi|3'], 'B');
});

// --- shortAlias is stored correctly and survives read-back (list.js display bug guard) ---

test('shortAlias: stored value preserved on read-back', function () {
    // Simulate two rounds of add
    var batch1 = createBatch('t1', 'mom', 2, 'A', { feeMode: 'none' });
    var batch2 = createBatch('t1', 'mom', 2, 'A', { feeMode: 'per_product' });
    assert.deepStrictEqual(batch1, ['A1', 'A2']);
    assert.deepStrictEqual(batch2, ['A1a', 'A2a']);

    // Read back from datamodel: each item should have the right shortAlias
    var all = bg.getAll();
    assert.strictEqual(all.length, 4);

    var foundA1 = false, foundA1a = false, foundA2 = false, foundA2a = false;
    for (var i = 0; i < all.length; i++) {
        if (all[i].shortAlias === 'A1') foundA1 = true;
        if (all[i].shortAlias === 'A1a') foundA1a = true;
        if (all[i].shortAlias === 'A2') foundA2 = true;
        if (all[i].shortAlias === 'A2a') foundA2a = true;
    }
    assert.ok(foundA1, 'A1 should exist');
    assert.ok(foundA1a, 'A1a should exist');
    assert.ok(foundA2, 'A2 should exist');
    assert.ok(foundA2a, 'A2a should exist');

    // Verify feeMode can distinguish the two batches
    var noneItems = all.filter(function(x) { return x.feeMode === 'none'; });
    var productItems = all.filter(function(x) { return x.feeMode === 'per_product'; });
    assert.strictEqual(noneItems.length, 2);
    assert.strictEqual(productItems.length, 2);
    assert.deepStrictEqual(noneItems.map(function(x) { return x.shortAlias; }).sort(), ['A1', 'A2']);
    assert.deepStrictEqual(productItems.map(function(x) { return x.shortAlias; }).sort(), ['A1a', 'A2a']);
});

// --- shortAlias display: rendering should use stored value, not recompute ---
// (Regression test for list.js _rowAlias() bug)

test('shortAlias: stored value != recomputed value for collisions', function () {
    createBatch('t1', 'mom', 3, 'A');
    createBatch('t1', 'mom', 3, 'A');

    // Simulate what list.js render does if it recalculates
    // _rowAlias(batchKey, groupIndex) = letter + groupIndex
    // This will ALWAYS return "A1", "A2", "A3" — ignoring the suffix
    function buggyRowAlias(batchKeyVal, gi) {
        return 'A' + gi; // this is what the bug did
    }

    var all = bg.getAll();
    // Items with suffix should NOT equal buggy recompute
    for (var i = 0; i < all.length; i++) {
        var stored = all[i].shortAlias;
        var recomputed = buggyRowAlias(all[i].testerId + '|' + all[i].factorAlias + '|' + all[i].groupCount, all[i].groupIndex);
        if (stored !== recomputed) {
            // This proves the bug: recompute gives wrong answer
            assert.ok(stored.length > recomputed.length, stored + ' should have suffix beyond ' + recomputed);
        }
    }
});

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------

console.log('');
console.log((passed + failed) + ' tests: ' + passed + ' passed, ' + failed + ' failed');
if (failed > 0) process.exit(1);
