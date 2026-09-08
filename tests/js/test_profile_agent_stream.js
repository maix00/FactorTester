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
  constructor(url) {
    this.closed = false;
    global.__lastEventSourceURL = url;
    global.__lastEventSource = this;
    queueMicrotask(() => {
      if (this.closed) return;
      this.onopen?.();
      const events = [
        {method: 'item/completed', params: {turnId: 'turn-1',
          item: {id: 'user-wire-1', type: 'message', role: 'user',
            content: [{type: 'input_text', text: 'USER_INPUT_MUST_NOT_BECOME_REPLY'}]}},
          chatkit_item: {id: 'user-wire-1', type: 'user_message'}},
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
          method: 'item/reasoning/summaryTextDelta',
          params: {
            turnId: 'turn-1', itemId: 'reasoning-1', summaryIndex: 0,
            delta: '正在核对可展示的过程信息',
          },
        },
        {
          method: 'item/commandExecution/outputDelta',
          params: {
            turnId: 'turn-1', itemId: 'command-1', delta: 'TOOL_STDOUT',
          },
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
        {
          type: 'app_server_exit',
          returncode: 0,
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
  path.resolve(__dirname, '../../server/manager/web/profile/chatkit-event-source.js'),
  'utf8',
);
vm.runInThisContext(source, {filename: 'chatkit-event-source.js'});

const streamSource = fs.readFileSync(
  path.resolve(__dirname, '../../server/manager/web/profile/chatkit-stream.js'),
  'utf8',
);
vm.runInThisContext(streamSource, {filename: 'chatkit-stream.js'});

const chunks = [];
const requestedURLs = [];
const rpcMethods = [];
let runtimeResumed = false;
let historyReads = 0;
let statusReads = 0;
const controller = {enqueue: value => chunks.push(Buffer.from(value).toString('utf8'))};
const state = {
  profileID: 'profile-main',
  conversationID: 'conversation-1',
  context: {
    api: async (url, init = {}) => {
      requestedURLs.push(url);
      if (url.includes('/api/client/profile-agent?')) {
        statusReads += 1;
        return {status: {
          event_sequence: statusReads === 1 ? 5 : 3,
          processing_conversation_id: statusReads > 1 ? 'conversation-1' : '',
          processing_event_after: statusReads > 1 ? 0 : undefined,
        }};
      }
      if (url.includes('/api/client/profile-agent/conversation-items?')) {
        historyReads += 1;
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
            {
              id: 'history-user-interrupted',
              type: 'user_message',
              content: [{type: 'input_text', text: '上一轮没有最终消息'}],
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
        return {success: true, response: {
          id: 1007,
          result: {accepted: true},
        }};
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
  cursor: 5,
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
  let authenticatedReads = 0;
  await new Promise((resolve, reject) => {
    const eventState = {context: {raw: async (_url, options) => {
      authenticatedReads += 1;
      assert.equal(options.headers.Accept, 'text/event-stream');
      return new Response(new ReadableStream({start(stream) {
        stream.enqueue(new TextEncoder().encode(
          'id: 9\ndata: {"method":"turn/completed"}\n\n',
        ));
      }}));
    }}};
    const source = window.FTProfileAgentEventSource.open(
      eventState,
      '/api/client/profile-agent/events?profile_id=profile-main&after=8',
    );
    source.onmessage = event => {
      try {
        assert.equal(event.lastEventId, '9');
        assert.equal(JSON.parse(event.data).method, 'turn/completed');
        source.close();
        resolve();
      } catch (error) { reject(error); }
    };
    source.onerror = reject;
  });
  assert.equal(authenticatedReads, 1, 'SSE uses the authenticated raw helper');
  await window.FTProfileChatKitStream.streamTurn(
    controller,
    state,
    {profileID: 'profile-main'},
    {input: '查询产品'},
    new AbortController().signal,
    async () => {},
  );
  const output = chunks.join('');
  assert.doesNotMatch(output, /USER_INPUT_MUST_NOT_BECOME_REPLY/);
  assert.notEqual(state.assistant?.id, 'user-wire-1');
  assert.match(output, /第一句/);
  assert.match(output, /第二句/);
  assert.doesNotMatch(output, /agent_process_exited|exited before producing/);
  assert.doesNotMatch(output, /旧回答不应覆盖/);
  assert.doesNotMatch(output, /PRIVATE_REASONING/);
  assert.match(output, /正在核对可展示的过程信息/);
  assert.match(output, /TOOL_STDOUT/);
  assert.match(output, /98 products/);
  assert.match(output, /assistant_message\.content_part\.done/);
  assert.match(
    global.__lastEventSourceURL,
    /after=0$/,
    'a restarted app-server turn uses its own authoritative event cursor',
  );
  assert.match(output, /thread\.item\.replaced/);
  assert.equal(global.__observedRuntime, true);
  assert.equal(
    state.turnID,
    'turn-1',
    'the first Provider event binds the turn when RPC only returned a request id',
  );
  assert.deepEqual(
    state.items.map(item => item.id),
    [
      'history-user-interrupted', 'history-assistant-old',
      'command-1', 'file-history-only', 'history-assistant-1',
    ],
    'authoritative history is stored oldest-first after reconciliation',
  );
  assert.deepEqual(
    window.FTProfileChatKitStream.turnRequest(state, {
      processing_conversation_id: 'conversation-1',
      processing_turn_id: 'turn-active',
    }, '补充要求'),
    {
      method: 'turn/steer',
      params: {
        threadId: 'provider-thread-1',
        turnId: 'turn-active',
        input: [{type: 'text', text: '补充要求'}],
      },
      turnID: 'turn-active',
    },
    'a new message steers the authoritative active turn after a remount',
  );
  assert.ok(requestedURLs.some(url => (
    url.includes('conversation-items') && url.includes('view=outline')
  )));
  assert.equal(historyReads, 1, 'a completed turn reconciles durable history once');
  assert.match(output, /"thread.item.added","item":\{"id":"file-history-only"/);
  assert.match(output, /"thread.item.done","item":\{"id":"file-history-only"/);
  const assistantAdded = chunks.findIndex(value => (
    value.includes('"type":"thread.item.added"')
    && value.includes('"type":"assistant_message"')
  ));
  const lastWorkflowDone = chunks.findLastIndex(value => (
    value.includes('"type":"thread.item.done"')
    && value.includes('"type":"workflow"')
  ));
  assert.ok(
    assistantAdded > lastWorkflowDone,
    'the final assistant item is created after every process item',
  );
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

for (const role of ['user', 'tool', 'system']) {
  assert.equal(window.FTProfileChatKitProtocol.completedText({params: {
    item: {type: 'message', role, content: 'never assistant output'},
  }}), '');
}
assert.equal(window.FTProfileChatKitProtocol.completedText({params: {
  item: {type: 'message', role: 'assistant', content: 'final answer'},
}}), 'final answer');
