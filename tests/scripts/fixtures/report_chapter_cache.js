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
global.window = {scrollTo() {}};
global.requestAnimationFrame = callback => callback();
global.FTUI = {
  empty: () => new Node("empty"),
  loading: () => new Node("loading"),
};
global.FTReportComponents = {
  renderBridgeGroup: () => new Node("bridge"),
  componentView: () => new Node("component"),
};
let controls;
global.FTReportChapterRail = {
  setup: (_rail, _roots, _context, value) => {
    controls = value;
    return {refresh() {}};
  },
};
vm.runInThisContext(fs.readFileSync(
  "scripts/worktree_manager_web/report/report-renderer.js", "utf8",
), {filename: "report-renderer.js"});

(async () => {
  const calls = [];
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
    loadChapter: async id => {
      calls.push(id);
      return {components: [{component_id: id, parent_id: null, kind: "chapter", title: id}]};
    },
  });
  await Promise.resolve();
  await Promise.resolve();
  assert.deepEqual(calls, ["d"]);
  for (const id of ["a", "b", "c"]) {
    controls.activate(["a", "b", "c", "d"].indexOf(id));
    await Promise.resolve();
    await Promise.resolve();
  }
  assert.deepEqual(calls, ["d", "a", "b", "c"]);
  controls.activate(2);
  await Promise.resolve();
  await Promise.resolve();
  assert.deepEqual(calls, ["d", "a", "b", "c"], "recent chapters should be cached");
  controls.activate(3);
  await Promise.resolve();
  await Promise.resolve();
  assert.deepEqual(calls, ["d", "a", "b", "c", "d"]);
  controls.activate(0);
  await Promise.resolve();
  await Promise.resolve();
  assert.deepEqual(calls, ["d", "a", "b", "c", "d", "a"], "old chapters should be evicted by LRU");
  console.log("ok");
})();
