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
    conversation_id: conversation.conversation_id,
    item_id: "item-1",
    role: "user",
    text: "请检查当前研究身份的状态",
    created_at: 1787125081,
  },
  {
    conversation_id: conversation.conversation_id,
    item_id: "item-2",
    role: "assistant",
    text: "这是历史回答\n\n```bash\nfactortester products list\n```",
    created_at: 1787125082,
  },
];

const context = {
  api: async url => url.includes("conversation-items")
    ? {items}
    : {conversations: [conversation]},
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
    params: {thread_id: conversation.conversation_id},
  })).json();
  assert.deepEqual(page.data.map(item => item.id), ["item-1", "item-2"]);
  console.log("PASS: read-only Profile Agent history uses valid locked threads and stable item ids");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
