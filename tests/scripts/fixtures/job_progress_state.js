const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/jobs/progress.js", "utf8",
), {filename: "progress.js"});

function view() {
  const bar = {
    value: undefined,
    removeAttribute(name) { if (name === "value") this.value = undefined; },
  };
  return {bar, label: {textContent: ""}, progressState: null};
}

const progress = window.FTJobProgress;
const current = view();
progress.updateProgress(current, {
  event: "start", seq: 1,
  data: {phase: "prepare", phases: [{key: "prepare"}, {key: "run"}]},
});
progress.updateProgress(current, {
  event: "progress", seq: 2,
  data: {phase: "prepare", completed: 1, total: 1},
});
assert.equal(current.bar.value, 50);
progress.updateProgress(current, {
  event: "progress", seq: 3,
  data: {phase: "run", completed: 1, total: 4},
});
assert.equal(current.bar.value, 62.5);

// A delayed event and a heartbeat without measurable data cannot roll the bar back
// or return it to the browser's indeterminate animation.
progress.updateProgress(current, {
  event: "progress", seq: 2,
  data: {phase: "prepare", completed: 0, total: 1},
});
assert.equal(current.bar.value, 62.5);
progress.updateProgress(current, {event: "heartbeat", seq: 4, data: {status: "running"}});
assert.equal(current.bar.value, 62.5);

progress.updateProgress(current, {event: "result", seq: 5, data: {status: "succeeded"}});
assert.equal(current.bar.value, 100);
assert.equal(current.progressState.terminal, true);

const failed = view();
progress.updateProgress(failed, {
  event: "progress", seq: 1,
  data: {phase: "run", completed: 2, total: 4},
});
progress.updateProgress(failed, {event: "error", seq: 2, data: {status: "failed"}});
assert.equal(failed.bar.value, 50);
assert.equal(failed.progressState.terminal, true);

console.log("ok");
