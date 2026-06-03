const { assert, resetGroupTest, registerConfigFields, load } = require('./group_test_harness');

const GT = resetGroupTest();
load('panels/list/selection-state.js');
load('core/local-settings/index.js');
load('core/dates.js');
load('core/local-settings/dates.js');
load('core/group-settings.js');
registerConfigFields(GT);
load('core/prerun-collect.js');

document.registerElement('group_start_year').value = '2026';
document.registerElement('group_start_month').value = '02';
document.registerElement('group_start_day').value = '03';
document.registerElement('group_end_year').value = '2026';
document.registerElement('group_end_month').value = '02';
document.registerElement('group_end_day').value = '31';

assert.deepStrictEqual(GT.core.dates.readGroupTimeRangeInput(), {
  startDate: '2026-02-03',
  endDate: '2026-02-28',
});

GT.groupSettings.groups.add({
  id: 'base-time',
  name: 'Time',
  testerId: 'tester-time',
  factorAlias: 'FactorTime',
  groupCount: 4,
  groupIndex: 1,
  startDate: '2025-01-01',
  endDate: '2025-01-02',
  feeMode: 'uniform',
  feeRate: 0.0001,
  rebalanceMode: 'recycle',
});

(async () => {
  const result = await GT.core.prerunCollect.buildGroupRunPayload('tester-time', 'FactorTime');
  assert.ifError(result.error);
  assert.strictEqual(result.payload.start_date, '2026-02-03');
  assert.strictEqual(result.payload.end_date, '2026-02-28');
  assert.strictEqual(result.payload.fee, 0.0001);
  assert.strictEqual(result.payload.rebalance_mode, 'recycle');
  console.log('PASS: group run payload uses local-settings dates and group config fields');
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
