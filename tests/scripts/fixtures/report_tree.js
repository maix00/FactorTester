const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

global.window = {};
vm.runInThisContext(
  fs.readFileSync("scripts/worktree_manager_web/report/tree.js", "utf8"),
  {filename: "tree.js"},
);

const {componentTree, chapterRoots} = window.FTReportTree;
const roots = componentTree([
  {component_id: "chapter", parent_id: null, kind: "chapter", title: "A"},
  {component_id: "section", parent_id: "chapter", kind: "section", title: "B"},
  {component_id: "body", parent_id: "section", kind: "body", title: "C"},
]);
assert.strictEqual(roots.length, 1);
assert.strictEqual(roots[0].children[0].children[0].component.title, "C");
assert.deepStrictEqual(chapterRoots({chapters: [
  {component_id: "chapter-2", title: "Latest", preview: "p"},
]}).map(item => item.component.title), ["Latest"]);
assert.deepStrictEqual(chapterRoots({components: [
  {component_id: "chapter", parent_id: null, kind: "chapter", title: "A"},
]}).map(item => item.component.title), ["A"]);
console.log("ok");
