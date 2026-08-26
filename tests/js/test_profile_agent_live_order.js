const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

global.window = {};
global.document = {documentElement: {lang: "zh-Hans"}};
global.navigator = {language: "zh-CN"};

for (const file of ["chatkit-protocol.js"]) {
  vm.runInThisContext(
    fs.readFileSync(
      path.resolve(__dirname, "../../server/manager/web/profile", file),
      "utf8",
    ),
    {filename: file},
  );
}

const requestedURLs = [];
let historyReads = 0;
const state = {
  profileID: "profile-main",
  conversationID: "conversation-1",
  context: {
    api: async url => {
      requestedURLs.push(url);
      historyReads += 1;
      if (historyReads === 1) return {
        // A transient thread/read snapshot can expose the newest user item
        // ahead of the final answer while the rollout index is settling.
        items: [
          {id: "user-old", type: "user_message"},
          {id: "assistant-new", type: "assistant_message"},
        ],
        has_more: true,
        after: "opaque-older-cursor",
        order: "desc",
      };
      return {
        items: [
          {id: "assistant-new", type: "assistant_message"},
          {id: "user-old", type: "user_message"},
        ],
        has_more: true,
        after: "opaque-older-cursor",
        order: "desc",
      };
    },
  },
  items: [],
  itemPage: null,
};

global.window.FTProfileChatKitConversations = {
  conversationIDFrom: params => String(params?.thread_id || "").trim(),
  profileStateFor: () => ({
    historyOnly: false,
    conversations: new Map(),
    context: state.context,
  }),
  getConversation: async () => state,
};
vm.runInThisContext(
  fs.readFileSync(
    path.resolve(__dirname, "../../server/manager/web/profile/chatkit-stream.js"),
    "utf8",
  ),
  {filename: "chatkit-stream.js"},
);
vm.runInThisContext(
  fs.readFileSync(
    path.resolve(__dirname, "../../server/manager/web/profile/chatkit-adapter.js"),
    "utf8",
  ),
  {filename: "chatkit-adapter.js"},
);

const adapter = window.FTProfileChatKit.create(
  {profile_id: state.profileID},
  state.context,
);

(async () => {
  const request = async body => adapter.fetch(
    "/api/client/profile-agent/chatkit",
    {method: "POST", body: JSON.stringify(body)},
  );
  const thread = await (await request({
    type: "threads.get_by_id",
    params: {thread_id: state.conversationID},
  })).json();
  assert.deepEqual(
    thread.items.data.map(item => item.id),
    ["user-old", "assistant-new"],
    "live history is rendered oldest-first",
  );
  assert.ok(historyReads >= 3, "refresh waits for two stable ordered snapshots");

  const page = await (await request({
    type: "items.list",
    params: {thread_id: state.conversationID, after: "assistant-new"},
  })).json();
  assert.deepEqual(page.data.map(item => item.id), ["user-old", "assistant-new"]);
  assert.ok(requestedURLs.some(url => url.includes("after=user-old")));
  console.log("PASS: live Profile Agent history is chronological and paginates older items");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
