const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tag) {
    this.tag = tag; this.children = []; this.dataset = {}; this.hidden = false;
    this.attributes = {}; this.listeners = {}; this.textContent = ""; this.className = "";
    this.classes = new Set();
    this.classList = {
      add: value => this.classes.add(value),
      remove: value => this.classes.delete(value),
    };
  }
  append(...values) { this.children.push(...values); }
  replaceChildren(...values) { this.children = values; }
  contains(value) { return this.children.includes(value); }
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
let resolveAssistance;
const assistancePromise = new Promise(resolve => { resolveAssistance = resolve; });
const events = [];
let stateHooks = null;
global.FTStaticLoader = {loadGroups: async names => events.push(["groups", names])};
global.FTAgentChat = {render: async (_context, _profile, options) => {
  const chat = new Element("chat");
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

const css = fs.readFileSync("server/manager/web/styles/app.css", "utf8");
const fixedHeight = css.indexOf(".profile-chatkit-host openai-chatkit { height: 600px; }");
const drawerHeight = css.indexOf(
  ".page-agent-drawer .profile-agent-chat-conversation-only openai-chatkit",
);
assert(fixedHeight >= 0 && drawerHeight > fixedHeight,
  "the drawer-specific fluid ChatKit height overrides fixed profile-page heights");

(async () => {
  const context = {
    tabID: "tab", t: value => value,
    pageState: {register: (_name, hooks) => { stateHooks = hooks; return {}; }},
    pageAgentLifecycle: {
      open: async profileID => {
        events.push(["open", profileID]);
        return {runtimeStatus: {running: true}};
      },
      hide: () => {},
    },
  };
  const drawer = FTPageAgentDrawer.attach(context, {
    resolveProfile: () => profilePromise,
    assistance: {connect: async () => {
      events.push(["bridge"]);
      await assistancePromise;
    }},
  });
  assert.equal(body.children.length, 2, "registration only mounts shell and trigger");
  assert.equal(events.length, 0, "registration performs no deferred work");
  stateHooks.restore({open: false, profile_id: "self"});
  await Promise.resolve();
  assert.equal(drawer.shell.hidden, true, "a previously closed drawer stays closed");
  assert.equal(drawer.toggle.hidden, false, "its floating trigger remains visible");
  assert.equal(events.length, 0, "restoring a closed drawer performs no Agent work");

  const opening = drawer.open();
  await Promise.resolve();
  assert.equal(drawer.toggle.hidden, true, "the trigger disappears while the drawer is open");
  assert.match(drawer.shell.children[1].children[0].textContent, /正在加载/);
  assert(events.some(item => item[0] === "groups"
    && item[1][0] === "profile-agent-chat"),
    "profile code starts loading only after the user opens the drawer");

  resolveProfile({profile_id: "self"});
  await new Promise(resolve => setTimeout(resolve, 0));
  assert(events.some(item => item[0] === "chat"),
    "ChatKit mounts without waiting for page-assistance code");
  resolveAssistance();
  await opening;
  assert(events.some(item => item[0] === "open"));
  assert(events.some(item => item[0] === "bridge"));
  assert(events.some(item => item[0] === "chat"));
  drawer.hide();
  assert.equal(drawer.toggle.hidden, false, "the trigger returns after the drawer closes");
  assert(events.some(item => item[0] === "chat" && item[1] === true));
  const title = drawer.shell.children[0].children[0];
  assert.equal(title.children[1].textContent, "self",
    "the active Profile is visible beside the assistant title");
  const bridgeStarts = events.filter(item => item[0] === "bridge").length;
  await drawer.open();
  assert.equal(events.filter(item => item[0] === "bridge").length, bridgeStarts,
    "reopening the drawer reuses its continuously active receiver");
  drawer.hide();
  stateHooks.restore({open: true, profile_id: "self"});
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(drawer.shell.hidden, false,
    "restoring an assisted tab reopens a drawer that the user left open");
  assert.equal(drawer.toggle.hidden, true);
  assert.equal(events.filter(item => item[0] === "bridge").length, bridgeStarts,
    "restoring the drawer does not create a duplicate receiver");
  const savedDrawerState = stateHooks.capture();
  assert.equal(savedDrawerState.open, true);
  stateHooks.dispose();
  let rebuiltHooks = null;
  const rebuiltContext = {
    ...context,
    pageState: {register: (_name, hooks) => {
      rebuiltHooks = hooks;
      hooks.restore(savedDrawerState);
      return {};
    }},
  };
  const rebuilt = FTPageAgentDrawer.attach(rebuiltContext, {
    resolveProfile: async () => ({profile_id: "self"}),
    assistance: {connect: async () => {}},
  });
  await new Promise(resolve => setTimeout(resolve, 0));
  assert(rebuiltHooks, "the rebuilt assisted page registers its drawer state");
  assert.equal(rebuilt.shell.hidden, false,
    "a performance-evicted assisted page reopens the drawer after rebuilding");
  assert.equal(rebuilt.toggle.hidden, true);
  const navigated = [];
  const switcher = FTPageAgentDrawer.attach({
    ...context,
    navigate: path => navigated.push(path),
    checkpointTabSession: () => {},
  }, {
    resolveProfile: async () => ({profile_id: "alpha", alias: "Alpha"}),
    resolveProfiles: async () => [
      {profile_id: "alpha", alias: "Alpha"},
      {profile_id: "beta", alias: "Beta"},
    ],
    onProfileChange: profile => events.push(["selected", profile.profile_id]),
    assistance: {connect: async () => {}, disconnect: () => {}},
  });
  await switcher.open();
  const switcherTitle = switcher.shell.children[0].children[0];
  const switcherProfile = switcherTitle.children[1];
  const switcherMenuButton = switcherTitle.children[2];
  const switcherMenu = switcherTitle.children[3];
  assert.equal(switcherProfile.textContent, "Alpha");
  switcherProfile.listeners.click();
  assert.match(navigated[0], /profile=alpha$/,
    "clicking the active Profile opens its detail page");
  switcherMenuButton.listeners.click();
  assert.equal(switcherMenu.hidden, false);
  switcherMenu.children[1].listeners.click();
  await new Promise(resolve => setTimeout(resolve, 0));
  assert(events.some(item => item[0] === "selected" && item[1] === "beta"));
  assert.equal(switcherProfile.textContent, "Beta",
    "selecting a bound Profile remounts the conversation under that Profile");
  console.log("PASS: page Agent drawer reuses its page-owned assistance receiver");
})().catch(error => { console.error(error); process.exitCode = 1; });
