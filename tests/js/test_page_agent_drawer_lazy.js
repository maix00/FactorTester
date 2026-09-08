const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tag) {
    this.tag = tag; this.children = []; this.dataset = {}; this.hidden = false;
    this.attributes = {}; this.listeners = {}; this.textContent = ""; this.className = "";
    this.style = {};
    this.classes = new Set();
    this.classList = {
      add: value => this.classes.add(value),
      remove: value => this.classes.delete(value),
    };
  }
  get isConnected() { return !this.removed; }
  append(...values) { this.children.push(...values); }
  replaceChildren(...values) { this.children = values; }
  contains(value) { return this.children.includes(value); }
  remove() { this.removed = true; }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  addEventListener(name, callback) { this.listeners[name] = callback; }
}

const body = new Element("body");
global.document = {
  body,
  createElement: tag => new Element(tag),
  querySelector: selector => selector === ".topbar"
    ? {getBoundingClientRect: () => ({bottom: 88})} : null,
};
global.window = globalThis;
const windowEvents = {};
global.innerHeight = 800;
global.addEventListener = (name, callback) => { windowEvents[name] = callback; };
const positions = new Map();
global.localStorage = {
  getItem: key => positions.get(key) ?? null,
  setItem: (key, value) => positions.set(key, String(value)),
};
global.FTIcons = {node: () => new Element("svg")};
let resolveProfile;
const profilePromise = new Promise(resolve => { resolveProfile = resolve; });
let resolveAssistance;
const assistancePromise = new Promise(resolve => { resolveAssistance = resolve; });
const events = [];
let stateHooks = null;
global.FTStaticLoader = {loadGroups: async names => events.push(["groups", names])};
global.FTAgentChat = {render: async (_context, _profile, options) => {
  const chat = new Element("chat");
  assert.equal(options.profileControl.tag, "select", "drawer places its authorized Profile selector inside ChatKit");
  assert(options.mountHost.classes.has("page-agent-drawer-body-conversation-only"));
  assert.deepEqual(options.runtimeStatus, {running: true},
    "the drawer reuses the lifecycle response instead of fetching Agent status again");
  options.mountHost.replaceChildren(chat);
  events.push(["chat", options.mountHost.contains(chat)]); return chat;
}};
vm.runInThisContext(
  fs.readFileSync("server/manager/web/profile/page-agent-drawer.js", "utf8"),
  {filename: "page-agent-drawer.js"},
);

(async () => {
  const hooks = [];
  const context = {tabID: "a", t: value => value,
    pageState: {register: (_name, value) => { hooks.push(value); }},
    pageAgentLifecycle: {open: async (id, owner) => {
      assert.equal(owner, "global-agent-drawer");
      events.push(["open", id]); return {runtimeStatus: {running: true}};
    }, hide() {}},
  };
  const options = {resolveProfile: () => profilePromise,
    resolveProfiles: async () => [{profile_id: "self"}],
    assistance: {connect: async () => {events.push(["bridge"]); await assistancePromise;}, disconnect() {}},
  };
  FTPageAgentDrawer.ensureGlobal(context);
  const drawer = FTPageAgentDrawer.attach(context, options);
  assert.equal(body.children.length, 2);
  assert.equal(drawer.shell.style.top, "96px");
  assert.equal(drawer.toggle.style.top, "124px");
  assert.equal(events.length, 0, "registration is lazy");
  const opening = drawer.open();
  resolveProfile({profile_id: "self"}); resolveAssistance(); await opening;
  assert.equal(events.filter(e => e[0] === "chat").length, 1);
  const chat = drawer.shell.children[0].children[0];
  const next = {...context, tabID: "b"};
  global.FTPageAgentProfiles = {forPage: async () => [], self: async () => ({profile_id: "self"})};
  FTPageAgentDrawer.activate(next);
  let nextDisconnects = 0;
  const same = FTPageAgentDrawer.attach(next, {resolveProfiles: async () => [], assistanceEnabled: false,
    assistance: {disconnect() {nextDisconnects += 1;}}});
  await Promise.resolve();
  assert.equal(same, drawer, "all tabs share the application drawer");
  assert.equal(drawer.shell.hidden, false, "tab changes retain open state");
  assert.equal(drawer.shell.children[0].children[0], chat, "tab changes never move or replace the chat iframe");
  const disconnectsBeforeClose = nextDisconnects;
  hooks[0].dispose();
  assert.equal(nextDisconnects, disconnectsBeforeClose, "closing an old page must not disconnect the new page receiver");
  assert.equal(drawer.shell.isConnected, true, "closing the originating tab cannot dispose the drawer");
  assert.equal(drawer.shell.dataset.ftPageAgentTab, undefined, "tab cache cannot park this shell");
  await drawer.open();
  assert.equal(events.filter(e => e[0] === "chat").length, 1, "reopening does not duplicate a stream");
  drawer.hide(); assert.equal(drawer.shell.hidden, true);
  FTPageAgentDrawer.activate(context); assert.equal(drawer.shell.hidden, true, "switching tabs cannot reopen a closed drawer");
  assert.equal(drawer.toggle.hidden, false);
  console.log("PASS: global lazy drawer survives tab changes and eviction");
})().catch(error => {console.error(error);process.exitCode = 1;});
