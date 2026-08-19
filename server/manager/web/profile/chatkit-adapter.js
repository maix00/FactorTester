(() => {
  const P = window.FTProfileChatKitProtocol;
  const CHATKIT_SCRIPT =
    "https://cdn.platform.openai.com/deployments/chatkit/chatkit.js";
  const CHATKIT_ENDPOINT = "/api/client/profile-agent/chatkit";
  const states = new Map();
  let scriptLoad = null;

  function profileKey(profile) {
    return String(profile?.profile_id || "").trim();
  }

  function stateFor(profile, context, skills) {
    const key = profileKey(profile);
    let state = states.get(key);
    if (state) {
      state.context = context;
      state.skills = [...skills];
      return state;
    }
    state = {
      profileID: key,
      context,
      skills: [...skills],
      threadID: "",
      threadTitle: "",
      createdAt: new Date().toISOString(),
      cursor: 0,
      items: [],
      source: null,
      turnID: "",
      assistant: null,
      active: false,
      threadPromise: null,
    };
    states.set(key, state);
    return state;
  }

  async function load() {
    if (customElements.get("openai-chatkit")) return;
    if (!scriptLoad) {
      scriptLoad = new Promise((resolve, reject) => {
        const existing = document.querySelector(
          `script[src="${CHATKIT_SCRIPT}"]`,
        );
        if (existing) {
          existing.addEventListener("load", resolve, {once: true});
          existing.addEventListener("error", () => reject(
            new Error("ChatKit script failed to load"),
          ), {once: true});
          return;
        }
        const script = document.createElement("script");
        script.src = CHATKIT_SCRIPT;
        script.async = true;
        script.onload = resolve;
        script.onerror = () => reject(new Error("ChatKit script failed to load"));
        document.head.append(script);
      }).then(() => customElements.whenDefined("openai-chatkit"));
    }
    return scriptLoad;
  }

  function closeSource(state) {
    state.source?.close();
    state.source = null;
  }

  function writeEvent(controller, payload) {
    controller.enqueue(new TextEncoder().encode(
      `data: ${JSON.stringify(payload)}\n\n`,
    ));
  }

  function ensureAssistant(state, controller) {
    if (state.assistant) return state.assistant;
    state.assistant = {
      id: P.randomID("assistant"),
      created_at: new Date().toISOString(),
      text: "",
    };
    writeEvent(controller, {
      type: "thread.item.added",
      item: {...P.assistantItem(state), content: []},
    });
    writeEvent(controller, {
      type: "assistant_message.content_part.added",
      content_index: 0,
      content: {type: "output_text", text: "", annotations: []},
    });
    return state.assistant;
  }

  function appendAssistantText(state, controller, text) {
    if (!text) return;
    const assistant = ensureAssistant(state, controller);
    const current = assistant.text || "";
    if (text === current) return;
    if (text.startsWith(current)) {
      const delta = text.slice(current.length);
      assistant.text = text;
      if (delta) writeEvent(controller, {
        type: "assistant_message.content_part.text_delta",
        content_index: 0,
        delta,
      });
      return;
    }
    // A completed item is authoritative. If an upstream reconnect caused
    // non-prefix deltas, preserve the full text for thread.item.done rather
    // than duplicating an already rendered delta.
    if (text.length >= current.length) assistant.text = text;
  }

  async function rpc(state, method, params) {
    const payload = await state.context.api("/api/client/profile-agent/rpc", {
      method: "POST",
      body: JSON.stringify({profile_id: state.profileID, method, params}),
    });
    if (payload?.success === false) {
      throw new Error(payload.error || "Profile Agent request failed");
    }
    return P.responseValue(payload);
  }

  async function ensureThread(state) {
    if (state.threadID) return state.threadID;
    if (!state.threadPromise) {
      state.threadPromise = rpc(state, "thread/start", {}).then(payload => {
        const identifier = P.threadIDFrom(payload);
        if (!identifier) throw new Error("Profile Agent did not return a thread");
        state.threadID = identifier;
        const thread = P.responseValue(payload)?.thread;
        state.createdAt = thread?.created_at || state.createdAt;
        return identifier;
      }).finally(() => { state.threadPromise = null; });
    }
    return state.threadPromise;
  }

  function waitForEvents(state, controller, signal) {
    return new Promise(resolve => {
      if (signal.aborted) {
        resolve("aborted");
        return;
      }
      const url = `/api/client/profile-agent/events?profile_id=${
        encodeURIComponent(state.profileID)}&after=${state.cursor}`;
      const source = new EventSource(url);
      state.source = source;
      let settled = false;
      const finish = result => {
        if (settled) return;
        settled = true;
        source.close();
        if (state.source === source) state.source = null;
        signal.removeEventListener("abort", abort);
        resolve(result);
      };
      const abort = () => finish("aborted");
      signal.addEventListener("abort", abort, {once: true});
      source.onmessage = event => {
        if (event.lastEventId) state.cursor = Number(event.lastEventId) || state.cursor;
        let payload;
        try {
          payload = JSON.parse(event.data);
        } catch (_) {
          return;
        }
        const method = P.rawMethod(payload);
        const delta = P.rawDelta(payload);
        if (method === "app_server_exit" || payload?.type === "app_server_exit") {
          if (state.assistant?.text) {
            finish("done");
          } else {
            writeEvent(controller, {
              type: "error",
              code: "agent_process_exited",
              message: "Profile Agent exited before producing a response",
            });
            finish("error");
          }
          return;
        }
        if (payload?.error || /error/i.test(method) && !delta) {
          writeEvent(controller, {
            type: "error", code: "agent_error", message: P.errorMessage(payload),
          });
          finish("error");
          return;
        }
        const completed = P.completedText(payload);
        if (completed) appendAssistantText(state, controller, completed);
        if (delta && /(agent.?message|assistant|delta|content)/i.test(method)) {
          appendAssistantText(
            state,
            controller,
            `${state.assistant?.text || ""}${delta}`,
          );
        }
        if (/turn[/:._-](completed|complete|failed|error|aborted|interrupted)/i.test(method)) {
          const completion = P.turnCompletion(payload);
          if (completion.error || /failed|error|aborted|interrupted/i.test(completion.status)) {
            writeEvent(controller, {
              type: "error",
              code: "agent_turn_failed",
              message: P.errorMessage(completion.error || payload),
            });
            finish("error");
            return;
          }
          finish("done");
          return;
        }
        if (P.terminalMethod(method)) finish("done");
      };
      source.onerror = () => finish("retry");
    });
  }

  async function streamTurn(state, params, signal) {
    const text = P.extractInputText(params);
    if (!text) throw new Error("A non-empty text message is required");
    if (state.active) throw new Error("The Profile Agent is already processing a message");
    state.active = true;
    const wasNew = !state.threadID;
    state.assistant = null;
    state.turnID = "";
    try {
      await ensureThread(state);
      if (wasNew) writeEvent(this, {
        type: "thread.created", thread: P.threadObject(state),
      });
      const user = P.userItem(state, text);
      state.items.push(user);
      writeEvent(this, {type: "thread.item.added", item: user});
      writeEvent(this, {type: "thread.item.done", item: user});
      writeEvent(this, {
        type: "stream_options", stream_options: {allow_cancel: true},
      });
      const response = await rpc(state, "turn/start", {
        threadId: state.threadID,
        input: [{type: "text", text}],
        skill_ids: state.skills,
      });
      state.turnID = P.threadIDFrom(response);
      let result = "retry";
      let retries = 0;
      while (result === "retry" && !signal.aborted && retries < 8) {
        result = await waitForEvents(state, this, signal);
        retries += 1;
      }
      if (result === "retry" && !signal.aborted) {
        writeEvent(this, {
          type: "error", code: "agent_events_timeout",
          message: "Agent event stream did not complete",
        });
      }
      if (state.assistant && !signal.aborted) {
        const item = P.assistantItem(state, state.assistant.text || "");
        state.items.push(item);
        writeEvent(this, {
          type: "assistant_message.content_part.done",
          content_index: 0, content: item.content[0],
        });
        writeEvent(this, {type: "thread.item.done", item});
      }
    } finally {
      closeSource(state);
      state.active = false;
      state.assistant = null;
    }
  }

  function create(profile, context, options = {}) {
    const state = stateFor(profile, context, options.skills || []);
    const fetchAdapter = async (input, init = {}) => {
      const body = await P.parseBody(input, init);
      const op = P.operation(body);
      if (!op) return window.fetch(input, init);
      const params = body.params || body;
      if (op === "threads.list") {
        return P.jsonResponse(P.page(state.threadID ? [P.threadObject(state)] : []));
      }
      if (op === "threads.get_by_id") {
        return state.threadID && String(params.thread_id || params.threadId) === state.threadID
          ? P.jsonResponse(P.threadObject(state))
          : P.jsonResponse({error: "thread not found"}, 404);
      }
      if (op === "items.list") return P.jsonResponse(P.page(state.items));
      if (op === "threads.update") {
        state.threadTitle = String(params.title || "").trim();
        return P.jsonResponse(P.threadObject(state));
      }
      if (op === "threads.delete") {
        state.items = [];
        state.threadID = "";
        state.threadTitle = "";
        return P.jsonResponse({});
      }
      if (op === "threads.stop") {
        if (state.threadID && state.turnID) {
          await rpc(state, "turn/interrupt", {
            threadId: state.threadID, turnId: state.turnID,
          });
        }
        closeSource(state);
        return P.jsonResponse({});
      }
      if (op === "threads.create" || op === "threads.add_user_message") {
        const controller = new AbortController();
        if (init.signal) {
          if (init.signal.aborted) controller.abort();
          else init.signal.addEventListener("abort", () => controller.abort(), {once: true});
        }
        const stream = new ReadableStream({
          start: streamController => {
            streamTurn.call(streamController, state, params, controller.signal)
              .catch(error => {
                if (!controller.signal.aborted) writeEvent(streamController, {
                  type: "error", code: "agent_request_failed",
                  message: error.message || String(error),
                });
              })
              .finally(() => streamController.close());
          },
          cancel: () => { controller.abort(); closeSource(state); },
        });
        return new Response(stream, {
          headers: {
            "Content-Type": "text/event-stream; charset=utf-8",
            "Cache-Control": "no-store",
          },
        });
      }
      return P.jsonResponse({error: `Unsupported ChatKit operation: ${op}`}, 400);
    };
    return {
      fetch: fetchAdapter,
      endpoint: CHATKIT_ENDPOINT,
      locale: P.chatLocale(context),
      dispose() {
        closeSource(state);
        state.active = false;
      },
    };
  }

  window.FTProfileChatKit = Object.freeze({load, create});
})();
