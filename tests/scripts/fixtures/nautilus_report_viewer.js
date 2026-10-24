const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const elements = [];
global.window = {};
global.document = {
  createTextNode(text) { return {textContent: text}; },
  createElement(tag) {
    const element = {
      tagName: tag.toUpperCase(),
      attributes: {}, style: {}, children: [],
      setAttribute(name, value) { this.attributes[name] = value; },
      append(...children) { this.children.push(...children); },
      replaceChildren(...children) { this.children = children; },
    };
    elements.push(element);
    return element;
  },
};
global.FTJobListFormat = {referenceURL: () => null};
const load = path => vm.runInThisContext(fs.readFileSync(path, "utf8"), {filename: path});
load("server/manager/web/jobs/artifacts.js");
global.FTJobArtifacts = window.FTJobArtifacts;
load("server/manager/web/jobs/job-artifact-viewers.js");
window.FTBacktestResultModel = {payloadNames: []};
load("server/manager/web/test-modules/backtest/results/view.js");

const context = {t: value => value};
const report = {name: "tearsheet.html", file_name: "tearsheet.html",
  content_type: "text/html", state: "active"};
const receipt = {name: "nautilus_receipt.json", file_name: "nautilus_receipt.json",
  content_type: "application/json", state: "active"};
const other = {name: "external.html", file_name: "external.html",
  content_type: "text/html", state: "active"};

assert.deepEqual(FTJobArtifacts.effectiveDeclarations([], [report], context), [],
  "an HTML upload without a native receipt is not automatically previewed");
const declarations = FTJobArtifacts.effectiveDeclarations([], [report, receipt, other], context);
assert.equal(declarations.length, 1);
assert.equal(declarations[0].viewer, "nautilus_tearsheet");
assert.deepEqual(declarations[0].artifacts, ["tearsheet.html"]);
assert.deepEqual(window.FTBacktestResults.relevantArtifacts([report, receipt, other]), [report]);
assert.deepEqual(window.FTBacktestResults.relevantArtifacts([report, other]), []);

const target = {children: [], replaceChildren(...children) { this.children = children; }};
let artifactFetches = 0;
FTJobArtifacts.fetch = async () => {
  artifactFetches += 1;
  return ({
  headers: {get: () => "text/html"},
  text: async () => "<!doctype html><html><body><script>Plotly.newPlot()</script></body></html>",
  });
};

(async () => {
  await window.FTJobArtifactViewers.mount(context, target, {
    jobID: "job-1", artifact: report, declaration: declarations[0],
    artifactQuery: "?server_id=local-1&evidence_ref=ev%3A1",
  });
  const frame = target.children[0];
  assert.equal(frame.tagName, "IFRAME");
  assert.equal(frame.attributes.sandbox, "allow-scripts");
  assert.equal(frame.attributes.referrerpolicy, "no-referrer");
  assert.equal(frame.src,
    "/api/jobs/job-1/artifacts/tearsheet.html?server_id=local-1&evidence_ref=ev%3A1&view=isolated");
  assert.equal(frame.srcdoc, undefined, "the report must not inherit the Manager shell CSP");
  assert.doesNotMatch(frame.attributes.sandbox, /allow-same-origin|allow-top-navigation/);
  assert.equal(artifactFetches, 0, "the report is not fetched into the Manager DOM");
  await window.FTJobArtifactViewers.mount(context, target, {
    jobID: "job-1", artifact: other,
    declaration: {viewer: ""},
  });
  assert.equal(target.children[0].tagName, "PRE",
    "other HTML remains text instead of executing in the Manager document");
  assert.equal(artifactFetches, 1);

  let createdTabs = [];
  let mounted = 0;
  window.FTBacktestResultModel.build = () => ({
    tabs: [], summary: {}, strategies: [], summaryRows: [],
  });
  window.FTBacktestResultModel.evaluationWindow = () => null;
  window.FTBacktestStrategySelection = {
    ALL_STRATEGIES: "all", normalize: () => ["all"],
    createScope: () => ({filterRows: rows => rows}),
  };
  global.FTJobResultTabs = {
    compose: ({tabs}) => tabs,
    active: tabs => tabs[0]?.key || "",
    create: (_, {tabs}) => {
      createdTabs = tabs;
      return {header: document.createElement("div")};
    },
  };
  window.FTJobResultTabs = FTJobResultTabs;
  window.FTRuntimeSummary = {rows: () => []};
  window.FTUI = {loading: () => document.createElement("span")};
  window.FTStaticLoader = {loadGroups: async () => {}};
  window.FTJobArtifactViewers.mount = async () => { mounted += 1; };
  const section = window.FTBacktestResults.section(context, {
    jobID: "job-1", artifacts: [report, receipt],
    resultSummary: {}, configuration: {}, resultDeclarations: [],
  });
  assert.equal(section.tagName, "SECTION");
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(createdTabs.map(item => item.key), ["nautilus_report"]);
  assert.equal(mounted, 1, "a report-only backtest opens the HTML report tab");
  console.log("nautilus report viewer contract passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
