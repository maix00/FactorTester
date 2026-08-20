const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Node {
  constructor(tagName) {
    this.tagName = String(tagName).toUpperCase();
    this.children = [];
    this.dataset = {};
  }
  append(...items) { this.children.push(...items.filter(Boolean)); }
  replaceChildren(...items) { this.children = []; this.append(...items); }
  addEventListener() {}
  setAttribute() {}
  querySelector() { return null; }
}

global.document = {createElement: tag => new Node(tag)};
const scrollCalls = [];
global.window = {scrollTo: value => scrollCalls.push(value)};
global.requestAnimationFrame = callback => callback();
global.AbortController = class {
  constructor() { this.signal = {aborted: false}; }
  abort() { this.signal.aborted = true; }
};
global.FTUI = {
  empty: () => new Node("empty"),
  loading: () => new Node("loading"),
};
global.FTReportComponents = {
  renderBridgeGroup: () => new Node("bridge"),
  componentView: () => new Node("component"),
};
let lazyResets = 0;
global.FTReportLazyRuntime = {
  reset() { lazyResets += 1; },
};
let controls;
let railCleanups = 0;
global.FTReportChapterRail = {
  setup: (_rail, _roots, _context, value) => {
    controls = value;
    return {
      refresh() {},
      cleanup() { railCleanups += 1; },
    };
  },
};
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/report/tree.js", "utf8",
), {filename: "tree.js"});
global.FTReportTree = window.FTReportTree;
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/report/chapter-cache.js", "utf8"),
  {filename: "chapter-cache.js"},
);
global.FTReportChapterCache = window.FTReportChapterCache;
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/report/report-renderer.js", "utf8",
), {filename: "report-renderer.js"});

(async () => {
  const settle = async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  };
  const calls = [];
  const signals = [];
  const mount = new Node("mount");
  const rail = new Node("rail");
  const report = {
    chapters: ["a", "b", "c", "d"].map(id => ({component_id: id, title: id})),
    bindings: [],
  };
  window.FTReportRenderer.render(report, mount, {
    chapterRail: rail,
    suppressAutoScroll: true,
    t: value => value,
    loadChapter: async (id, options = {}) => {
      calls.push(id);
      signals.push(options.signal);
      return {components: [{component_id: id, parent_id: null, kind: "chapter", title: id}]};
    },
    selectedChapterID: "b",
    setSelectedChapter: id => { global.selectedChapterID = id; },
  });
  await settle();
  assert.deepEqual(calls, ["b"]);
  assert.equal(global.selectedChapterID, "b");
  assert.equal(signals[0].aborted, false);
  assert.equal(scrollCalls.length, 0, "suppressed renderer must not scroll after lazy chapter load");
  for (const id of ["a", "b", "c"]) {
    controls.activate(["a", "b", "c", "d"].indexOf(id));
    await settle();
  }
  assert.deepEqual(calls, ["b", "a", "c"]);
  controls.activate(2);
  await settle();
  assert.deepEqual(calls, ["b", "a", "c"], "recent chapters should be cached");
  controls.activate(3);
  await settle();
  assert.deepEqual(calls, ["b", "a", "c", "d"]);
  controls.activate(0);
  await settle();
  assert.deepEqual(calls, ["b", "a", "c", "d", "a"], "old chapters should be evicted by LRU");
  controls.activate(1);
  const abandonedSignal = signals.at(-1);
  controls.activate(2);
  assert.equal(abandonedSignal.aborted, true, "switching chapters aborts the previous request");
  assert.deepEqual(calls, ["b", "a", "c", "d", "a", "b"]);
  assert.ok(lazyResets >= 1, "chapter switches must release lazy observers");
  window.FTReportRenderer.render(report, mount, {
    chapterRail: rail,
    suppressAutoScroll: true,
    t: value => value,
    loadChapter: async id => ({
      components: [{component_id: id, parent_id: null, kind: "chapter", title: id}],
    }),
  });
  assert.equal(railCleanups, 1, "re-rendering must release the previous rail listeners");
  mount.__ftLazyCleanup();
  assert.equal(railCleanups, 2, "unmounting must release the active rail listeners");
  console.log("ok");
})();
