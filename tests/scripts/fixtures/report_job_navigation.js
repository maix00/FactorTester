const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

global.window = {};
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/report/report-entry.js", "utf8",
), {filename: "report-entry.js"});

const navigated = [];
window.FTReferencePage = {
  routeFor: (kind, target, label, serverID) => (
    `/reference?kind=${kind}&target=${encodeURIComponent(target)}`
      + `&label=${encodeURIComponent(label)}&server_id=${serverID}`
  ),
};
const context = {
  state: {
    report: {
      bindings: [{
        target_ref: "job:remote-job",
        label: "远端测试任务",
        data: {server_id: "remote-main", port: 8000},
      }],
    },
    session: {username: "alice"},
  },
  t: value => value,
  navigate: path => navigated.push(path),
  showNotice: () => assert.fail("unexpected reference notice"),
};

window.FTReportEntry.openReference(
  "factortester://job/job%3Aremote-job", context,
);
assert.deepStrictEqual(navigated, [
  "/jobs/8000/remote-job?server_id=remote-main",
]);

navigated.length = 0;
window.FTReportEntry.openReference(
  "factortester://evidence/evidence%3Asha256%3Aabc", {
    ...context,
    state: {
      ...context.state,
      report: {
        bindings: [{
          target_ref: "evidence:sha256:abc",
          label: "终态证据",
          data: {server_id: "remote-main"},
        }],
      },
    },
  },
);
assert.deepStrictEqual(navigated, [
  "/reference?kind=evidence&target=evidence%3Asha256%3Aabc"
    + "&label=%E7%BB%88%E6%80%81%E8%AF%81%E6%8D%AE&server_id=remote-main",
]);
console.log("ok");
