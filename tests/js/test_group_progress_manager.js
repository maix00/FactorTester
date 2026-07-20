const path = require('path');
const { assert, MockElement, resetGroupTest, load } = require('./group_test_harness');

const sharedProgressPath = path.resolve(__dirname, '../../static/js/modules/single_factor_test/single_factor_progress.js');
delete require.cache[sharedProgressPath];

const GT = resetGroupTest();
global.SingleFactorProgress = undefined;
require(sharedProgressPath);

function createContainer(id) {
  const container = new MockElement(id);
  container.children = [];
  container.appendChild = (child) => {
    container.children.push(child);
    child.parentNode = container;
    return child;
  };
  return container;
}

load('core/run-group-batch.js');

const container = createContainer('activity-progress-container');
const manager = GT.groupSettings.runGroupBatch.createManager({
  progressContainer: container,
});

manager.registerActivityManifest([
  {
    key: 'pre_replay',
    label: '回放准备',
    flows: [
      { flow_key: 'prepare.window', flow_label: '解析窗口', display_order: 1 },
    ],
  },
  {
    key: 'event_replay',
    label: '事件回放',
    flows: [
      { flow_key: 'signal.flow', flow_label: '读取信号', event_kind: 'SIGNAL', display_order: 1 },
      { flow_key: 'signal.compose', flow_label: '合成Long-Short目标', event_kind: 'SIGNAL', display_order: 2 },
      { flow_key: 'notice.flow', flow_label: '处理通知', event_kind: 'TRADE_INTENT', display_order: 2 },
      { flow_key: 'order.flow', flow_label: '处理订单', event_kind: 'ORDER', display_order: 3 },
    ],
  },
  {
    key: 'post_replay',
    label: '回放收尾',
    flows: [
      { flow_key: 'risk.flow', flow_label: '计算指标', display_order: 1 },
    ],
  },
]);

const row = manager.getRow();
assert(row.root.classList.contains('is-running'));
assert(!row.root.classList.contains('is-event-replaying'));
assert(row.diagram.innerHTML.includes('gt-flow-event-root'));
assert(row.diagram.innerHTML.includes('gt-flow-merge-junction'));
assert(row.diagram.innerHTML.includes('事件回放（event_replay）'));
assert(row.diagram.innerHTML.includes('合成多空组合（Long-Short）目标'));

const flowStyle = global.document.body.children.find((child) => child.id === 'gt-flow-line-style');
assert(flowStyle, 'flow diagram stylesheet should be installed');
assert(!flowStyle.textContent.includes('writing-mode:vertical-rl'));
assert(flowStyle.textContent.includes('width:max-content'));

manager.updateSignalProgress({ phase: 'event_replay', completed: 1, total: 4 });
assert.equal(row.fill.style.width, '25.00%');
assert(row.root.classList.contains('is-event-replaying'));
assert(row.diagram.innerHTML.includes('gt-flow-line-phase is-active is-event-phase'));

// Percentage-only SSE packets must retain the existing flow DOM. Replacing
// it would reset the active CSS flow animation on every progress update.
const eventDiagram = row.diagram.innerHTML;
manager.updateSignalProgress({ phase: 'event_replay', completed: 2, total: 4 });
assert.equal(row.fill.style.width, '50.00%');
assert.strictEqual(row.diagram.innerHTML, eventDiagram);

manager.recordActivity({
  phase: 'event_replay',
  flow_key: 'signal.flow',
  flow_label: '读取信号',
  timestamp: '2026-01-01 09:01:00',
});
assert(row.message.title.includes('读取信号') || row.message.title.includes('09:01:00'));

const activeEventDiagram = row.diagram.innerHTML;
manager.recordActivity({
  phase: 'event_replay',
  flow_key: 'signal.compose',
  flow_label: '合成Long-Short目标',
  timestamp: '2026-01-01 09:02:00',
});
assert.strictEqual(row.diagram.innerHTML, activeEventDiagram);

manager.markAllDone(true, '完成');
assert.equal(row.fill.style.width, '100%');
assert(!row.root.classList.contains('is-running'));
assert(!row.root.classList.contains('is-event-replaying'));

console.log('PASS: group progress manager renders converged flow line and running event animation');
