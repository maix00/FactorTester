(() => {
  const P = window.FTProfileChatKitProtocol;

  function closeSource(state) {
    state.source?.close();
    state.source = null;
  }

  function writeEvent(controller, payload) {
    controller.enqueue(new TextEncoder().encode(
      `data: ${JSON.stringify(payload)}\n\n`,
    ));
  }

  function writeError(controller, error) {
    writeEvent(controller, {
      type: "error",
      code: "agent_request_failed",
      message: error?.message || String(error),
    });
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
    if (text.length >= current.length) assistant.text = text;
  }

  async function rpc(state, method, params) {
    const payload = await state.context.api("/api/client/profile-agent/rpc", {
      method: "POST",
      body: JSON.stringify({
        profile_id: state.profileID,
        conversation_id: state.conversationID,
        method,
        params,
      }),
    });
    if (payload?.success === false) {
      throw new Error(payload.error || "Profile Agent request failed");
    }
    return P.responseValue(payload);
  }

  function itemText(item) {
    const content = item?.content;
    if (Array.isArray(content)) {
      return content.map(part => typeof part === "string"
        ? part
        : String(part?.text || part?.value || "")).join("");
    }
    return String(item?.text || item?.message || item?.output_text || "");
  }

  function itemKey(item) {
    return `${String(item?.type || "").toLowerCase()}:${itemText(item)}`;
  }

  function isAssistantMessage(item) {
    const type = String(item?.type || "").replace(/[-_]/g, "").toLowerCase();
    return /^(agentmessage|assistantmessage|assistant|outputtext)$/.test(type);
  }

  function isConversationMessage(item) {
    const type = String(item?.type || "").replace(/[-_]/g, "").toLowerCase();
    return type === "usermessage" || isAssistantMessage(item);
  }

  function reconcileProcessItems(state, controller, history) {
    const liveByID = new Map(state.items.map(item => [String(item.id || ""), item]));
    for (const item of history) {
      if (isConversationMessage(item)) continue;
      const existing = liveByID.get(String(item.id || ""));
      if (!existing) {
        writeEvent(controller, {type: "thread.item.added", item});
        writeEvent(controller, {type: "thread.item.done", item});
      } else if (JSON.stringify(existing) !== JSON.stringify(item)) {
        writeEvent(controller, {type: "thread.item.replaced", item});
      }
    }
  }

  async function authoritativePage(state, params = {}) {
    const pageParams = P.itemPageParams(params);
    const view = "timeline";
    const query = new URLSearchParams({
      profile_id: state.profileID,
      conversation_id: state.conversationID,
      limit: String(pageParams.limit),
      view,
      order: pageParams.order,
    });
    const after = P.chronologicalPageAfter(
      state.itemPage, pageParams.after, view,
    );
    if (after) query.set("after", after);
    const payload = await state.context.api(
      `/api/client/profile-agent/conversation-items?${query}`,
    );
    const order = payload?.order || pageParams.order;
    return {
      // Provider pagination stays newest-first for efficient latest-page
      // reads.  ChatKit renders the returned page in the order it receives,
      // so its public adapter must always receive an oldest-to-newest page.
      items: P.chronologicalItems(payload?.items, order),
      has_more: Boolean(payload?.has_more),
      after: payload?.after || null,
      order,
      view,
    };
  }

  async function reconcileThreadHistory(state, controller, priorAssistantIDs) {
    // Reconcile the complete durable timeline so final answers never replace
    // the public progress, workflow, and tool records emitted during a turn.
    // A completed turn can precede the Provider's durable thread update by a
    // short interval, so retry this local latest-page read instead of closing
    // ChatKit before the final answer exists.
    const retryDelays = [0, 100, 200, 400, 800, 1200, 1800];
    let page = null;
    let assistant = null;
    for (const delay of retryDelays) {
      if (delay) await new Promise(resolve => setTimeout(resolve, delay));
      page = await authoritativePage(state);
      assistant = [...page.items].reverse().find(item => (
        isAssistantMessage(item)
        && Boolean(itemText(item))
        && !priorAssistantIDs.has(String(item.id || ""))
      ));
      if (assistant) break;
    }
    const history = page?.items || [];
    // SSE is the fast path.  If it missed a delta or the provider emits a
    // different event name, recover the authoritative text from the durable
    // provider thread before closing the browser stream.
    if (assistant) appendAssistantText(state, controller, itemText(assistant));
    reconcileProcessItems(state, controller, history);
    if (!assistant && state.assistant?.text) return state.items;
    state.items = history;
    state.itemPage = page;
    state.restored = true;
    if (!assistant && !state.assistant?.text) {
      throw new Error("Profile Agent final response is not yet available");
    }
    return history;
  }

  function syncThread(state, payload) {
    const value = P.responseValue(payload) || {};
    const thread = value.thread || value;
    const identifier = P.threadIDFrom(payload);
    if (!identifier) throw new Error("Profile Agent did not return a thread");
    state.threadID = identifier;
    state.threadTitle = String(
      thread.name || thread.title || state.threadTitle || "",
    ).trim();
    state.createdAt = P.historyTimestamp(
      thread.createdAt || thread.created_at,
      state.createdAt,
    );
    state.items = [];
    state.restored = true;
    state.conversation = {
      ...state.conversation,
      provider_thread_id: identifier,
      title: state.threadTitle,
    };
    return identifier;
  }

  async function restoreThread(state) {
    if (state.restored && state.threadID) return state.threadID;
    const providerThreadID = String(
      state.conversation?.provider_thread_id || state.threadID || "",
    ).trim();
    if (!providerThreadID) {
      if (state.conversation?.title || state.conversation?.preview) {
        throw new Error("Conversation Provider thread binding is missing");
      }
      return "";
    }
    if (!state.threadPromise) {
      state.threadPromise = authoritativePage(state).then(page => {
        state.threadID = providerThreadID;
        state.items = page.items;
        state.itemPage = page;
        state.restored = true;
        return providerThreadID;
      })
        .finally(() => { state.threadPromise = null; });
    }
    return state.threadPromise;
  }

  async function resumeThread(state) {
    const threadID = await restoreThread(state);
    if (!threadID) {
      throw new Error("Conversation has no Provider thread binding");
    }
    if (state.runtimeAttached) return threadID;
    if (!state.runtimePromise) {
      state.runtimePromise = rpc(state, "thread/resume", {
        threadId: threadID,
      }).then(payload => {
        const resumedID = P.threadIDFrom(payload);
        if (resumedID && resumedID !== threadID) {
          throw new Error("Profile Agent resumed a different Provider thread");
        }
        state.runtimeAttached = true;
        return threadID;
      }).finally(() => { state.runtimePromise = null; });
    }
    return state.runtimePromise;
  }

  async function ensureThread(state) {
    if (state.conversation?.provider_thread_id || state.threadID) {
      return resumeThread(state);
    }
    if (!state.threadPromise) {
      state.threadPromise = rpc(state, "thread/start", {}).then(payload => {
        const threadID = syncThread(state, payload);
        state.runtimeAttached = true;
        return threadID;
      }).finally(() => { state.threadPromise = null; });
    }
    return state.threadPromise;
  }

  async function alignEventCursor(state) {
    try {
      const payload = await state.context.api(
        `/api/client/profile-agent?profile_id=${encodeURIComponent(state.profileID)}`,
      );
      const sequence = Number(payload?.status?.event_sequence);
      if (Number.isFinite(sequence) && sequence >= 0) state.cursor = sequence;
    } catch (_) {
      // Keep the last known cursor.  The SSE connection still provides a
      // durable replay path when the status request is temporarily unavailable.
    }
  }

  function eventBelongsToCurrentTurn(state, payload) {
    const eventTurnID = P.eventTurnID(payload);
    if (!eventTurnID) return true;
    return !state.turnID || eventTurnID === state.turnID;
  }

  function openEventStream(state, controller, signal) {
    let resolveReady;
    let rejectReady;
    let resolveDone;
    const ready = new Promise((resolve, reject) => {
      resolveReady = resolve;
      rejectReady = reject;
    });
    const done = new Promise(resolve => { resolveDone = resolve; });
    if (signal.aborted) {
      resolveReady();
      resolveDone("aborted");
      return {ready, done, activate: () => {}, close: () => {}};
    }
    const url = `/api/client/profile-agent/events?profile_id=${
      encodeURIComponent(state.profileID)}&after=${state.cursor}`;
    const source = new EventSource(url);
    state.source = source;
    const pending = [];
    let settled = false;
    let opened = false;
    const finish = result => {
      if (settled) return;
      settled = true;
      source.close();
      if (state.source === source) state.source = null;
      signal.removeEventListener("abort", abort);
      resolveDone(result);
    };
    const abort = () => finish("aborted");
    signal.addEventListener("abort", abort, {once: true});
    source.onopen = () => {
      opened = true;
      resolveReady();
    };
    const processPayload = payload => {
      if (!eventBelongsToCurrentTurn(state, payload)) return;
      state.runtimeObserver?.(payload);
      const method = P.rawMethod(payload);
      const delta = P.agentMessageDelta(payload);
      const structuredItem = payload?.chatkit_item;
      if (structuredItem && ![
        "user_message", "assistant_message",
      ].includes(String(structuredItem.type || ""))) {
        const existingIndex = state.items.findIndex(
          item => item.id === structuredItem.id,
        );
        if (existingIndex < 0) {
          state.items.push(structuredItem);
          writeEvent(controller, {
            type: "thread.item.added", item: structuredItem,
          });
        } else if (/item[/:._-]completed/i.test(method)) {
          state.items[existingIndex] = structuredItem;
          writeEvent(controller, {
            type: "thread.item.replaced", item: structuredItem,
          });
        }
        if (/item[/:._-]completed/i.test(method)) {
          writeEvent(controller, {
            type: "thread.item.done", item: structuredItem,
          });
        }
      }
      if (method === "app_server_exit" || payload?.type === "app_server_exit") {
        if (state.assistant?.text) finish("done");
        else {
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
      if (delta) {
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
    source.onmessage = event => {
      if (event.lastEventId) state.cursor = Number(event.lastEventId) || state.cursor;
      let payload;
      try {
        payload = JSON.parse(event.data);
      } catch (_) {
        return;
      }
      if (!state.turnID) {
        pending.push(payload);
        return;
      }
      processPayload(payload);
    };
    source.onerror = () => {
      if (!opened) rejectReady(new Error("Profile Agent event stream unavailable"));
      finish("retry");
    };
    return {
      ready,
      done,
      activate: () => {
        for (const payload of pending.splice(0)) processPayload(payload);
      },
      close: () => finish("aborted"),
    };
  }

  async function streamTurn(
    controller,
    state,
    profileState,
    params,
    signal,
    updateConversation,
  ) {
    const text = P.extractInputText(params);
    if (!text) throw new Error("A non-empty text message is required");
    if (state.active) throw new Error("The Profile Agent is already processing a message");
    state.active = true;
    const hadThread = Boolean(state.threadID || state.conversation?.provider_thread_id);
    state.assistant = null;
    state.turnID = "";
    const priorAssistantIDs = new Set(state.items
      .filter(isAssistantMessage)
      .map(item => String(item.id || "")));
    try {
      await ensureThread(state);
      if (!hadThread) writeEvent(controller, {
        type: "thread.created", thread: P.threadObject(state),
      });
      const user = P.userItem(state, text);
      state.items.push(user);
      writeEvent(controller, {type: "thread.item.added", item: user});
      writeEvent(controller, {type: "thread.item.done", item: user});
      writeEvent(controller, {
        type: "stream_options", stream_options: {allow_cancel: true},
      });
      await alignEventCursor(state);
      let eventStream = openEventStream(state, controller, signal);
      await eventStream.ready.catch(() => {});
      const response = await rpc(state, "turn/start", {
        threadId: state.threadID,
        input: [{type: "text", text}],
        skill_ids: state.skills,
      });
      state.turnID = P.threadIDFrom(response) || state.turnID;
      eventStream.activate();
      let result = "retry";
      let retries = 0;
      while (result === "retry" && !signal.aborted && retries < 8) {
        result = await eventStream.done;
        retries += 1;
        if (result === "retry" && !signal.aborted) {
          eventStream = openEventStream(state, controller, signal);
          await eventStream.ready.catch(() => {});
        }
      }
      if (result === "retry" && !signal.aborted) {
        writeEvent(controller, {
          type: "error", code: "agent_events_timeout",
          message: "Agent event stream did not complete",
        });
      }
      if (!signal.aborted) {
        try {
          await reconcileThreadHistory(state, controller, priorAssistantIDs);
        } catch (error) {
          // Keep a successfully streamed response visible even if the
          // post-turn history reconciliation is temporarily unavailable.
          if (!state.assistant?.text) writeError(controller, error);
        }
      }
      if (state.assistant && !signal.aborted) {
        const item = P.assistantItem(state, state.assistant.text || "");
        if (!state.items.some(existing => itemKey(existing) === itemKey(item))) {
          state.items.push(item);
        }
        writeEvent(controller, {
          type: "assistant_message.content_part.done",
          content_index: 0, content: item.content[0],
        });
        writeEvent(controller, {type: "thread.item.done", item});
      }
      await updateConversation(profileState, state, {
        title: state.threadTitle || text.slice(0, 80),
        preview: text,
      }).catch(() => {});
    } finally {
      closeSource(state);
      state.active = false;
      state.assistant = null;
    }
  }

  window.FTProfileChatKitStream = Object.freeze({
    closeSource,
    authoritativePage,
    restoreThread,
    resumeThread,
    rpc,
    streamTurn,
    writeError,
  });
})();
