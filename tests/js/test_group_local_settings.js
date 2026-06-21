const { assert, resetGroupTest, MockElement, load } = require('./group_test_harness');

const GT = resetGroupTest();
['group_start_year', 'group_start_month', 'group_start_day', 'group_end_year', 'group_end_month', 'group_end_day', 'group_initial_capital']
  .forEach((id) => document.registerElement(id, new MockElement(id)));

load('core/local-settings/index.js');
load('core/date-inputs.js');
load('core/local-settings/dates.js');
load('core/local-settings/initial-capital.js');

document.getElementById('group_start_year').value = '2024';
document.getElementById('group_start_month').value = '03';
document.getElementById('group_start_day').value = '05';
document.getElementById('group_end_year').value = '2024';
document.getElementById('group_end_month').value = '04';
document.getElementById('group_end_day').value = '08';
document.getElementById('group_initial_capital').value = '250000';

const snapshot = GT.localSettings.collect();
assert.strictEqual(snapshot.dates.startDate, '2024-03-05');
assert.strictEqual(snapshot.dates.endDate, '2024-04-08');
assert.strictEqual(snapshot.dates.precision, 'exact');
assert.strictEqual(snapshot.initialCapital.initialCapital, 250000);
assert.strictEqual(snapshot.initialCapital.baseCurrency, 'CNY');
assert.strictEqual(snapshot.initialCapital.currencyConversionFeeRate, 0);

document.getElementById('group_start_year').value = '2026';
document.getElementById('group_start_month').value = '01';
document.getElementById('group_start_day').value = '01';
document.getElementById('group_end_year').value = '2026';
document.getElementById('group_end_month').value = '01';
document.getElementById('group_end_day').value = '02';
document.getElementById('group_initial_capital').value = '1000';

const result = GT.localSettings.apply(snapshot);
assert.deepStrictEqual(result.errors, []);
assert.strictEqual(document.getElementById('group_start_year').value, '2024');
assert.strictEqual(Number(document.getElementById('group_start_month').value), 3);
assert.strictEqual(Number(document.getElementById('group_start_day').value), 5);
assert.strictEqual(document.getElementById('group_end_year').value, '2024');
assert.strictEqual(Number(document.getElementById('group_end_month').value), 4);
assert.strictEqual(Number(document.getElementById('group_end_day').value), 8);
assert.strictEqual(document.getElementById('group_initial_capital').value, '250000');
assert.ok(GT.localSettings.summarize(snapshot)[0].includes('2024-03-05'));
assert.ok(GT.localSettings.summarize(snapshot)[1].includes('250000'));
const fields = GT.localSettings.getRunFields();
assert.strictEqual(fields.startDate, '2024-03-05');
assert.strictEqual(fields.endDate, '2024-04-08');
assert.strictEqual(fields.initialCapital, 250000);
assert.strictEqual(fields.baseCurrency, 'CNY');
const payload = GT.localSettings.prepareRun().payload;
assert.strictEqual(payload.start_date, '2024-03-05');
assert.strictEqual(payload.end_date, '2024-04-08');
assert.strictEqual(payload.initial_capital, 250000);
assert.strictEqual(payload.base_currency, 'CNY');
assert.deepStrictEqual(GT.localSettings.prepareRun().errors, []);

console.log('PASS: GroupTest dates register under local settings');
