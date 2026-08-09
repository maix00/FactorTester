const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(fs.readFileSync(
  "scripts/worktree_manager_web/app/route-dispatch.js", "utf8",
), {filename: "route-dispatch.js"});

const calls = [];
let loggedIn = true;
const dispatch = window.FTAppRouteDispatch.create({
  content: {replaceChildren() {}},
  t: value => value,
  context: token => ({token}),
  jobsContext: token => ({token, kind: "jobs"}),
  requireLogin: () => {
    calls.push("auth");
    return !loggedIn;
  },
  handlers: {
    home: () => calls.push("home"),
    research: token => calls.push(`research:${token}`),
    jobs: context => calls.push(`jobs:${context.token}`),
    job: (context, port, id) => calls.push(`job:${context.token}:${port}:${id}`),
    reference: (context, route) => calls.push(
      `reference:${context.token}:${route.target}`,
    ),
  },
});

(async () => {
  await dispatch.render({kind: "home"}, 1);
  await dispatch.render({kind: "research"}, 2);
  await dispatch.render({kind: "reference", target: "evidence:1"}, 3);
  assert.deepEqual(calls, ["home", "research:2", "reference:3:evidence:1"]);

  loggedIn = false;
  await dispatch.render({kind: "jobs"}, 4);
  assert.equal(calls.at(-1), "jobs:4", "public server task feed must render without auth");
  await dispatch.render({kind: "job", port: 8141, id: "job-one"}, 5);
  assert.equal(calls.at(-1), "job:5:8141:job-one", "public job detail must render without auth");
  console.log("ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
