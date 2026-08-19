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

  function threadObject(state) {
    return {
      id: state.threadID,
      title: state.threadTitle || null,
      created_at: state.createdAt,
      status: {type: "active"},
      metadata: {profile_id: state.profileID},
      items: page(state.items),
    };
  }

  function userItem(state, text) {
    return {
      id: randomID("user"),
      type: "user_message",
      thread_id: state.threadID,
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
      thread_id: state.threadID,
      created_at: assistant.created_at,
      content: [{type: "output_text", text, annotations: []}],
    };
  }

  function rawMethod(payload) {
    return String(
      payload?.method || payload?.type || payload?.params?.method || "",
    );
  }

  function rawDelta(payload) {
    const params = payload?.params || {};
    for (const value of [params.delta, params.text, payload?.delta, payload?.text]) {
      if (typeof value === "string") return value;
    }
    const content = params.content ?? payload?.content;
    if (typeof content === "string") return content;
    if (Array.isArray(content)) {
      return content.map(item => typeof item === "string"
        ? item
        : String(item?.text || item?.content || "")).join("");
    }
    return "";
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
    chatLocale,
    completedText,
    errorMessage,
    extractInputText,
    jsonResponse,
    operation,
    page,
    parseBody,
    randomID,
    rawDelta,
    rawMethod,
    responseValue,
    terminalMethod,
    turnCompletion,
    threadIDFrom,
    threadObject,
    userItem,
  });
})();
