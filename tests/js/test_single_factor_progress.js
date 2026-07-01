const assert = require('assert');
const path = require('path');

global.window = global;
require(path.resolve(__dirname, '../../static/js/modules/single_factor_test/single_factor_progress.js'));

const progress = global.SingleFactorProgress;

assert(progress, 'SingleFactorProgress should be registered globally');

assert.deepEqual(
  progress.normalizeProgress(0, 0, '已有缓存，跳过'),
  { completed: 1, total: 1, terminal: true },
);
assert.deepEqual(
  progress.normalizeProgress(undefined, undefined, '数据准备完成'),
  { completed: 1, total: 1, terminal: true },
);
assert.deepEqual(
  progress.normalizeProgress(2, 5, '处理中'),
  { completed: 2, total: 5, terminal: false },
);

const phase = {
  completed: 0,
  total: 0,
  done: false,
  subSteps: {
    cached: { completed: 0, total: 0, done: false, message: '已有缓存，跳过' },
    loading: { completed: 2, total: 4, done: false },
    done: { completed: 3, total: 3, done: true },
  },
};

const cached = progress.normalizeProgress(0, 0, phase.subSteps.cached.message);
phase.subSteps.cached.completed = cached.completed;
phase.subSteps.cached.total = cached.total;
phase.subSteps.cached.done = cached.terminal;

assert.deepEqual(progress.aggregateSubSteps(phase.subSteps), { completed: 6, total: 8 });

progress.completePhaseRecord(phase);
assert.equal(phase.done, true);
assert.deepEqual(progress.aggregateSubSteps(phase.subSteps), { completed: 8, total: 8 });
assert.equal(phase.completed, 8);
assert.equal(phase.total, 8);

assert.equal(
  progress.computeLinearPct(['prepare', 'simulate'], {}, 'prepare', 1, 2, 0),
  25,
);
assert.equal(
  progress.computeLinearPct(['prepare', 'simulate'], {}, 'prepare', 1, 2, 30),
  30,
);

const wrapper = { style: { display: 'none' } };
const bar = { style: { width: '0%' } };
const text = { textContent: '' };
const runBtn = { disabled: false };
const simple = progress.createSimpleProgressController({
  resolve: () => ({ wrapper, bar, text, runBtn }),
});
simple.show('开始');
assert.equal(wrapper.style.display, 'flex');
assert.equal(runBtn.disabled, true);
assert.equal(text.textContent, '开始');
simple.setCount(2, 4, '节点');
assert.equal(bar.style.width, '50%');
assert.equal(text.textContent, '2/4 节点');
simple.done('完成', -1);
assert.equal(bar.style.width, '100%');
assert.equal(runBtn.disabled, false);
simple.fail('失败', 120, -1);
assert.equal(bar.style.width, '100%');
assert.equal(text.textContent, '失败');
assert.equal(wrapper.style.display, 'flex');

console.log('PASS: shared single factor progress semantics');
