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
    this.hidden = false;
    this.disabled = false;
    this.textContent = "";
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = [...children]; }
  setAttribute() {}
  addEventListener(name, listener) { this.listeners[name] = listener; }
  dispatch(name, detail = {}) { this.listeners[name]?.({target: this, detail}); }
  click() { this.onclick?.({target: this}); }
  setOptions(options) { this.options = options; }
  setThreadId(threadID) { this.threadID = threadID; return Promise.resolve(); }
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

(async () => {
  const context = {
    t: value => value,
    calls: [],
    api: async function(url, init = {}) {
      this.calls.push({url, init});
      return url.includes("profile-skills")
        ? {skills: []}
        : {status: {running: false}};
    },
  };
  const root = await window.FTAgentChat.render(context, {
    profile_id: "profile-1",
    runtime: {runtime_kind: "server"},
    active_claim: true,
  });
  await flush();
  const buttons = findAll(root, item => item.tagName === "button");
  assert.equal(buttons.some(item => [
    "结果", "过程", "启动 Agent", "停止 Agent",
  ].includes(item.textContent)), false);
  const initialChats = findAll(root, item => item.tagName === "openai-chatkit");
  assert.equal(initialChats.length, 1, "one timeline uses one ChatKit element");
  assert.equal(initialChats[0].options.api.fetch, adapters[0].fetch);
  assert.equal(context.calls.filter(
    call => call.url === "/api/client/profile-agent/start",
  ).length, 1, "entering the tab starts the Agent exactly once");
  const lifecycleHost = findAll(
    root, item => item.dataset?.ftRerenderOnTabRestore === "true",
  )[0];
  lifecycleHost.__ftBeforeTabSave();
  await flush();
  assert.equal(context.calls.filter(
    call => call.url === "/api/client/profile-agent/stop",
  ).length, 1, "leaving the tab stops the Agent exactly once");
  console.log("PASS: Profile Agent uses one timeline and tab-scoped lifecycle");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
