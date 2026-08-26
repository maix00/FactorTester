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
          method: 'thread/tokenUsage/updated',
          params: {
            turnId: 'turn-1',
            tokenUsage: {
              modelContextWindow: 200000,
              last: {totalTokens: 12000},
              total: {totalTokens: 45000},
            },
          },
        },
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
          method: 'item/completed',
          params: {
            turnId: 'turn-1',
            item: {id: 'command-1', type: 'commandExecution'},
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
      // Codex may persist and emit the final item after turn/completed.  The
      // browser stream must remain attached during authoritative reconciliation.
      setTimeout(() => this.onmessage?.({
        lastEventId: String(events.length + 1),
        data: JSON.stringify({
          method: 'item/completed',
          params: {
            turnId: 'turn-1',
            item: {id: 'late-final', type: 'agentMessage', text: '第一句\n第二句'},
          },
        }),
      }), 5);
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
const rpcMethods = [];
let runtimeResumed = false;
let historyReads = 0;
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
        historyReads += 1;
        if (historyReads < 3) return {
          items: [{
            id: 'history-assistant-old',
            type: 'assistant_message',
            content: [{type: 'output_text', text: '旧回答不应覆盖', annotations: []}],
          }],
          has_more: false,
          after: null,
          order: 'desc',
        };
        return {
          items: [
            {
              id: 'history-assistant-1',
              type: 'assistant_message',
              content: [{type: 'output_text', text: '第一句\n第二句', annotations: []}],
            },
            {
              id: 'file-history-only',
              type: 'workflow',
              workflow: {type: 'custom', tasks: [{
                type: 'custom', title: 'updated report.py',
                content: '```diff\n+result\n```', status_indicator: 'complete',
              }]},
            },
            {
              id: 'command-1',
              type: 'workflow',
              workflow: {type: 'custom', tasks: [{
                type: 'custom', title: 'command',
                content: '```text\n98 products\n```', status_indicator: 'complete',
              }]},
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
      rpcMethods.push(body.method);
      if (body.method === 'turn/start') {
        if (!runtimeResumed) {
          throw new Error('thread must be resumed before turn/start');
        }
        return {success: true, response: {turn: {id: 'turn-1'}}};
      }
      if (body.method === 'thread/resume') {
        runtimeResumed = true;
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
  items: [{
    id: 'history-assistant-old',
    type: 'assistant_message',
    content: [{type: 'output_text', text: '旧回答不应覆盖', annotations: []}],
  }],
  source: null,
  turnID: '',
  assistant: null,
  active: false,
  threadPromise: null,
  restored: true,
  runtimeObserver: payload => {
    if (payload.method === 'thread/tokenUsage/updated') {
      global.__observedRuntime = true;
    }
  },
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
  assert.match(output, /98 products/);
  assert.match(output, /assistant_message\.content_part\.done/);
  assert.match(output, /thread\.item\.replaced/);
  assert.equal(global.__observedRuntime, true);
  assert.deepEqual(
    state.items.map(item => item.id),
    ['history-assistant-old', 'command-1', 'file-history-only', 'history-assistant-1'],
    'authoritative history is stored oldest-first after reconciliation',
  );
  assert.ok(requestedURLs.some(url => (
    url.includes('conversation-items') && url.includes('view=timeline')
  )));
  assert.equal(historyReads, 3, 'final history is retried until this turn is durable');
  assert.match(output, /"thread.item.added","item":\{"id":"file-history-only"/);
  assert.match(output, /"thread.item.done","item":\{"id":"file-history-only"/);
  assert.deepEqual(
    rpcMethods.slice(0, 2),
    ['thread/resume', 'turn/start'],
    'an existing Provider thread must be resumed in the current runtime session before writing',
  );
  console.log('PASS: missed Profile Agent SSE output is recovered from thread history');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
