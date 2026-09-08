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

  function ensureAssistant(state) {
    if (state.assistant) return state.assistant;
    state.assistant = {
      id: P.randomID("assistant"),
      created_at: new Date().toISOString(),
      text: "",
    };
    return state.assistant;
  }

  function appendAssistantText(state, text) {
    if (!text) return;
    const assistant = ensureAssistant(state);
    const current = assistant.text || "";
    if (text === current) return;
    if (text.startsWith(current)) {
      assistant.text = text;
      return;
    }
    if (text.length >= current.length) {
      assistant.text = text;
    }
  }

  function markFinalResponse(state) {
    state.finalResponseComplete = true;
  }

  function emitAssistant(state, controller) {
    if (!state.assistant?.text) return null;
    const item = P.assistantItem(state, state.assistant.text);
    writeEvent(controller, {
      type: "thread.item.added",
      item: {...item, content: []},
    });
    writeEvent(controller, {
      type: "assistant_message.content_part.added",
      content_index: 0,
      content: {type: "output_text", text: "", annotations: []},
    });
    writeEvent(controller, {
      type: "assistant_message.content_part.text_delta",
      content_index: 0,
      delta: state.assistant.text,
    });
    writeEvent(controller, {
      type: "assistant_message.content_part.done",
      content_index: 0,
      content: item.content[0],
    });
    writeEvent(controller, {type: "thread.item.done", item});
    return item;
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

  function processItem(state, itemID) {
    return state.items.find(item => String(item?.id || "") === itemID);
  }

  function liveProcessItem(state, itemID, title, workflowType = "custom") {
    const existing = processItem(state, itemID);
    if (existing?.type === "workflow") return structuredClone(existing);
    return {
      id: itemID,
      thread_id: state.conversationID,
      created_at: new Date().toISOString(),
      type: "workflow",
      workflow: {
        type: workflowType,
        tasks: [{
          type: workflowType === "reasoning" ? "thought" : "custom",
          title,
          content: null,
          status_indicator: "loading",
        }],
        summary: {title},
        expanded: false,
      },
    };
  }

  function emitProcessReplacement(state, controller, item) {
    const index = state.items.findIndex(existing => existing.id === item.id);
    if (index < 0) {
      state.items.push(item);
      writeEvent(controller, {type: "thread.item.added", item});
      return;
    }
    state.items[index] = item;
    writeEvent(controller, {type: "thread.item.replaced", item});
  }

  function appendDisplayableProcessDelta(state, controller, payload) {
    const method = P.rawMethod(payload);
    const params = payload?.params || {};
    const delta = typeof params.delta === "string" ? params.delta : "";
    const providerItemID = String(params.itemId || params.item_id || "").trim();
    if (!delta || !providerItemID) return;

    let itemID;
    let title;
    let workflowType = "custom";
    let fence = "";
    if (method === "item/reasoning/summaryTextDelta") {
      itemID = providerItemID;
      title = "Reasoning summary";
      workflowType = "reasoning";
    } else if (method === "item/commandExecution/outputDelta") {
      itemID = providerItemID;
      title = "Command output";
      fence = "text";
    } else if (method === "item/fileChange/outputDelta") {
      itemID = providerItemID;
      title = "File changes";
      fence = "diff";
    } else if (method === "item/plan/delta") {
      itemID = providerItemID;
      title = "Plan";
    } else {
      return;
    }

    state.processDeltaText ||= new Map();
    const key = `${method}:${providerItemID}:${params.summaryIndex ?? ""}`;
    const text = `${state.processDeltaText.get(key) || ""}${delta}`;
    state.processDeltaText.set(key, text);
    const item = liveProcessItem(state, itemID, title, workflowType);
    const taskIndex = workflowType === "reasoning"
      ? Math.max(0, Number(params.summaryIndex) || 0) : 0;
    while (item.workflow.tasks.length <= taskIndex) {
      item.workflow.tasks.push({
        type: "thought",
        title: `Reasoning summary ${item.workflow.tasks.length + 1}`,
        content: null,
        status_indicator: "loading",
      });
    }
    const task = item.workflow.tasks[taskIndex];
    task.content = fence ? `\`\`\`${fence}\n${text}\n\`\`\`` : text;
    emitProcessReplacement(state, controller, item);
  }

  function emitTurnOutcome(state, controller, status, payload) {
    const interrupted = /aborted|interrupted/i.test(status);
    const itemID = `${state.turnID || P.randomID("turn")}-outcome`;
    const item = liveProcessItem(
      state,
      itemID,
      interrupted ? "Agent turn interrupted" : "Agent turn failed",
    );
    const task = item.workflow.tasks[0];
    task.content = interrupted
      ? "The Agent stopped before producing a final response. You can continue the conversation with a new message."
      : P.errorMessage(payload);
    task.status_indicator = "complete";
    emitProcessReplacement(state, controller, item);
    writeEvent(controller, {type: "thread.item.done", item});
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
    const view = params.view || "outline";
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

  async function stableAuthoritativePage(state) {
    // The Manager timeline endpoint is the ordering authority.  Re-reading it
    // until two snapshots match made every conversation open perform several
    // serial thread/read calls and delayed long conversations by seconds.
    return authoritativePage(state);
  }

  async function reconcileThreadHistory(
    state, controller, priorAssistantIDs, signal,
  ) {
    // SSE is the live authority.  Read durable history once to reconcile IDs
    // and process records; an interrupted turn without a final assistant item
    // remains a valid incomplete turn and must never block the next message.
    if (signal?.aborted) return state.items;
    const page = await authoritativePage(state);
    const assistantIndex = page.items.findLastIndex(item => (
      isAssistantMessage(item)
      && Boolean(itemText(item))
      && !priorAssistantIDs.has(String(item.id || ""))
    ));
    const latestUserIndex = page.items.findLastIndex(item => (
      String(item?.type || "").replace(/[-_]/g, "").toLowerCase()
      === "usermessage"
    ));
    const assistant = assistantIndex > latestUserIndex
      ? page.items[assistantIndex]
      : null;
    const history = page?.items || [];
    // SSE is the fast path.  If it missed a delta or the provider emits a
    // different event name, recover the authoritative text from the durable
    // provider thread before closing the browser stream.
    reconcileProcessItems(state, controller, history);
    // Process records must be committed before the final answer.  Otherwise
    // a delayed history reconciliation briefly places the answer above the
    // commands that produced it until the next full refresh.
    if (assistant) {
      appendAssistantText(state, itemText(assistant));
      const temporaryID = state.assistant.id;
      state.assistant.id = assistant.id;
      state.assistant.created_at = assistant.created_at;
      if (temporaryID !== assistant.id) writeEvent(controller, {
        type: "thread.item.removed", item_id: temporaryID,
      });
    }
    if (!assistant && state.finalResponseComplete && state.assistant?.text) {
      return state.items;
    }
    state.items = history;
    state.itemPage = page;
    state.restored = true;
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
      state.threadPromise = stableAuthoritativePage(state).then(page => {
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

  async function runtimeStatus(state) {
    try {
      const payload = await state.context.api(
        `/api/client/profile-agent?profile_id=${encodeURIComponent(state.profileID)}`,
      );
      return payload?.status || {};
    } catch (_) {
      return {};
    }
  }

  async function alignEventCursor(state) {
    const status = await runtimeStatus(state);
    const sequence = Number(status?.event_sequence);
    if (Number.isFinite(sequence) && sequence >= 0) state.cursor = sequence;
    return status;
  }

  function turnRequest(state, status, text) {
    const conversationID = String(state.conversationID || "").trim();
    const processingConversationID = String(
      status?.processing_conversation_id || "",
    ).trim();
    const processingTurnID = String(status?.processing_turn_id || "").trim();
    const params = {
      threadId: state.threadID,
      input: [{type: "text", text}],
    };
    if (!processingConversationID) {
      return {method: "turn/start", params: {...params, skill_ids: state.skills}};
    }
    if (processingConversationID !== conversationID) {
      throw new Error("Profile Agent is processing another conversation");
    }
    if (!processingTurnID) {
      throw new Error("Profile Agent active turn is not ready for steering");
    }
    return {
      method: "turn/steer",
      params: {...params, turnId: processingTurnID},
      turnID: processingTurnID,
    };
  }

  function eventBelongsToCurrentTurn(state, payload) {
    const eventTurnID = P.eventTurnID(payload);
    if (!eventTurnID) return true;
    if (!state.turnID) {
      state.turnID = eventTurnID;
      return true;
    }
    return !state.turnID || eventTurnID === state.turnID;
  }

  // This is recovery for a stale browser-side active flag, not a second
  // composer feature. ChatKit does not expose a supported live-steer control.
  // If the Manager says the old turn ended, its atomic steer endpoint promotes
  // the already-submitted message to a fresh turn so it is never lost.
  async function recoverStaleActiveTurn(
    controller, state, profileState, text, updateConversation,
  ) {
    const status = await runtimeStatus(state);
    const request = turnRequest(state, status, text);
    if (request.method !== "turn/steer") {
      throw new Error("Profile Agent is already responding");
    }
    const response = await rpc(state, request.method, request.params);
    if (response?.managerTransition !== "turn/start") {
      throw new Error("Profile Agent is already responding");
    }
    const user = P.userItem(state, text);
    state.items.push(user);
    writeEvent(controller, {type: "thread.item.added", item: user});
    writeEvent(controller, {type: "thread.item.done", item: user});
    await updateConversation(profileState, state, {
      title: state.threadTitle || text.slice(0, 80), preview: text,
    }).catch(() => {});
    return response;
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
    const source = window.FTProfileAgentEventSource.open(state, url);
    state.source = source;
    const pending = [];
    let settled = false;
    let turnCompleted = false;
    let opened = false;
    const finish = result => {
      if (settled) return;
      settled = true;
      source.close();
      if (state.source === source) state.source = null;
      signal.removeEventListener("abort", abort);
      resolveDone(result);
    };
    const completeTurn = () => {
      if (turnCompleted) return;
      turnCompleted = true;
      resolveDone("turn_completed");
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
      appendDisplayableProcessDelta(state, controller, payload);
      if (method === "app_server_exit" || payload?.type === "app_server_exit") {
        // The isolated app-server is a replaceable transport process.  Its
        // exit does not define the Provider turn outcome; reconcile the
        // durable thread once instead of manufacturing a turn failure.
        finish("done");
        return;
      }
      if (payload?.error || /error/i.test(method) && !delta) {
        writeEvent(controller, {
          type: "error", code: "agent_error", message: P.errorMessage(payload),
        });
        finish("error");
        return;
      }
      const completed = structuredItem?.type === "workflow" ? "" : P.completedText(payload);
      if (completed) {
        const assistant = ensureAssistant(state);
        assistant.text = completed;
        const stableID = structuredItem?.id || payload?.params?.item?.id;
        if (stableID && stableID !== assistant.id) {
          writeEvent(controller, {type: "thread.item.removed", item_id: assistant.id});
          assistant.id = stableID;
        }
        markFinalResponse(state);
      }
      if (delta) {
        appendAssistantText(
          state,
          `${state.assistant?.text || ""}${delta}`,
        );
      }
      if (delta || completed) {
        emitProcessReplacement(state, controller, P.assistantItem(state, state.assistant.text));
      }
      if (/turn[/:._-](completed|complete|failed|error|aborted|interrupted)/i.test(method)) {
        const completion = P.turnCompletion(payload);
        if (completion.error || /failed|error|aborted|interrupted/i.test(completion.status)) {
          emitTurnOutcome(state, controller, completion.status, payload);
          writeEvent(controller, {
            type: "error",
            code: "agent_turn_failed",
            message: P.errorMessage(completion.error || payload),
          });
          finish("error");
          return;
        }
        // Keep SSE attached while the caller reconciles durable history.  The
        // final assistant item may legally arrive after turn/completed.
        completeTurn();
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
    const resuming = params.resume === true;
    if (!text && !resuming) throw new Error("A non-empty text message is required");
    let response = null;
    let transitionedSteer = false;
    if (state.active && !resuming) {
      response = await recoverStaleActiveTurn(
        controller, state, profileState, text, updateConversation,
      );
      transitionedSteer = true;
      state.eventStream?.close();
    }
    state.active = true;
    const generation = Number(state.streamGeneration || 0) + 1;
    state.streamGeneration = generation;
    const hadThread = Boolean(state.threadID || state.conversation?.provider_thread_id);
    state.assistant = null;
    state.finalResponseComplete = false;
    state.turnID = "";
    state.processDeltaText = new Map();
    const priorAssistantIDs = new Set(state.items
      .filter(isAssistantMessage)
      .map(item => String(item.id || "")));
    try {
      if (!transitionedSteer && !resuming) {
        await ensureThread(state);
        if (!hadThread) writeEvent(controller, {
          type: "thread.created", thread: P.threadObject(state),
        });
        const user = P.userItem(state, text);
        state.items.push(user);
        writeEvent(controller, {type: "thread.item.added", item: user});
        writeEvent(controller, {type: "thread.item.done", item: user});
      }
      writeEvent(controller, {
        type: "stream_options", stream_options: {allow_cancel: true},
      });
      let request = {method: "turn/start", turnID: ""};
      if (resuming) {
        await ensureThread(state);
        const status = await runtimeStatus(state);
        if (String(status.processing_conversation_id || "") !== state.conversationID
            || !status.processing_turn_id) return;
        state.turnID = String(status.processing_turn_id);
        state.cursor = Number(status.processing_event_after) || 0;
        request = {method: "resume", turnID: state.turnID};
      } else if (!transitionedSteer) {
        const runtimeStatus = await alignEventCursor(state);
        request = turnRequest(state, runtimeStatus, text);
        response = await rpc(state, request.method, request.params);
      }
      state.turnID = request.turnID || P.turnIDFrom(response) || state.turnID;
      if (request.method === "turn/start" || transitionedSteer) {
        // The request may have replaced a stopped app-server process.  Event
        // sequences are process-local, so use the Manager-owned cursor for
        // this exact turn instead of carrying a cursor from the old process.
        const startedStatus = await alignEventCursor(state);
        const eventAfter = Number(startedStatus?.processing_event_after);
        if (Number.isFinite(eventAfter) && eventAfter >= 0) {
          state.cursor = eventAfter;
        }
      }
      writeEvent(controller, {type: "turn.started", turn_id: state.turnID});
      // The app-server event buffer is replayable from the cursor captured
      // immediately before turn/start.  Opening SSE after the turn exists
      // avoids racing the lifecycle process startup without losing early
      // deltas from a fast response.
      let eventStream = openEventStream(state, controller, signal);
      state.eventStream = eventStream;
      await eventStream.ready.catch(() => {});
      eventStream.activate();
      let result = "retry";
      let retries = 0;
      while (result === "retry" && !signal.aborted && retries < 8) {
        result = await eventStream.done;
        retries += 1;
        if (result === "retry" && !signal.aborted) {
          eventStream = openEventStream(state, controller, signal);
          state.eventStream = eventStream;
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
          await reconcileThreadHistory(
            state, controller, priorAssistantIDs, signal,
          );
        } catch (error) {
          // Keep a successfully streamed response visible even if the
          // post-turn history reconciliation is temporarily unavailable.
          if (!state.assistant?.text) writeError(controller, error);
        }
      }
      if (state.assistant?.text && !signal.aborted) {
        const item = emitAssistant(state, controller);
        if (!state.items.some(existing => itemKey(existing) === itemKey(item))) {
          state.items.push(item);
        }
      }
      if (!resuming) await updateConversation(profileState, state, {
        title: state.threadTitle || text.slice(0, 80),
        preview: text,
      }).catch(() => {});
    } finally {
      if (state.streamGeneration === generation) {
        state.eventStream = null;
        closeSource(state);
        state.active = false;
        state.assistant = null;
      }
    }
  }

  window.FTProfileChatKitStream = Object.freeze({
    closeSource,
    authoritativePage,
    stableAuthoritativePage,
    restoreThread,
    resumeThread,
    rpc,
    turnRequest,
    streamTurn,
    writeError,
  });
})();
