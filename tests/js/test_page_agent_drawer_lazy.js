const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tag) {
    this.tag = tag; this.children = []; this.dataset = {}; this.hidden = false;
    this.attributes = {}; this.listeners = {}; this.textContent = ""; this.className = "";
    this.classes = new Set();
    this.classList = {add: value => this.classes.add(value)};
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
global.FTPageAgentContext = {create: () => ({
  start: async () => events.push(["bridge"]),
  pause: () => events.push(["pause"]),
  resume: async () => events.push(["resume"]),
  dispose: () => {},
})};
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
    assistance: {prepare: async () => {
      events.push(["prepare"]);
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
  assert(events.some(item => item[0] === "prepare"));
  assert(events.some(item => item[0] === "open"));
  assert(events.some(item => item[0] === "bridge"));
  assert(events.some(item => item[0] === "chat"));
  drawer.hide();
  assert.equal(drawer.toggle.hidden, false, "the trigger returns after the drawer closes");
  assert(events.some(item => item[0] === "chat" && item[1] === true));
  assert(events.some(item => item[0] === "pause"));
  await drawer.open();
  assert(events.some(item => item[0] === "resume"));
  drawer.hide();
  const resumeCount = events.filter(item => item[0] === "resume").length;
  stateHooks.restore({open: true, profile_id: "self"});
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(drawer.shell.hidden, false,
    "restoring an assisted tab reopens a drawer that the user left open");
  assert.equal(drawer.toggle.hidden, true);
  assert(events.filter(item => item[0] === "resume").length > resumeCount,
    "a restored drawer resumes the existing conversation bridge");
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
    assistance: {prepare: async () => {}},
  });
  await new Promise(resolve => setTimeout(resolve, 0));
  assert(rebuiltHooks, "the rebuilt assisted page registers its drawer state");
  assert.equal(rebuilt.shell.hidden, false,
    "a performance-evicted assisted page reopens the drawer after rebuilding");
  assert.equal(rebuilt.toggle.hidden, true);
  console.log("PASS: page Agent drawer defers all work until it opens");
})().catch(error => { console.error(error); process.exitCode = 1; });
