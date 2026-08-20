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

const earlyFailure = view();
progress.updateProgress(earlyFailure, {
  event: "error", seq: 1, data: {status: "failed"},
});
assert.equal(earlyFailure.bar.value, 0, "an early failure must stop indeterminate animation");
progress.updateProgress(earlyFailure, {
  event: "progress", seq: 2, data: {completed: 1, total: 1},
});
assert.equal(earlyFailure.bar.value, 0, "terminal progress must be latched");

(async () => {
  let completions = 0;
  const context = {
    t: value => value,
    raw: async (_path, options) => ({
      body: {
        getReader: () => ({
          read: () => new Promise((_resolve, reject) => {
            options.signal.addEventListener("abort", () => {
              const error = new Error("aborted");
              error.name = "AbortError";
              reject(error);
            }, {once: true});
          }),
        }),
      },
    }),
  };
  const abandoned = view();
  const watching = progress.watchProgress(
    context, "job-abandoned", "", abandoned,
    {onComplete: () => { completions += 1; }},
  );
  await new Promise(resolve => setImmediate(resolve));
  progress.stopProgress();
  await watching;
  assert.equal(completions, 0, "navigation abort must not trigger an obsolete detail read");

  const terminalView = view();
  let terminalMeta = null;
  let reads = 0;
  const terminalContext = {
    t: value => value,
    raw: async () => ({
      body: {getReader: () => ({read: async () => {
        reads += 1;
        if (reads > 1) return {done: true};
        return {
          done: false,
          value: new TextEncoder().encode(
            "id: 9\nevent: result\ndata: {\"status\":\"succeeded\"}\n\n",
          ),
        };
      }})},
    }),
  };
  await progress.watchProgress(
    terminalContext, "job-terminal", "", terminalView,
    {onComplete: meta => { terminalMeta = meta; }},
  );
  assert.equal(terminalView.bar.value, 100);
  assert.equal(terminalMeta.terminal, true);

  const resumedView = view();
  resumedView.progressState = {
    lastSeq: 27, percent: 40, phaseIndex: new Map(), phaseCount: 0, terminal: false,
  };
  let resumedPath = "";
  await progress.watchProgress({
    t: value => value,
    raw: async path => {
      resumedPath = path;
      return {body: {getReader: () => ({read: async () => ({done: true})})}};
    },
  }, "job-resumed", "?server_id=remote-1", resumedView);
  assert.match(resumedPath, /server_id=remote-1&after=27$/);
  console.log("ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
