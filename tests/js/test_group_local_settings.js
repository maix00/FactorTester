const { assert, resetGroupTest, MockElement, load } = require('./group_test_harness');

const GT = resetGroupTest();
['group_start_year', 'group_start_month', 'group_start_day', 'group_end_year', 'group_end_month', 'group_end_day']
  .forEach((id) => document.registerElement(id, new MockElement(id)));

load('core/local-settings/index.js');
load('core/dates.js');
load('core/local-settings/dates.js');

document.getElementById('group_start_year').value = '2024';
document.getElementById('group_start_month').value = '03';
document.getElementById('group_start_day').value = '05';
document.getElementById('group_end_year').value = '2024';
document.getElementById('group_end_month').value = '04';
document.getElementById('group_end_day').value = '08';

const snapshot = GT.localSettings.collect();
assert.deepStrictEqual(snapshot.dates, {
  startDate: '2024-03-05',
  endDate: '2024-04-08',
});

document.getElementById('group_start_year').value = '2026';
document.getElementById('group_start_month').value = '01';
document.getElementById('group_start_day').value = '01';
document.getElementById('group_end_year').value = '2026';
document.getElementById('group_end_month').value = '01';
document.getElementById('group_end_day').value = '02';

const result = GT.localSettings.apply(snapshot);
assert.deepStrictEqual(result.errors, []);
assert.strictEqual(document.getElementById('group_start_year').value, '2024');
assert.strictEqual(document.getElementById('group_start_month').value, '03');
assert.strictEqual(document.getElementById('group_start_day').value, '05');
assert.strictEqual(document.getElementById('group_end_year').value, '2024');
assert.strictEqual(document.getElementById('group_end_month').value, '04');
assert.strictEqual(document.getElementById('group_end_day').value, '08');
assert.ok(GT.localSettings.summarize(snapshot)[0].includes('2024-03-05'));
assert.deepStrictEqual(GT.localSettings.getRunFields(), snapshot.dates);
assert.deepStrictEqual(GT.localSettings.prepareRun().payload, {
  start_date: '2024-03-05',
  end_date: '2024-04-08',
});
assert.deepStrictEqual(GT.localSettings.prepareRun().errors, []);

console.log('PASS: GroupTest dates register under local settings');
