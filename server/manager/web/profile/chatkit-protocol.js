(() => {
  function randomID(prefix) {
    const suffix = typeof globalThis.crypto?.randomUUID === "function"
      ? globalThis.crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    return `${prefix}-${suffix}`;
  }

  function jsonResponse(payload, status = 200) {
    return new Response(JSON.stringify(payload), {
      status,
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
      },
    });
  }

  function page(data) {
    return {data, has_more: false, after: null};
  }

  function threadObject(state, options = {}) {
    const includeItems = options.includeItems !== false;
    return {
      // ChatKit sees the Manager-owned conversation id.  The provider thread
      // id remains an internal binding and is never used as the browser's
      // history key.
      id: state.conversationID,
      title: state.threadTitle || null,
      created_at: state.createdAt,
      status: {type: "active"},
      metadata: {
        profile_id: state.profileID,
        conversation_id: state.conversationID,
      },
      items: includeItems ? page(state.items) : page([]),
    };
  }

  function userItem(state, text) {
    return {
      id: randomID("user"),
      type: "user_message",
      thread_id: state.conversationID,
      created_at: new Date().toISOString(),
      content: [{type: "input_text", text}],
      attachments: [],
      quoted_text: null,
      inference_options: {},
    };
  }

  function assistantItem(state, text = "") {
    const assistant = state.assistant || {
      id: randomID("assistant"),
      created_at: new Date().toISOString(),
    };
    return {
      id: assistant.id,
      type: "assistant_message",
      thread_id: state.conversationID,
      created_at: assistant.created_at,
      content: [{type: "output_text", text, annotations: []}],
    };
  }

  function rawMethod(payload) {
    return String(
      payload?.method || payload?.type || payload?.params?.method || "",
    );
  }

  function agentMessageDelta(payload) {
    if (rawMethod(payload) !== "item/agentMessage/delta") return "";
    const delta = eventParams(payload).delta;
    return typeof delta === "string" ? delta : "";
  }

  function eventTurnID(payload) {
    const params = payload?.params || {};
    const item = params.item || payload?.item || {};
    const metadata = item.metadata
      || item.internal_chat_message_metadata_passthrough
      || {};
    return String(
      params.turnId || params.turn_id || params.turn?.id
      || payload?.turnId || payload?.turn_id || payload?.turn?.id
      || item.turnId || item.turn_id || metadata.turn_id || "",
    ).trim();
  }

  function eventParams(payload) {
    return payload?.params && typeof payload.params === "object"
      ? payload.params
      : payload || {};
  }

  function textValue(value) {
    if (typeof value === "string") return value;
    if (Array.isArray(value)) return value.map(textValue).join("");
    if (!value || typeof value !== "object") return "";
    for (const key of ["text", "value", "output_text", "content", "parts", "message"]) {
      const text = textValue(value[key]);
      if (text) return text;
    }
    return "";
  }

  function completedItem(payload) {
    const params = eventParams(payload);
    return params.item || payload?.item || params.completed_item
      || payload?.completed_item || null;
  }

  function isAssistantItem(item) {
    const type = String(item?.type || item?.kind || "").replace(/[-_]/g, "");
    return /^(agentmessage|assistantmessage|assistant|outputtext|message)$/i.test(type);
  }

  function completedText(payload) {
    const item = completedItem(payload);
    if (!isAssistantItem(item)) return "";
    return textValue(item.text ?? item.content ?? item.output_text ?? item.message);
  }

  function errorMessage(payload) {
    const value = payload?.error || payload?.params?.error || payload;
    if (typeof value === "string") return value;
    return String(value?.message || value?.code || "Agent returned an error");
  }

  function terminalMethod(method) {
    // Item completion only marks one item (often a tool call). The turn is
    // the only event that closes the ChatKit response stream.
    return /turn[/:._-](completed|complete|failed|error|aborted|interrupted)/i
      .test(method);
  }

  function turnCompletion(payload) {
    const params = eventParams(payload);
    const turn = params.turn || payload?.turn || {};
    const rawStatus = turn.status ?? params.status ?? payload?.status ?? "";
    const status = typeof rawStatus === "string"
      ? rawStatus
      : String(rawStatus?.type || rawStatus?.value || "");
    return {
      status: status.toLowerCase(),
      error: turn.error || params.error || payload?.error || null,
    };
  }

  function chatLocale(context) {
    const raw = String(
      context?.locale || context?.language || context?.lang
      || document.documentElement.lang || navigator.language || "zh-Hans",
    );
    if (/^zh[-_]?(tw|hk|mo)/i.test(raw)) return "zh-Hant";
    if (/^zh/i.test(raw)) return "zh";
    return raw.split(/[-_]/)[0] || "en";
  }

  function responseValue(payload) {
    return payload?.response?.result
      || payload?.response
      || payload?.result
      || payload;
  }

  function threadIDFrom(payload) {
    const value = responseValue(payload) || {};
    return String(
      value.thread?.id || value.threadId || value.thread_id
      || value.turn?.id || value.turnId || value.id || "",
    ).trim();
  }

  function historyTimestamp(value, fallback) {
    if (typeof value === "number" && Number.isFinite(value)) {
      return new Date(value < 100000000000 ? value * 1000 : value).toISOString();
    }
    if (typeof value === "string" && value.trim()) {
      const parsed = Date.parse(value);
      if (Number.isFinite(parsed)) return new Date(parsed).toISOString();
    }
    return fallback;
  }

  function historyItems(state, thread) {
    const turns = Array.isArray(thread?.turns) ? thread.turns : [];
    const result = [];
    for (const turn of turns) {
      const items = Array.isArray(turn?.items) ? turn.items : [];
      for (const item of items) {
        const rawType = String(item?.type || item?.kind || "")
          .replace(/[-_]/g, "").toLowerCase();
        const id = String(item?.id || randomID(rawType || "history"));
        const createdAt = historyTimestamp(
          item?.createdAt || item?.created_at || turn?.startedAt || turn?.started_at,
          state.createdAt,
        );
        const threadID = state.threadID;
        if (rawType === "usermessage" || rawType === "inputmessage") {
          const text = textValue(item?.content ?? item?.text ?? item?.message);
          if (!text) continue;
          result.push({
            id,
            type: "user_message",
            thread_id: threadID,
            created_at: createdAt,
            content: [{type: "input_text", text}],
            attachments: [],
            quoted_text: null,
            inference_options: {},
          });
          continue;
        }
        if (rawType === "agentmessage" || rawType === "assistantmessage") {
          const text = textValue(item?.text ?? item?.content ?? item?.message);
          if (!text) continue;
          result.push({
            id,
            type: "assistant_message",
            thread_id: threadID,
            created_at: createdAt,
            content: [{type: "output_text", text, annotations: []}],
          });
        }
      }
    }
    return result;
  }

  function extractInputText(params) {
    const input = params?.input;
    if (typeof input === "string") return input.trim();
    if (Array.isArray(input)) {
      return input.map(item => typeof item === "string"
        ? item
        : String(item?.text || "")).join(" ").trim();
    }
    const content = input?.content || params?.content;
    if (Array.isArray(content)) {
      return content.map(item => typeof item === "string"
        ? item
        : String(item?.text || "")).join(" ").trim();
    }
    return String(params?.prompt || "").trim();
  }

  function parseBody(input, init) {
    if (typeof init?.body === "string") {
      try { return JSON.parse(init.body); } catch (_) { return null; }
    }
    if (typeof Request !== "undefined" && input instanceof Request) {
      return input.clone().json().catch(() => null);
    }
    return null;
  }

  function operation(body) {
    return String(body?.type || body?.operation || body?.method || "")
      .replace(/^backend\./, "");
  }

  window.FTProfileChatKitProtocol = Object.freeze({
    assistantItem,
    agentMessageDelta,
    chatLocale,
    completedText,
    errorMessage,
    extractInputText,
    historyTimestamp,
    historyItems,
    jsonResponse,
    operation,
    page,
    parseBody,
    randomID,
    rawMethod,
    eventTurnID,
    responseValue,
    terminalMethod,
    turnCompletion,
    threadIDFrom,
    threadObject,
    userItem,
  });
})();
