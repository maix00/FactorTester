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
      fetchForView: view => ({view}),
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
    api: async url => url.includes("profile-skills")
      ? {skills: []}
      : {status: {running: true}},
  };
  const root = await window.FTAgentChat.render(context, {
    profile_id: "profile-1",
    runtime: {runtime_kind: "server"},
    active_claim: true,
  });
  await flush();
  const buttons = findAll(root, item => item.tagName === "button");
  const resultsButton = buttons.find(item => item.textContent === "结果");
  const processButton = buttons.find(item => item.textContent === "过程");
  const initialChats = findAll(root, item => item.tagName === "openai-chatkit");
  assert.equal(initialChats.length, 1, "only results should mount initially");
  const resultsChat = initialChats[0];
  assert.equal(resultsChat.options.api.fetch.view, "results");
  resultsChat.dispatch("chatkit.thread.change", {threadId: "conversation-1"});

  processButton.click();
  await flush();
  const bothChats = findAll(root, item => item.tagName === "openai-chatkit");
  assert.equal(bothChats.length, 2, "process should mount lazily once");
  const processChat = bothChats.find(item => item !== resultsChat);
  const resultsSlot = findAll(
    root, item => item.dataset?.itemView === "results",
  )[0];
  const processSlot = findAll(
    root, item => item.dataset?.itemView === "process",
  )[0];
  assert.equal(processChat.options.api.fetch.view, "process");
  assert.equal(processChat.options.initialThread, "conversation-1");
  assert.equal(processChat.threadID, "conversation-1");
  assert.equal(resultsSlot.hidden, true);
  assert.equal(processSlot.hidden, false);

  resultsButton.click();
  assert.equal(resultsChat.threadID, "conversation-1");
  assert.equal(resultsSlot.hidden, false);
  assert.equal(processSlot.hidden, true);
  processButton.click();
  assert.equal(
    findAll(root, item => item.tagName === "openai-chatkit").length,
    2,
    "repeated switches must reuse both ChatKit elements",
  );
  assert.equal(
    findAll(root, item => item.tagName === "openai-chatkit")[0],
    resultsChat,
    "the results conversation DOM must keep its identity",
  );
  assert.equal(adapters.length, 1, "both projections must share one conversation adapter");
  console.log("PASS: Profile Agent switches projections without rebuilding ChatKit");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
