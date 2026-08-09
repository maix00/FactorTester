const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(fs.readFileSync(
  "scripts/worktree_manager_web/research/workspaces.js", "utf8",
), {filename: "workspaces.js"});

const local = new Map([
  ["owned-report", {local_ref: "record:[[branch]]"}],
]);
const owned = window.FTResearch.resolvePublicationSource({
  report_id: "owned-report",
  is_owned: true,
  href: "/research/publication-1",
}, local, true);
assert.equal(owned.local_source, true);
assert.equal(owned.href, "/research/local%3Arecord%3A%5B%5Bbranch%5D%5D");

const otherOwner = window.FTResearch.resolvePublicationSource({
  report_id: "owned-report",
  is_owned: false,
  href: "/research/publication-1",
}, local, true);
assert.equal(otherOwner.local_source, undefined);
assert.equal(otherOwner.href, "/research/publication-1");

const notEmbedded = window.FTResearch.resolvePublicationSource({
  report_id: "owned-report",
  is_owned: true,
  href: "/research/publication-1",
}, local, false);
assert.equal(notEmbedded.local_source, undefined);

const missingLocal = window.FTResearch.resolvePublicationSource({
  report_id: "missing-report",
  is_owned: true,
  href: "/research/publication-2",
}, local, true);
assert.equal(missingLocal.local_source, undefined);
assert.equal(missingLocal.href, "/research/publication-2");
console.log("ok");
