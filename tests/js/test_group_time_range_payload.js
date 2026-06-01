var assert = require('assert');
var root = require('path').join(__dirname, '../..');

function makeElement(value) {
    return {
        value: value || '',
        addEventListener: function() {},
        closest: function() { return null; },
    };
}

var elements = {
    group_start_year: makeElement('2026'),
    group_start_month: makeElement('02'),
    group_start_day: makeElement('03'),
    group_end_year: makeElement('2026'),
    group_end_month: makeElement('04'),
    group_end_day: makeElement('05'),
};

global.window = global;
global.document = {
    readyState: 'loading',
    getElementById: function(id) { return elements[id] || null; },
    querySelector: function() { return null; },
    querySelectorAll: function() { return []; },
    addEventListener: function() {},
    createElement: function() { return { style: {}, appendChild: function() {} }; },
};
global.setTimeout = function() {};
global.GroupTest = {
    datamodel: {},
    state: { emit: function() {}, on: function() {}, off: function() {} },
    log: function() {},
    ui: {},
};

global.window.DateUtils = {
    getMaxDay: function(y, m) { return new Date(y, m, 0).getDate(); },
    pad: function(n) { return n < 10 ? '0' + n : String(n); },
};

require(root + '/static/js/modules/single_factor_test/group_test/app.js');

var resolved = GroupTest.ui._resolveGroupRunTimeRange(
    '2025-01-01',
    '2025-12-31',
    { start_date: '2024-01-01', end_date: '2024-12-31' }
);
assert.strictEqual(resolved.startDate, '2026-02-03');
assert.strictEqual(resolved.endDate, '2026-04-05');
assert.strictEqual(resolved.explicitStartDate, '2026-02-03');
assert.strictEqual(resolved.explicitEndDate, '2026-04-05');

elements.group_start_year.value = '';
elements.group_start_month.value = '';
elements.group_start_day.value = '';
elements.group_end_year.value = '';
elements.group_end_month.value = '';
elements.group_end_day.value = '';
resolved = GroupTest.ui._resolveGroupRunTimeRange(
    '2025-01-01',
    '2025-12-31'
);
assert.strictEqual(resolved.startDate, '2025-01-01');
assert.strictEqual(resolved.endDate, '2025-12-31');

console.log('group time range payload OK');
