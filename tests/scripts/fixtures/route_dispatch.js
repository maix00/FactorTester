const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/app/route-dispatch.js", "utf8",
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
    jobs: (context, section) => calls.push(`jobs:${context.token}:${section}`),
    job: (context, port, id) => calls.push(`job:${context.token}:${port}:${id}`),
    jobConfiguration: (context, port, id) => (
      calls.push(`job-config:${context.token}:${port}:${id}`)
    ),
    jobInput: (context, port, id, name) => (
      calls.push(`job-input:${context.token}:${port}:${id}:${name}`)
    ),
    reference: (context, route) => calls.push(
      `reference:${context.token}:${route.target}`,
    ),
    factorSeries: (context, factorRef, groupRef) => calls.push(
      `factor-series:${context.token}:${factorRef}:${groupRef}`,
    ),
    icTest: context => calls.push(`ic-test:${context.token}`),
    backtest: context => calls.push(`backtest:${context.token}`),
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
  assert.deepEqual(calls.slice(-3), [
    "nav:jobs", "heading:查看因子序列", "factor-series:4:factor:v1:roc:product-group:night",
  ]);

  loggedIn = false;
  await dispatch.render({kind: "jobs"}, 5);
  assert.equal(calls.at(-1), "jobs:5:types", "public test type page must render without auth");
  await dispatch.render({kind: "job", port: 8141, id: "job-one"}, 6);
  assert.equal(calls.at(-1), "job:6:8141:job-one", "public job detail must render without auth");
  await dispatch.render({kind: "job-configuration", port: 8141, id: "job-one"}, 7);
  assert.equal(
    calls.at(-1), "job-config:7:8141:job-one",
    "test configuration must use its own public detail page",
  );
  await dispatch.render({
    kind: "job-input", port: 8141, id: "job-one", inputName: "factor_source__Demo",
  }, 8);
  assert.equal(calls.at(-1), "job-input:8:8141:job-one:factor_source__Demo");

  await dispatch.render({kind: "factors"}, 9);
  assert.deepEqual(
    calls.slice(-3),
    ["nav:factors", "heading:因子库", "factors:9"],
    "public visitors must be able to browse the factor catalog",
  );
  await dispatch.render({kind: "products"}, 10);
  assert.deepEqual(
    calls.slice(-3),
    ["nav:products", "heading:产品库", "products:10"],
    "public visitors must be able to browse the product catalog",
  );
  await dispatch.render({kind: "ic-test"}, 11);
  assert.deepEqual(
    calls.slice(-3),
    ["nav:", "heading:IC 测试", "ic-test:11"],
    "visitor mode must render the IC workbench without an account session",
  );
  await dispatch.render({kind: "backtest"}, 12);
  assert.deepEqual(
    calls.slice(-3),
    ["nav:", "heading:回测", "backtest:12"],
    "visitor mode must render the backtest workbench without an account session",
  );
  console.log("ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
