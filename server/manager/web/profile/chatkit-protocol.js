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

  function page(data, options = {}) {
    return {
      data,
      has_more: Boolean(options.has_more),
      after: options.after || null,
    };
  }

  function itemPageParams(params = {}) {
    const requested = Number(
      params.limit ?? params.page_size ?? params.pageSize ?? 10,
    );
    return {
      limit: Number.isFinite(requested)
        ? Math.max(1, Math.min(Math.trunc(requested), 50)) : 10,
      after: String(params.after ?? params.cursor ?? "").trim(),
      order: String(params.order || "desc").toLowerCase() === "asc"
        ? "asc" : "desc",
    };
  }

  function chronologicalItems(items, order = "desc") {
    const values = Array.isArray(items) ? [...items] : [];
    return String(order || "desc").toLowerCase() === "desc"
      ? values.reverse()
      : values;
  }

  function chronologicalPageAfter(previous, requested, view = "") {
    const value = String(requested || "").trim();
    if (!value || !previous || previous.order !== "desc") return value;
    if (previous.view && view && previous.view !== view) return value;
    if (value === previous.after || !previous.items?.length) return value;
    const lastVisible = previous.items[previous.items.length - 1];
    if (String(lastVisible?.id || "") !== value) return value;
    // A descending backend page is normalized before it reaches ChatKit.
    // When ChatKit uses the last visible item as its cursor, that item is
    // now the newest one.  The older-page boundary is the first item.
    return String(previous.items[0]?.id || value);
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
      status: options.locked
        ? {type: "locked", reason: "Agent is stopped; history remains readable"}
        : {type: "active"},
      metadata: {
        profile_id: state.profileID,
        conversation_id: state.conversationID,
      },
      items: includeItems ? page(state.items, state.itemPage || {}) : page([]),
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
    const role = String(item?.role || "").toLowerCase();
    if (role && role !== "assistant") return false;
    // Generic provider messages also represent user/tool input. Their text
    // must never seed the live assistant accumulator or its stable item ID.
    if (/^message$/i.test(type)) return role === "assistant";
    return /^(agentmessage|assistantmessage|assistant|outputtext)$/i.test(type);
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

  function turnIDFrom(payload) {
    const value = responseValue(payload) || {};
    return String(
      value.turn?.id || value.turnId || value.turn_id
      || ""
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
    jsonResponse,
    itemPageParams,
    chronologicalItems,
    chronologicalPageAfter,
    operation,
    page,
    parseBody,
    randomID,
    rawMethod,
    eventTurnID,
    responseValue,
    terminalMethod,
    turnCompletion,
    turnIDFrom,
    threadIDFrom,
    threadObject,
    userItem,
  });
})();
