const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

global.window = {};
global.document = {documentElement: {lang: 'zh-Hans'}};
global.navigator = {language: 'zh-Hans'};

const protocolSource = fs.readFileSync(
  path.resolve(__dirname, '../../server/manager/web/profile/chatkit-protocol.js'),
  'utf8',
);
vm.runInThisContext(protocolSource, {filename: 'chatkit-protocol.js'});
global.EventSource = class {
  constructor() {
    this.closed = false;
    global.__lastEventSource = this;
    queueMicrotask(() => {
      if (this.closed) return;
      this.onopen?.();
      const events = [
        {
          method: 'item/reasoning/textDelta',
          params: {turnId: 'turn-1', delta: 'PRIVATE_REASONING'},
        },
        {
          method: 'item/commandExecution/outputDelta',
          params: {turnId: 'turn-1', delta: 'TOOL_STDOUT'},
          chatkit_item: {
            id: 'command-1',
            type: 'workflow',
            workflow: {type: 'custom', tasks: [{
              type: 'custom', title: 'command', status_indicator: 'loading',
            }]},
          },
        },
        {
          method: 'item/agentMessage/delta',
          params: {turnId: 'turn-1', delta: '第一句'},
        },
        {
          method: 'item/agentMessage/delta',
          params: {turnId: 'turn-1', delta: '\n第二句'},
        },
        {
          method: 'item/completed',
          params: {
            turnId: 'turn-1',
            item: {id: 'history-assistant-1', type: 'agentMessage', text: '第一句\n第二句'},
          },
          chatkit_item: {
            id: 'command-1',
            type: 'workflow',
            workflow: {type: 'custom', tasks: [{
              type: 'custom', title: 'command', status_indicator: 'complete',
            }]},
          },
        },
        {
          method: 'turn/completed',
          params: {turn: {id: 'turn-1', status: 'completed', error: null}},
        },
      ];
      events.forEach((payload, index) => this.onmessage?.({
        lastEventId: String(index + 1),
        data: JSON.stringify(payload),
      }));
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
const requestedURLs = [];
const controller = {enqueue: value => chunks.push(Buffer.from(value).toString('utf8'))};
const state = {
  profileID: 'profile-main',
  conversationID: 'conversation-1',
  context: {
    api: async (url, init = {}) => {
      requestedURLs.push(url);
      if (url.includes('/api/client/profile-agent?')) {
        return {status: {event_sequence: 0}};
      }
      if (url.includes('/api/client/profile-agent/conversation-items?')) {
        return {
          items: [
            {
              id: 'history-assistant-1',
              type: 'assistant_message',
              content: [{type: 'output_text', text: '第一句\n第二句', annotations: []}],
            },
            {
              id: 'history-assistant-old',
              type: 'assistant_message',
              content: [{type: 'output_text', text: '旧回答不应覆盖', annotations: []}],
            },
          ],
          has_more: false,
          after: null,
          order: 'desc',
        };
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
                type: 'agentMessage',
                text: '第一句\n第二句',
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
  itemView: 'process',
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
  assert.match(output, /第一句/);
  assert.match(output, /第二句/);
  assert.doesNotMatch(output, /旧回答不应覆盖/);
  assert.doesNotMatch(output, /PRIVATE_REASONING/);
  assert.doesNotMatch(output, /TOOL_STDOUT/);
  assert.match(output, /assistant_message\.content_part\.done/);
  assert.match(output, /thread\.item\.replaced/);
  assert.ok(requestedURLs.some(url => (
    url.includes('conversation-items') && url.includes('view=results')
  )));
  console.log('PASS: missed Profile Agent SSE output is recovered from thread history');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
