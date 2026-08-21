const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(
  fs.readFileSync(
    path.resolve(
      __dirname,
      "../../server/manager/web/profile/agent-runtime-controls.js",
    ),
    "utf8",
  ),
  {filename: "agent-runtime-controls.js"},
);

const runtime = window.FTProfileAgentRuntimeControls;
assert.deepEqual(runtime.contextUsage({
  last_tokens: 12000,
  total_tokens: 45000,
  model_context_window: 200000,
}), {
  used: 12000,
  total: 45000,
  capacity: 200000,
  percent: 6,
});
assert.deepEqual(runtime.runtimeEventPatch({
  method: "thread/tokenUsage/updated",
  params: {
    tokenUsage: {
      modelContextWindow: 200000,
      last: {totalTokens: 12000},
      total: {totalTokens: 45000},
    },
  },
}), {
  model_context_window: 200000,
  last_tokens: 12000,
  total_tokens: 45000,
});
assert.deepEqual(runtime.runtimeEventPatch({
  method: "model/rerouted",
  params: {toModel: "safe-model"},
}), {actual_model: "safe-model"});
assert.deepEqual(runtime.runtimeEventPatch({
  method: "thread/compacted",
}, {compaction_count: 2}), {compaction_count: 3});
assert.deepEqual(runtime.runtimeEventPatch({
  method: "item/completed",
  params: {item: {id: "compact-1", type: "contextCompaction"}},
}, {compaction_count: 3}), {compaction_count: 4});

class Element {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.listeners = {};
    this.textContent = "";
    this.value = "";
    this.disabled = false;
    this.hidden = false;
    this.dataset = {};
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = [...children]; }
  setAttribute() {}
  addEventListener(name, listener) { this.listeners[name] = listener; }
  dispatch(name) { this.listeners[name]?.({target: this}); }
  click() { this.listeners.click?.({target: this}); this.onclick?.({target: this}); }
}

function findByClass(root, className) {
  if (String(root.className || "").split(" ").includes(className)) return root;
  for (const child of root.children || []) {
    const found = findByClass(child, className);
    if (found) return found;
  }
  return null;
}

async function flush() {
  await Promise.resolve();
  await Promise.resolve();
  await new Promise(resolve => setImmediate(resolve));
}

global.document = {createElement: tagName => new Element(tagName)};

async function testSaveNoticeAndRollback() {
  let rejectSave = false;
  const writes = [];
  const context = {
    t: value => value,
    api: (url, init = {}) => {
      if (url.includes("/models?")) return Promise.resolve({
        models: [{
          id: "model-a",
          display_name: "Model A",
          reasoning_efforts: [{id: "high", description: "High"}],
          service_tiers: [{id: "fast", name: "Fast"}],
        }, {
          id: "model-b",
          display_name: "Model B",
          reasoning_efforts: [],
          service_tiers: [],
        }],
      });
      if (rejectSave) return Promise.reject(new Error("save rejected"));
      writes.push(JSON.parse(init.body || "{}"));
      return Promise.resolve({conversation: {
        model_id: "model-b", reasoning_effort: "", service_tier: "",
        actual_model: "",
      }});
    },
  };
  const component = runtime.create({profile_id: "profile-1"}, context);
  const conversation = {
    model_id: "model-a", reasoning_effort: "high", service_tier: "fast",
  };
  component.setConversation({conversationID: "conversation-1", conversation});
  assert.equal(component.element.tagName, "details");
  const selects = findByClass(component.element, "profile-agent-runtime-fields")
    .children.map(field => field.children[1]);
  selects[0].dispatch("focus");
  await flush();
  selects[0].value = "model-b";
  selects[0].dispatch("change");
  assert.equal(conversation.model_id, "model-a", "draft changes must not mutate persisted state");
  assert.equal(writes.length, 0, "draft changes must not auto-save");
  const apply = findByClass(component.element, "profile-agent-runtime-apply");
  apply.click();
  assert.equal(selects.every(select => select.disabled), true);
  await flush();
  const notice = findByClass(component.element, "profile-agent-runtime-notice");
  assert.equal(
    notice.textContent,
    "目录验证通过，设置已保存；将在下一次提问时确认实际模型",
  );
  assert.deepEqual(writes[0], {
    profile_id: "profile-1",
    conversation_id: "conversation-1",
    model_id: "model-b",
    reasoning_effort: "",
    service_tier: "",
    refresh_catalog: true,
  });
  assert.equal(selects.every(select => !select.disabled), true);

  rejectSave = true;
  selects[0].value = "model-a";
  selects[0].dispatch("change");
  apply.click();
  await flush();
  assert.match(notice.textContent, /会话模型设置保存失败: save rejected/);
  assert.equal(component.currentConversation().model_id, "model-b");
  assert.equal(selects[0].value, "model-b", "failed Apply must restore the persisted selection");
}

testSaveNoticeAndRollback().then(() => {
  console.log("PASS: Profile Agent model changes provide durable feedback");
}).catch(error => {
  console.error(error);
  process.exitCode = 1;
});

console.log("PASS: Profile Agent runtime metadata projection");
