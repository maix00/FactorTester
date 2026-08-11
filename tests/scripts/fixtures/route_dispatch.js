const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(fs.readFileSync(
  "scripts/worktree_manager_web/app/route-dispatch.js", "utf8",
), {filename: "route-dispatch.js"});

const calls = [];
let loggedIn = true;
const pageContext = token => ({
  token,
  activeNav: value => calls.push(`nav:${value}`),
  setHeading: value => calls.push(`heading:${value}`),
});
const dispatch = window.FTAppRouteDispatch.create({
  content: {replaceChildren() {}},
  t: value => value,
  context: pageContext,
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
    jobConfiguration: (context, port, id) => (
      calls.push(`job-config:${context.token}:${port}:${id}`)
    ),
    reference: (context, route) => calls.push(
      `reference:${context.token}:${route.target}`,
    ),
    factorSeries: (context, factorRef, groupRef) => calls.push(
      `factor-series:${context.token}:${factorRef}:${groupRef}`,
    ),
    factors: context => calls.push(`factors:${context.token}`),
    products: context => calls.push(`products:${context.token}`),
  },
});

(async () => {
  await dispatch.render({kind: "home"}, 1);
  await dispatch.render({kind: "research"}, 2);
  await dispatch.render({kind: "reference", target: "evidence:1"}, 3);
  assert.deepEqual(calls, ["home", "research:2", "reference:3:evidence:1"]);

  await dispatch.render({
    kind: "factor-series", factorRef: "factor:v1:roc", groupRef: "product-group:night",
  }, 4);
  assert.deepEqual(calls.slice(-4), [
    "nav:factors", "heading:因子序列", "auth",
    "factor-series:4:factor:v1:roc:product-group:night",
  ]);

  loggedIn = false;
  await dispatch.render({kind: "jobs"}, 5);
  assert.equal(calls.at(-1), "jobs:5", "public server task feed must render without auth");
  await dispatch.render({kind: "job", port: 8141, id: "job-one"}, 6);
  assert.equal(calls.at(-1), "job:6:8141:job-one", "public job detail must render without auth");
  await dispatch.render({kind: "job-configuration", port: 8141, id: "job-one"}, 7);
  assert.equal(
    calls.at(-1), "job-config:7:8141:job-one",
    "test configuration must use its own public detail page",
  );

  await dispatch.render({kind: "factors"}, 8);
  assert.deepEqual(
    calls.slice(-3),
    ["nav:factors", "heading:因子库", "auth"],
    "a protected route must establish its own shell before showing login",
  );
  await dispatch.render({kind: "products"}, 9);
  assert.deepEqual(
    calls.slice(-3),
    ["nav:products", "heading:产品", "auth"],
    "switching protected routes must not retain the previous page header",
  );
  console.log("ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
