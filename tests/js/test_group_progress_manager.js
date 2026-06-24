const path = require('path');
const { assert, MockElement, resetGroupTest, load } = require('./group_test_harness');

const sharedProgressPath = path.resolve(__dirname, '../../static/js/modules/single_factor_test/single_factor_progress.js');
delete require.cache[sharedProgressPath];

const GT = resetGroupTest();
global.SingleFactorProgress = undefined;
require(sharedProgressPath);

const container = new MockElement('progress-container');
container.children = [];
container.appendChild = (child) => {
  container.children.push(child);
  child.parentNode = container;
  return child;
};

load('core/run-group-batch.js');

const manager = GT.groupSettings.runGroupBatch.createManager({
  progressContainer: container,
  phaseLabels: { trade_data: '数据准备', simulate: '交易账本模拟' },
  subStepLabels: { trade_data: { calendar: '交易日历' } },
});

manager.registerPhases(['trade_data', 'simulate']);
manager.syncRows(1);
manager.updateRow(0, 'trade_data', 0, 1, '加载收益', 'load_returns');
manager.updateRow(0, 'trade_data', 0, 1, '加载价格', 'load_prices');
let row = manager.getRow(0);
let tradeData = row.phaseHistory.trade_data;
assert.equal(tradeData.subSteps.load_returns.done, true);
assert.equal(tradeData.subSteps.load_returns.completed, 1);
assert.equal(tradeData.subSteps.load_returns.total, 1);
assert.equal(tradeData.completed, 1);
assert.equal(tradeData.total, 2);

manager.updateRow(0, 'trade_data', 0, 0, '已有缓存，跳过', 'calendar');
manager.updateRow(0, 'simulate', 1, 1, '完成');

row = manager.getRow(0);
tradeData = row.phaseHistory.trade_data;
assert.equal(tradeData.done, true);
assert.equal(tradeData.completed, 3);
assert.equal(tradeData.total, 3);
assert.equal(tradeData.subSteps.calendar.done, true);
assert.equal(tradeData.subSteps.calendar.completed, 1);
assert.equal(tradeData.subSteps.calendar.total, 1);
assert.equal(row.phaseHistory.simulate.completed, 1);
assert.equal(row.phaseHistory.simulate.total, 1);

manager.markAllDone(true, '完成');
assert.equal(row.pct, 100);
assert.equal(row.textEl.textContent, '100%');

console.log('PASS: group progress manager completes count-less sub-steps');
