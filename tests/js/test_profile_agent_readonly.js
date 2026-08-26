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
      "这是历史回答\n\n```bash\nfactortester products list\n```"
    ), annotations: []}],
    created_at: "2026-08-20T00:00:02+00:00",
  },
];
const processItems = [{
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
}];
const requestedURLs = [];

const context = {
  api: async url => {
    requestedURLs.push(url);
    if (!url.includes("conversation-items")) {
      return {conversations: [conversation]};
    }
    const process = url.includes("view=process");
    return {
      // The Provider/Profile directory keeps the default desc page efficient:
      // newest item first.  The ChatKit adapter must expose it chronologically.
      items: process ? processItems : [...items].reverse(),
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
    ["item-1", "item-2"],
  );
  assert.equal(
    thread.items.data[1].content[0].text,
    "这是历史回答\n\n```bash\nfactortester products list\n```",
  );
  assert.deepEqual(thread.items.data[1].content[0].annotations, []);
  assert.equal(thread.items.data[1].annotations, undefined);

  const page = await (await get({
    type: "items.list",
    params: {
      thread_id: conversation.conversation_id,
      limit: 7,
      after: "item-2",
    },
  })).json();
  assert.deepEqual(page.data.map(item => item.id), ["item-1", "item-2"]);
  assert.equal(page.has_more, true);
  assert.equal(page.after, "older-turn-cursor");
  assert.ok(requestedURLs.some(url => (
    url.includes("limit=7") && url.includes("after=item-1")
    && url.includes("view=results") && url.includes("order=desc")
  )));

  const getProcess = async body => adapter.fetchForView("process")(
    "/api/client/profile-agent/chatkit",
    {method: "POST", body: JSON.stringify(body)},
  );
  const processPage = await (await getProcess({
    type: "items.list",
    params: {thread_id: conversation.conversation_id, limit: 5},
  })).json();
  assert.deepEqual(processPage.data.map(item => item.id), ["process-1"]);
  assert.ok(requestedURLs.some(url => (
    url.includes("limit=5") && url.includes("view=process")
  )));
  const resultsAgain = await (await get({
    type: "items.list",
    params: {thread_id: conversation.conversation_id, limit: 5},
  })).json();
  assert.deepEqual(
    resultsAgain.data.map(item => item.id),
    ["item-1", "item-2"],
    "the process projection must not mutate the mounted results projection",
  );
  console.log("PASS: read-only Profile Agent history uses valid locked threads and stable item ids");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
