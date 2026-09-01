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
  const buttons = findAll(root, item => item.tagName === "button");
  assert.equal(buttons.some(item => [
    "结果", "过程", "启动 Agent", "停止 Agent",
  ].includes(item.textContent)), false);
  const initialChats = findAll(root, item => item.tagName === "openai-chatkit");
  assert.equal(initialChats.length, 1, "one timeline uses one ChatKit element");
  assert.equal(initialChats[0].options.api.fetch, adapters[0].fetch);
  assert.equal(initialChats[0].options.initialThread, "conversation-live");
  initialChats[0].dispatch("chatkit.ready");
  await flush();
  assert.equal(
    initialChats[0].updateCount,
    1,
    "a remounted active conversation fetches process items produced while absent",
  );
  const activeComposer = findAll(root, item => item.tagName === "form")[0];
  const activeInput = findAll(activeComposer, item => item.tagName === "textarea")[0];
  const activeAction = findAll(activeComposer, item => item.tagName === "button")[0];
  initialChats[0].dispatch("chatkit.response.start");
  assert.equal(activeComposer.hidden, false);
  assert.equal(activeAction.attributes["aria-label"], "停止生成");
  activeInput.value = "补充约束";
  activeInput.dispatch("input");
  assert.equal(activeAction.attributes["aria-label"], "发送补充要求");
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
