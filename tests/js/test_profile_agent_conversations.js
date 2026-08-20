const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const values = new Map();
global.sessionStorage = {
  getItem: key => values.get(key) ?? null,
  setItem: (key, value) => values.set(key, String(value)),
  removeItem: key => values.delete(key),
};
global.window = {};
vm.runInThisContext(
  fs.readFileSync(
    path.resolve(__dirname, "../../server/manager/web/profile/chatkit-conversations.js"),
    "utf8",
  ),
  {filename: "chatkit-conversations.js"},
);

const conversations = [
  {
    conversation_id: "conversation-a",
    provider_thread_id: "provider-a",
    title: "A",
    active: true,
  },
  {
    conversation_id: "conversation-b",
    provider_thread_id: "provider-b",
    title: "B",
    active: false,
  },
];

async function main() {
  let calls = 0;
  let release;
  const context = {
    api: () => {
      calls += 1;
      if (calls > 1) return Promise.resolve({conversations});
      return new Promise(resolve => { release = resolve; });
    },
  };
  const profile = {profile_id: "maxc"};
  const state = window.FTProfileChatKitConversations.profileStateFor(
    profile, context, [],
  );
  let selected = "";
  state.onConversationChange = conversation => {
    selected = conversation.conversationID;
  };
  const first = window.FTProfileChatKitConversations.loadConversations(state);
  const second = window.FTProfileChatKitConversations.loadConversations(state);
  assert.equal(calls, 1, "concurrent history reads must share one request");
  release({conversations});
  await Promise.all([first, second]);
  assert.equal(state.selectedID, "conversation-a");
  assert.equal(selected, "conversation-a");

  await window.FTProfileChatKitConversations.getConversation(
    state, "conversation-b", false,
  );
  assert.equal(state.selectedID, "conversation-b");
  assert.equal(selected, "conversation-b");

  window.FTProfileChatKitConversations.dispose(state, () => {});
  const remounted = window.FTProfileChatKitConversations.profileStateFor(
    profile, context, [],
  );
  assert.equal(
    remounted.selectedID,
    "conversation-b",
    "selected conversation must survive ChatKit remounts",
  );
  console.log("PASS: Profile Agent history state survives remounts");
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
