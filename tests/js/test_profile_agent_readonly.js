const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

global.window = {};
global.document = {documentElement: {lang: "zh-Hans"}};
global.navigator = {language: "zh-CN"};
global.sessionStorage = {getItem: () => "", setItem: () => {}, removeItem: () => {}};

for (const file of [
  "chatkit-protocol.js",
  "chatkit-adapter.js",
]) {
  vm.runInThisContext(
    fs.readFileSync(
      path.resolve(__dirname, "../../server/manager/web/profile", file),
      "utf8",
    ),
    {filename: file},
  );
}

const conversation = {
  conversation_id: "conversation-maxc",
  title: "MaxC history",
  created_at: 1787125080,
  active: true,
};
const items = [
  {
    id: "item-1",
    type: "user_message",
    thread_id: conversation.conversation_id,
    content: [{type: "input_text", text: "请检查当前研究身份的状态"}],
    attachments: [],
    quoted_text: null,
    inference_options: {},
    created_at: "2026-08-20T00:00:01+00:00",
  },
  {
    id: "item-2",
    type: "assistant_message",
    thread_id: conversation.conversation_id,
    content: [{type: "output_text", text: (
      "这是历史回答\n\n```bash\nfactortester product-library list\n```"
    ), annotations: []}],
    created_at: "2026-08-20T00:00:02+00:00",
  },
];
const processItem = {
  id: "process-1",
  type: "workflow",
  thread_id: conversation.conversation_id,
  workflow: {
    type: "reasoning",
    expanded: false,
    tasks: [{
      type: "thought",
      title: "Reasoning summary",
      content: "读取状态。",
      status_indicator: "complete",
    }],
  },
  created_at: "2026-08-20T00:00:01+00:00",
};
const requestedURLs = [];

const context = {
  api: async url => {
    requestedURLs.push(url);
    if (!url.includes("conversation-items")) {
      return {conversations: [conversation]};
    }
    return {
      // The Provider/Profile directory keeps the default desc page efficient:
      // newest item first.  The ChatKit adapter must expose it chronologically.
      items: [items[1], processItem, items[0]],
      has_more: true,
      after: "older-turn-cursor",
      order: "desc",
    };
  },
};
const adapter = window.FTProfileChatKit.create(
  {profile_id: "maxc"},
  context,
  {
    readOnly: true,
    profileKey: "remote-main::GTHT@MaxJJW@392452984564::maxc",
    profileScope: "subordinates",
  },
);

(async () => {
  const get = async body => adapter.fetch(
    "/api/client/profile-agent/chatkit",
    {method: "POST", body: JSON.stringify(body)},
  );
  const thread = await (await get({
    type: "threads.get_by_id",
    params: {thread_id: conversation.conversation_id},
  })).json();
  assert.equal(thread.status.type, "locked");
  assert.deepEqual(
    thread.items.data.map(item => item.id),
    ["item-1", "process-1", "item-2"],
  );
  assert.equal(
    thread.items.data[2].content[0].text,
    "这是历史回答\n\n```bash\nfactortester product-library list\n```",
  );
  assert.deepEqual(thread.items.data[2].content[0].annotations, []);
  assert.equal(thread.items.data[2].annotations, undefined);

  const page = await (await get({
    type: "items.list",
    params: {
      thread_id: conversation.conversation_id,
      limit: 7,
      after: "item-2",
    },
  })).json();
  assert.deepEqual(
    page.data.map(item => item.id),
    ["item-1", "process-1", "item-2"],
  );
  assert.equal(page.has_more, true);
  assert.equal(page.after, "older-turn-cursor");
  assert.ok(requestedURLs.some(url => (
    url.includes("limit=7") && url.includes("after=item-1")
    && url.includes("view=timeline") && url.includes("order=desc")
  )));
  console.log("PASS: read-only Profile Agent history retains the complete timeline");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
