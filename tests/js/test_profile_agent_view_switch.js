const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class Element {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.listeners = {};
    this.dataset = {};
    this.attributes = {};
    this.hidden = false;
    this.disabled = false;
    this.textContent = "";
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = [...children]; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  addEventListener(name, listener) { this.listeners[name] = listener; }
  dispatch(name, detail = {}) { this.listeners[name]?.({target: this, detail}); }
  click() { this.onclick?.({target: this}); }
  setOptions(options) { this.options = options; }
  setThreadId(threadID) { this.threadID = threadID; return Promise.resolve(); }
  fetchUpdates() { this.updateCount = (this.updateCount || 0) + 1; return Promise.resolve(); }
}

function findAll(root, predicate, values = []) {
  if (predicate(root)) values.push(root);
  for (const child of root.children || []) findAll(child, predicate, values);
  return values;
}

async function flush() {
  await Promise.resolve();
  await Promise.resolve();
  await new Promise(resolve => setImmediate(resolve));
}

global.window = {};
global.location = {origin: "http://test.local"};
let hostOptions;
window.FTXpertTransport = {create: (_adapter, options) => (hostOptions = options, ({key: "test", dispose() {}}))};
global.navigator = {language: "zh-CN"};
global.document = {
  documentElement: {lang: "zh-Hans"},
  createElement: tagName => new Element(tagName),
};
global.FTUI = {empty: (title, detail) => ({title, detail})};

const adapters = [];
window.FTProfileChatKit = {
  load: async () => {},
  create: () => {
    const adapter = {
      endpoint: "/chatkit",
      locale: "zh-CN",
      fetch: () => {},
      initialThread: "conversation-live",
      dispose() {},
    };
    adapters.push(adapter);
    return adapter;
  },
};
window.FTProfileAgentRuntimeControls = {
  create: () => ({
    element: new Element("details"),
    setConversation() {},
    observeEvent() {},
    dispose() {},
  }),
};

vm.runInThisContext(
  fs.readFileSync(
    path.resolve(__dirname, "../../server/manager/web/profile/agent-chat.js"),
    "utf8",
  ),
  {filename: "agent-chat.js"},
);

assert.equal(window.FTAgentChat.conversationModel({
  active_claim: {provider_model: "provider-default"},
}, {model_id: "conversation-model"}), "conversation-model",
"the conversation header follows the persisted conversation setting");
assert.equal(window.FTAgentChat.conversationModel({
  active_claim: {provider_model: "provider-default"},
}, {model_id: "conversation-model", actual_model: "runtime-model"}), "runtime-model",
"a runtime-confirmed model takes precedence in the conversation header");

(async () => {
  const context = {
    t: value => value,
    calls: [],
    api: async function(url, init = {}) {
      this.calls.push({url, init});
      return url.includes("profile-skills")
        ? {skills: []}
        : {status: {
          running: false,
          processing_conversation_id: "conversation-live",
        }};
    },
  };
  const root = await window.FTAgentChat.render(context, {
    profile_id: "profile-1",
    runtime: {runtime_kind: "server"},
    active_claim: true,
  });
  await flush();
  const identitySlot = new Element('div');
  hostOptions.mountControls('profile', identitySlot);
  assert.equal(identitySlot.children[0].children[0].tagName, 'strong', 'dedicated sessions keep a fixed Profile');
  const buttons = findAll(root, item => item.tagName === "button");
  assert.equal(buttons.some(item => [
    "结果", "过程", "启动 Agent", "停止 Agent",
  ].includes(item.textContent)), false);
  const initialChats = findAll(root, item => item.tagName === "xpertai-chatkit");
  assert.equal(initialChats.length, 1, "one timeline uses one ChatKit element");
  assert.equal(initialChats[0].options.api.apiUrl, "http://test.local/ft-profile-bridge/");
  assert.equal(initialChats[0].options.initialThread, "conversation-live");
  initialChats[0].dispatch("chatkit.ready");
  await flush();
  assert.equal(
    initialChats[0].updateCount || 0,
    0,
    "native thread load owns restoration; host must not start a competing fetch",
  );
  initialChats[0].dispatch("chatkit.ready");
  await flush();
  assert.equal(
    initialChats[0].updateCount || 0,
    0,
    "status polling does not repeatedly replace the ChatKit timeline and scroll anchor",
  );
  assert.equal(
    findAll(root, item => item.className === "profile-agent-active-composer").length,
    0,
    "active turns rely on ChatKit's native stop control without a second composer",
  );
  const lifecycleHost = findAll(
    root, item => item.dataset?.ftKeepConnectedOnTabSave === "true",
  )[0];
  assert.equal(context.calls.filter(
    call => call.url === "/api/client/profile-agent/start",
  ).length, 1, "entering the tab starts the Agent exactly once");
  lifecycleHost.__ftBeforeTabSave();
  await flush();
  assert.equal(context.calls.filter(
    call => call.url === "/api/client/profile-agent/stop",
  ).length, 0, "leaving the UI never stops an active Agent turn");
  console.log("PASS: Profile Agent uses one timeline and tab-scoped lifecycle");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
