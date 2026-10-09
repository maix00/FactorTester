const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

class FakeElement {
  constructor(tag = "div") {
    this.tagName = tag;
    this.children = [];
    this.attributes = {};
    this.listeners = {};
    this.className = "";
    this.value = "";
    this.style = {};
    this.classList = {add() {}, remove() {}, toggle() {}};
  }

  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = [...items]; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  addEventListener(name, callback) { this.listeners[name] = callback; }
}

global.document = {createElement: tag => new FakeElement(tag)};
global.window = {};
window.FTUI = {
  empty: () => new FakeElement("div"),
  loading: () => new FakeElement("div"),
  pagedTable: () => ({
    shell: new FakeElement("table"),
    body: {rows: []},
  }),
  refreshButton: (_context, onClick) => {
    const button = new FakeElement("button");
    button.refresh = onClick;
    return button;
  },
};
global.FTUI = window.FTUI;

class FakeIntersectionObserver {
  constructor(callback, options) {
    this.callback = callback;
    this.options = options;
    this.targets = new Set();
    this.disconnected = false;
    FakeIntersectionObserver.instances.push(this);
  }

  observe(target) { this.targets.add(target); }
  unobserve(target) { this.targets.delete(target); }
  disconnect() { this.targets.clear(); this.disconnected = true; }
  intersect(target) {
    if (this.targets.has(target)) {
      this.callback([{target, isIntersecting: true}]);
    }
  }
}
FakeIntersectionObserver.instances = [];
window.IntersectionObserver = FakeIntersectionObserver;

vm.runInThisContext(
  fs.readFileSync("server/manager/web/profile/profile-directory.js", "utf8"),
  {filename: "profile-directory.js"},
);

function contextFor(calls, tabID = "", apiHandler = null) {
  return {
    tabID,
    active: true,
    activeNav() {},
    setHeading() {},
    t: value => value,
    toolbar: new FakeElement("header"),
    content: new FakeElement("main"),
    isRouteCurrent() { return this.active; },
    api(path) {
      calls.push(path);
      if (apiHandler) return apiHandler(path);
      return Promise.resolve({
        items: [], page: 1, page_size: 20, total: 0,
      });
    },
  };
}

async function settle() {
  await new Promise(resolve => setImmediate(resolve));
}

async function main() {
  const calls = [];
  const context = contextFor(calls);
  await window.FTProfileDirectory.list(context);
  assert.strictEqual(calls.length, 0, "offscreen scopes must not load on mount");
  const observer = FakeIntersectionObserver.instances.at(-1);
  assert.strictEqual(observer.options.rootMargin, "0px");
  const roots = context.content.children[0].children;
  const byScope = scope => roots.find(root => root.className.includes(`profile-directory-${scope}`));

  observer.intersect(byScope("mine"));
  await settle();
  assert.deepStrictEqual(
    calls.map(path => new URL(path, "http://manager").searchParams.get("scope")),
    ["mine"],
  );

  const secondCalls = [];
  await window.FTProfileDirectory.list(contextFor(secondCalls, "second-tab"));
  const secondObserver = FakeIntersectionObserver.instances.at(-1);
  assert.strictEqual(observer.disconnected, false,
    "loading another tab must not disconnect this tab's observer");

  observer.intersect(byScope("subordinates"));
  await settle();
  observer.intersect(byScope("servers"));
  await settle();
  assert.deepStrictEqual(
    calls.map(path => new URL(path, "http://manager").searchParams.get("scope")),
    ["mine", "subordinates", "servers"],
  );
  assert.strictEqual(observer.disconnected, true);
  secondObserver.intersect(
    FakeIntersectionObserver.instances.at(-1).targets.values().next().value,
  );
  await settle();
  assert.strictEqual(secondCalls.length, 1,
    "each mounted tab retains its own lazy directory loader");

  const staleCalls = [];
  const staleRequests = [];
  const staleContext = contextFor(staleCalls, "stale-tab", () => new Promise(resolve => {
    staleRequests.push(resolve);
  }));
  await window.FTProfileDirectory.list(staleContext);
  const staleObserver = FakeIntersectionObserver.instances.at(-1);
  const staleMine = staleContext.content.children[0].children
    .find(root => root.className.includes("profile-directory-mine"));
  staleObserver.intersect(staleMine);
  assert.strictEqual(staleCalls.length, 1);
  staleContext.active = false;
  staleRequests.shift()({items: [], page: 1, page_size: 20, total: 0});
  await settle();
  assert.ok(staleObserver.targets.has(staleMine),
    "an inactive tab keeps its pending section observed for reactivation");
  staleContext.active = true;
  staleObserver.intersect(staleMine);
  assert.strictEqual(staleCalls.length, 2,
    "a stale completion can be retried when its tab becomes current");
  staleRequests.shift()({items: [], page: 1, page_size: 20, total: 0});
  await settle();
  assert.ok(!staleObserver.targets.has(staleMine));

  window.IntersectionObserver = undefined;
  const fallbackCalls = [];
  await window.FTProfileDirectory.list(contextFor(fallbackCalls));
  await settle();
  assert.strictEqual(fallbackCalls.length, 3, "older browsers retain eager fallback");
  console.log("ok");
}

main().catch(error => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
