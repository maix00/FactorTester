const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

global.window = {};
global.document = {documentElement: {lang: 'zh-Hans'}};
global.navigator = {language: 'zh-Hans'};

for (const filename of ['chatkit-protocol.js', 'chatkit-stream.js']) {
  vm.runInThisContext(fs.readFileSync(path.resolve(
    __dirname, `../../server/manager/web/profile/${filename}`,
  ), 'utf8'), {filename});
}

assert.equal(
  window.FTProfileChatKitProtocol.turnIDFrom({id: 1007, result: {accepted: true}}),
  '',
  'a JSON-RPC request id is not a Provider turn id',
);

const rpcMethods = [];
const chunks = [];
const existingSource = {closed: false, close() { this.closed = true; }};
const existingAssistant = {id: 'assistant-active', text: '正在处理'};
const state = {
  profileID: 'profile-main',
  conversationID: 'conversation-1',
  context: {api: async (url, init = {}) => {
    if (url.includes('/api/client/profile-agent?')) return {status: {
      event_sequence: 12,
      processing_conversation_id: 'conversation-1',
      processing_turn_id: 'turn-active',
    }};
    const body = JSON.parse(init.body || '{}');
    rpcMethods.push(body);
    return {success: true, response: {accepted: body.method}};
  }},
  skills: [],
  conversation: {provider_thread_id: 'provider-thread-1'},
  threadID: 'provider-thread-1',
  threadTitle: '',
  cursor: 11,
  items: [],
  source: existingSource,
  turnID: 'turn-active',
  assistant: existingAssistant,
  active: true,
  threadPromise: null,
  restored: true,
};
const controller = {enqueue: value => chunks.push(Buffer.from(value).toString('utf8'))};

(async () => {
  await assert.rejects(
    window.FTProfileChatKitStream.streamTurn(
      controller,
      state,
      {profileID: 'profile-main'},
      {input: '补充约束'},
      new AbortController().signal,
      async () => {},
    ),
    /already responding/,
  );

  assert.equal(rpcMethods.length, 1, 'stale-state recovery checks the atomic steer endpoint');
  assert.equal(rpcMethods[0].method, 'turn/steer');
  assert.equal(state.active, true, 'the authoritative turn remains active');
  assert.equal(state.turnID, 'turn-active');
  assert.equal(state.assistant, existingAssistant, 'the active response is not reset');
  assert.equal(state.source, existingSource, 'the active event stream is retained');
  assert.equal(existingSource.closed, false, 'steering does not close the event stream');
  assert.equal(state.items.length, 0);
  assert.equal(chunks.length, 0);
  console.log('PASS: live turns stay on ChatKit controls and reject unpromoted recovery');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
