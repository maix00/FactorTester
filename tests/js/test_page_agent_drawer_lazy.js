const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tag) {
    this.tag = tag; this.children = []; this.dataset = {}; this.hidden = false;
    this.attributes = {}; this.listeners = {}; this.textContent = ""; this.className = "";
    this.classList = {add: () => {}};
  }
  append(...values) { this.children.push(...values); }
  replaceChildren(...values) { this.children = values; }
  remove() { this.removed = true; }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  addEventListener(name, callback) { this.listeners[name] = callback; }
}

const body = new Element("body");
global.document = {body, createElement: tag => new Element(tag)};
global.window = globalThis;
global.FTIcons = {node: () => new Element("svg")};
let resolveProfile;
const profilePromise = new Promise(resolve => { resolveProfile = resolve; });
const events = [];
let stateHooks = null;
global.FTStaticLoader = {loadGroups: async names => events.push(["groups", names])};
global.FTPageAgentContext = {create: () => ({
  start: async () => events.push(["bridge"]), dispose: () => {},
})};
global.FTAgentChat = {render: async () => {
  events.push(["chat"]); return new Element("chat");
}};
vm.runInThisContext(
  fs.readFileSync("server/manager/web/profile/page-agent-drawer.js", "utf8"),
  {filename: "page-agent-drawer.js"},
);

(async () => {
  const context = {
    tabID: "tab", t: value => value,
    pageState: {register: (_name, hooks) => { stateHooks = hooks; return {}; }},
    pageAgentLifecycle: {
      open: async profileID => events.push(["open", profileID]), hide: () => {},
    },
  };
  const drawer = FTPageAgentDrawer.attach(context, {
    resolveProfile: () => profilePromise,
    assistance: {prepare: async () => events.push(["prepare"])},
  });
  assert.equal(body.children.length, 2, "registration only mounts shell and trigger");
  assert.equal(events.length, 0, "registration performs no deferred work");
  stateHooks.restore({open: true, profile_id: "self"});
  await Promise.resolve();
  assert.equal(drawer.shell.hidden, true, "restoring a page never reopens the drawer");
  assert.equal(events.length, 0, "page restoration performs no Agent work");

  const opening = drawer.open();
  await Promise.resolve();
  assert.equal(drawer.toggle.hidden, true, "the trigger disappears while the drawer is open");
  assert.match(drawer.shell.children[1].children[0].textContent, /正在加载/);
  assert.deepEqual(events, [
    ["groups", ["profile"]], ["prepare"],
  ], "expensive work starts only after the user opens the drawer");

  resolveProfile({profile_id: "self"});
  await opening;
  assert.deepEqual(events, [
    ["groups", ["profile"]], ["prepare"], ["open", "self"], ["bridge"], ["chat"],
  ]);
  drawer.hide();
  assert.equal(drawer.toggle.hidden, false, "the trigger returns after the drawer closes");
  assert.deepEqual(events.at(-1), ["chat"]);
  console.log("PASS: page Agent drawer defers all work until it opens");
})().catch(error => { console.error(error); process.exitCode = 1; });
