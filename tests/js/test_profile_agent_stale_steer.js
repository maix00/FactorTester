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

let oldStreamClosed = false;
window.FTProfileAgentEventSource = {open() {
  const source = {onopen: null, onmessage: null, onerror: null, close() {}};
  setTimeout(() => {
    source.onopen?.();
    source.onmessage?.({lastEventId: '21', data: JSON.stringify({
      method: 'item/completed',
      params: {
        turnId: 'turn-new',
        item: {id: 'assistant-new', type: 'agentMessage', text: 'OK'},
      },
    })});
    source.onmessage?.({lastEventId: '22', data: JSON.stringify({
      method: 'turn/completed',
      params: {turn: {id: 'turn-new', status: 'completed'}},
    })});
  }, 0);
  return source;
}};

const rpcMethods = [];
const chunks = [];
const state = {
  profileID: 'profile-main',
  conversationID: 'conversation-1',
  context: {api: async (url, init = {}) => {
    if (url.includes('/conversation-items?')) return {
      items: [], order: 'asc', has_more: false,
    };
    if (url.includes('/api/client/profile-agent?')) return {status: {
      event_sequence: 20,
      processing_conversation_id: 'conversation-1',
      processing_turn_id: 'turn-new',
      processing_event_after: 20,
    }};
    const body = JSON.parse(init.body || '{}');
    rpcMethods.push(body);
    return {success: true, response: {result: {
      accepted: 'turn/start',
      turn: {id: 'turn-new'},
      managerTransition: 'turn/start',
    }}};
  }},
  skills: [],
  conversation: {provider_thread_id: 'provider-thread-1'},
  threadID: 'provider-thread-1',
  threadTitle: '',
  cursor: 12,
  items: [],
  source: {close() {}},
  eventStream: {close() { oldStreamClosed = true; }},
  turnID: 'turn-old',
  assistant: {id: 'assistant-old', text: '旧回复'},
  active: true,
  streamGeneration: 1,
  threadPromise: null,
  restored: true,
};
const controller = {enqueue: value => chunks.push(Buffer.from(value).toString('utf8'))};

(async () => {
  await window.FTProfileChatKitStream.streamTurn(
    controller,
    state,
    {profileID: 'profile-main'},
    {input: '连通性测试：请只回复 OK'},
    new AbortController().signal,
    async () => {},
  );

  assert.equal(rpcMethods.length, 1);
  assert.equal(rpcMethods[0].method, 'turn/steer');
  assert.equal(oldStreamClosed, true, 'the stale event consumer is retired');
  assert.equal(state.active, false);
  assert.match(chunks.join(''), /连通性测试：请只回复 OK/);
  assert.match(chunks.join(''), /OK/);
  console.log('PASS: a stale steer promoted by the Manager owns the new turn stream');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
