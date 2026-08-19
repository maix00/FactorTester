const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const protocol = {
  randomID: prefix => `${prefix}-1`,
  assistantItem: (_state, text = '') => ({
    id: 'assistant-1',
    type: 'assistant_message',
    thread_id: 'conversation-1',
    created_at: new Date(0).toISOString(),
    content: [{type: 'output_text', text, annotations: []}],
  }),
  userItem: (_state, text) => ({
    id: 'user-1',
    type: 'user_message',
    thread_id: 'conversation-1',
    created_at: new Date(0).toISOString(),
    content: [{type: 'input_text', text}],
  }),
  extractInputText: params => String(params.input || '').trim(),
  responseValue: payload => payload.response?.result || payload.response || payload.result || payload,
  threadIDFrom: payload => String(
    payload.thread?.id || payload.turn?.id || payload.turnId || payload.id || '',
  ),
  historyTimestamp: (_value, fallback) => fallback,
  historyItems: (state, thread) => {
    const result = [];
    for (const turn of thread.turns || []) {
      for (const item of turn.items || []) {
        if (item.type === 'assistant_message') {
          result.push({
            id: item.id,
            type: 'assistant_message',
            thread_id: state.threadID,
            created_at: new Date(0).toISOString(),
            content: [{type: 'output_text', text: item.text, annotations: []}],
          });
        }
      }
    }
    return result;
  },
  threadObject: () => ({id: 'conversation-1'}),
  eventTurnID: payload => String(payload.params?.turnId || ''),
  rawMethod: payload => String(payload.method || payload.type || ''),
  rawDelta: () => '',
  completedText: () => '',
  turnCompletion: payload => ({status: String(payload.params?.status || ''), error: null}),
  terminalMethod: method => /turn[/:._-](completed|complete)/i.test(method),
  errorMessage: () => 'Agent error',
};

global.window = {FTProfileChatKitProtocol: protocol};
global.EventSource = class {
  constructor() {
    this.closed = false;
    global.__lastEventSource = this;
    queueMicrotask(() => {
      if (this.closed) return;
      this.onopen?.();
      this.onmessage?.({
        lastEventId: '1',
        data: JSON.stringify({
          method: 'turn/completed',
          params: {turnId: 'turn-1', status: 'completed'},
        }),
      });
    });
  }

  close() {
    this.closed = true;
  }
};

const source = fs.readFileSync(
  path.resolve(__dirname, '../../server/manager/web/profile/chatkit-stream.js'),
  'utf8',
);
vm.runInThisContext(source, {filename: 'chatkit-stream.js'});

const chunks = [];
const controller = {enqueue: value => chunks.push(Buffer.from(value).toString('utf8'))};
const state = {
  profileID: 'profile-main',
  conversationID: 'conversation-1',
  context: {
    api: async (url, init = {}) => {
      if (url.includes('/api/client/profile-agent?')) {
        return {status: {event_sequence: 0}};
      }
      const body = JSON.parse(init.body || '{}');
      if (body.method === 'turn/start') {
        return {success: true, response: {turn: {id: 'turn-1'}}};
      }
      if (body.method === 'thread/resume') {
        return {
          success: true,
          response: {
            thread: {
              id: 'provider-thread-1',
              turns: [{items: [{
                id: 'history-assistant-1',
                type: 'assistant_message',
                text: '98 个期货品种，2846 个合约路径',
              }]}],
            },
          },
        };
      }
      throw new Error(`unexpected API call: ${url} ${body.method || ''}`);
    },
  },
  skills: [],
  conversation: {provider_thread_id: 'provider-thread-1'},
  threadID: 'provider-thread-1',
  threadTitle: '',
  createdAt: new Date(0).toISOString(),
  cursor: 0,
  items: [],
  source: null,
  turnID: '',
  assistant: null,
  active: false,
  threadPromise: null,
  restored: true,
};

(async () => {
  await window.FTProfileChatKitStream.streamTurn(
    controller,
    state,
    {profileID: 'profile-main'},
    {input: '查询产品'},
    new AbortController().signal,
    async () => {},
  );
  const output = chunks.join('');
  assert.match(output, /98 个期货品种/);
  assert.match(output, /assistant_message\.content_part\.done/);
  console.log('PASS: missed Profile Agent SSE output is recovered from thread history');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
