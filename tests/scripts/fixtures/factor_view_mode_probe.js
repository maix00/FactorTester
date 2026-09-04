"use strict";

// Regression: rendering a factor view page mounts the shared mode-action
// "编辑" button when the session may edit the factor.  Catalog factor rows
// carry no can_edit flag — editability is owner-based (owner_username matches
// the session), so the old can_edit gate silently hid the button.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = globalThis;
global.structuredClone = global.structuredClone || (v => JSON.parse(JSON.stringify(v)));
const fakeNode = () => ({
  append() {}, replaceChildren() {}, appendChild() {}, addEventListener() {},
  removeEventListener() {}, classList: {add() {}, toggle() {}, remove() {}},
  setAttribute() {}, getAttribute: () => null, querySelector: () => null,
  querySelectorAll: () => [], style: {}, dataset: {}, children: [],
  hidden: false, className: "", textContent: "", title: "",
});
global.document = {
  createElement: () => fakeNode(),
  createDocumentFragment: () => fakeNode(),
  querySelector: () => null,
  querySelectorAll: () => [],
  body: fakeNode(),
  documentElement: fakeNode(),
};

function makeContext() {
  const toolbar = [];
  const navigated = [];
  const context = {
    t: value => value,
    session: {username: "alice"},
    toolbar: {append(...items) { toolbar.push(...items); }},
    button(label, handler) { return {textContent: label, onclick: handler}; },
    navigate(path) { navigated.push(path); },
    isRouteCurrent: () => true,
    updateActiveTab() {}, setHeading() {},
    content: {replaceChildren() {}},
    api: async () => ({}),
  };
  return {context, toolbar, navigated};
}

function factorRow(overrides = {}) {
  return {
    ref: "factor:v2:stored", alias: "Probe|N:5d",
    factor_alias: "Probe|N:5d", owner_username: "alice",
    factor_owner_ref: "profile:alice", owner_ref: "profile:alice",
    schema_version: 2,
    identity: {family_alias: "Probe", params: {N: "5d"}},
    ...overrides,
  };
}

window.FTUI = {
  actionButton(label, handler) { return {textContent: label, onclick: handler}; },
  table() { return {shell: fakeNode()}; },
  fieldRows() { return []; },
  loading() { return fakeNode(); },
  empty() { return fakeNode(); },
};
window.FTIcons = {node: () => fakeNode()};
window.FTFactorModel = {
  familyName: () => "Probe",
  withSourceMetadata: value => value,
  frozenFactorIdentity: () => null,
  factorExpression: () => "",
};
window.FTFactorDisplayEnrichment = {
  enrichFactorForDisplay: (_data, factor) => factor,
};
window.FTFactorDetailShared = {
  parameterValues: () => ({}),
  previewExpression: () => "",
  pageClass: () => "factor-page",
  summary: () => fakeNode(),
  provenance: () => null,
  parameterTable: () => null,
  helpIcon: () => fakeNode(),
  sourceUnavailableText: () => "",
  fieldHelp: () => null,
};
window.FTFactorObjectJobs = {
  create: () => ({mount: fakeNode(), root: fakeNode(), load: async () => {}}),
};
window.FTObjectDetailTabs = {
  create: () => ({root: fakeNode(), current: () => "overview", addEventListener() {}}),
};

vm.runInThisContext(
  fs.readFileSync(
    "server/manager/web/catalog/shared/object-mode-actions.js", "utf8",
  ),
  {filename: "object-mode-actions.js"},
);
vm.runInThisContext(
  fs.readFileSync("server/manager/web/catalog/factor-details.js", "utf8"),
  {filename: "factor-details.js"},
);

async function renderView(overrides) {
  const {context, toolbar, navigated} = makeContext();
  const data = {factors: [factorRow(overrides)], families: []};
  await window.FTFactorDetails.factorDetail(
    context, data, data.factors[0].ref, "view", async () => ({}),
  );
  return {context, toolbar, navigated};
}

(async () => {
  // Owner session sees the shared 编辑 action (no can_edit flag on rows).
  const owned = await renderView({});
  const labels = owned.toolbar.map(item => item.textContent || "");
  assert(labels.includes("查看因子序列"), "expected 查看因子序列");
  assert(labels.includes("编辑"), "owner must see the shared 编辑 action");
  const edit = owned.toolbar[labels.indexOf("编辑")];
  edit.onclick();
  assert.equal(owned.navigated[0], "/factors/factor/Probe%7CN%3A5d?mode=edit");

  // can_edit=true also grants the action even without an owner match.
  const flagged = await renderView({can_edit: true, owner_username: "other"});
  const flaggedLabels = flagged.toolbar.map(item => item.textContent || "");
  assert(flaggedLabels.includes("编辑"), "can_edit must grant the action");

  // A different user's factor stays read-only.
  const foreign = await renderView({owner_username: "bob"});
  const foreignLabels = foreign.toolbar.map(item => item.textContent || "");
  assert(!foreignLabels.includes("编辑"), "non-owner must not see 编辑");

  // Read-only overlay contexts never mount the action.
  const overlay = await (async () => {
    const {context, toolbar} = makeContext();
    context.testObjectViewOnly = true;
    const data = {factors: [factorRow({})], families: []};
    await window.FTFactorDetails.factorDetail(
      context, data, data.factors[0].ref, "view", async () => ({}),
    );
    return toolbar;
  })();
  const overlayLabels = overlay.map(item => item.textContent || "");
  assert(!overlayLabels.includes("编辑"), "view-only overlays hide 编辑");

  console.log("ok");
})().catch(error => {
  console.error("PROBE FAILED:", error && error.stack || error);
  process.exit(1);
});
