(() => {
  const P = window.FTProfileChatKitProtocol;
  const C = window.FTProfileChatKitConversations;
  const S = window.FTProfileChatKitStream;
  const CHATKIT_SCRIPT =
    "https://cdn.platform.openai.com/deployments/chatkit/chatkit.js";
  const CHATKIT_ENDPOINT = "/api/client/profile-agent/chatkit";
  let scriptLoad = null;

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

  async function fetchAdapter(profileState, input, init = {}) {
    const body = await P.parseBody(input, init);
    const operation = P.operation(body);
    if (!operation) return window.fetch(input, init);
    const params = body?.params && typeof body.params === "object"
      ? body.params : (body || {});

    if (operation === "threads.list") {
      const conversations = await C.loadConversations(profileState);
      return P.jsonResponse(P.page(conversations.map(conversation => {
        const state = C.conversationState(profileState, conversation);
        return P.threadObject(state, {includeItems: false});
      })));
    }
    if (operation === "threads.get_by_id") {
      const state = await C.getConversation(
        profileState, C.conversationIDFrom(params), true,
      );
      await S.restoreThread(state);
      return P.jsonResponse(P.threadObject(state));
    }
    if (operation === "items.list") {
      const state = await C.getConversation(
        profileState, C.conversationIDFrom(params), false,
      );
      await S.restoreThread(state);
      return P.jsonResponse(P.page(state.items));
    }
    if (operation === "threads.update") {
      const state = await C.getConversation(
        profileState, C.conversationIDFrom(params), false,
      );
      await C.updateConversation(profileState, state, {
        title: String(params.title || "").trim(),
      });
      return P.jsonResponse(P.threadObject(state));
    }
    if (operation === "threads.delete") {
      const state = await C.getConversation(
        profileState, C.conversationIDFrom(params), false,
      );
      await C.deleteConversation(profileState, state, S.closeSource);
      return P.jsonResponse({});
    }
    if (operation === "threads.stop") {
      const state = await C.getConversation(
        profileState, C.conversationIDFrom(params), false,
      );
      if (state.threadID && state.turnID) {
        await S.rpc(state, "turn/interrupt", {
          threadId: state.threadID, turnId: state.turnID,
        });
      }
      S.closeSource(state);
      return P.jsonResponse({});
    }
    if (operation === "threads.create" || operation === "threads.add_user_message") {
      const text = P.extractInputText(params);
      const requestedID = C.conversationIDFrom(params);
      const state = requestedID
        ? await C.getConversation(profileState, requestedID, true)
        : await C.createConversation(profileState);
      if (operation === "threads.create" && !text) {
        return P.jsonResponse(P.threadObject(state));
      }
      const controller = new AbortController();
      if (init.signal) {
        if (init.signal.aborted) controller.abort();
        else init.signal.addEventListener(
          "abort", () => controller.abort(), {once: true},
        );
      }
      const stream = new ReadableStream({
        start: streamController => {
          S.streamTurn(
            streamController,
            state,
            profileState,
            params,
            controller.signal,
            C.updateConversation,
          ).catch(error => {
            if (!controller.signal.aborted) S.writeError?.(streamController, error);
          }).finally(() => streamController.close());
        },
        cancel: () => { controller.abort(); S.closeSource(state); },
      });
      return new Response(stream, {
        headers: {
          "Content-Type": "text/event-stream; charset=utf-8",
          "Cache-Control": "no-store",
        },
      });
    }
    return P.jsonResponse({error: `Unsupported ChatKit operation: ${operation}`}, 400);
  }

  function readOnlyConversationID(params) {
    const values = [
      params?.thread_id,
      params?.threadId,
      params?.threadID,
      params?.conversation_id,
      params?.conversationId,
      params?.id,
      params?.thread?.id,
      params?.thread?.thread_id,
      params?.thread?.threadId,
      params?.thread?.conversation_id,
    ];
    return values.map(value => String(value || "").trim()).find(Boolean) || "";
  }

  function readOnlyText(value) {
    if (typeof value === "string") return value;
    if (Array.isArray(value)) return value.map(readOnlyText).join("");
    if (!value || typeof value !== "object") return "";
    for (const key of ["text", "value", "output_text", "content", "parts", "message"]) {
      const text = readOnlyText(value[key]);
      if (text) return text;
    }
    return "";
  }

  function readOnlyItem(profileKey, conversationID, item, index = 0) {
    const role = /^(assistant|assistant_message|agent_message)$/i.test(
      String(item?.role || item?.type || item?.item_type || "").trim(),
    )
      ? "assistant_message" : "user_message";
    const created = P.historyTimestamp(
      item?.created_at,
      new Date().toISOString(),
    );
    const text = readOnlyText(item);
    const itemID = String(item?.id || item?.item_id || "").trim()
      || `item-${conversationID}-${index}`;
    return {
      // Manager history rows use item_id rather than ChatKit's id.  Keep the
      // mapped id stable across list/get requests so ChatKit does not discard
      // the history as a different set of items on every read.
      id: itemID,
      type: role,
      thread_id: conversationID,
      created_at: created,
      content: [role === "assistant_message"
        ? {type: "output_text", text, annotations: []}
        : {type: "input_text", text}],
      ...(role === "user_message" ? {
        attachments: [], quoted_text: null, inference_options: {},
      } : {}),
      metadata: {profile_key: profileKey},
    };
  }

  function readOnlyThread(profileKey, conversation, items = []) {
    const identifier = String(conversation?.conversation_id || "");
    const created = P.historyTimestamp(
      conversation?.created_at,
      new Date().toISOString(),
    );
    return {
      id: identifier,
      title: conversation?.title || null,
      created_at: created,
      // ChatKit's ThreadStatus accepts active, locked, or closed.  A parent
      // viewer sees a locked historical thread: it is readable, but cannot
      // be used to send turns or mutate the source Agent conversation.
      status: {type: "locked", reason: "read-only conversation"},
      metadata: {profile_key: profileKey, conversation_id: identifier},
      items: P.page(items.map((item, index) => (
        readOnlyItem(profileKey, identifier, item, index)
      ))),
    };
  }

  function readOnlyURL(path, profileState, conversationID = "") {
    const params = new URLSearchParams({
      profile_key: profileState.profileKey,
      scope: profileState.profileScope,
    });
    if (conversationID) params.set("conversation_id", conversationID);
    return `${path}?${params}`;
  }

  async function readOnlyJSON(profileState, path, conversationID = "") {
    const payload = await profileState.context.api(
      readOnlyURL(path, profileState, conversationID),
    );
    return payload || {};
  }

  async function readOnlyConversations(profileState) {
    const payload = await readOnlyJSON(
      profileState,
      "/api/client/profile-directory/conversations",
    );
    return Array.isArray(payload.conversations) ? payload.conversations : [];
  }

  async function readOnlyItems(profileState, conversationID) {
    const payload = await readOnlyJSON(
      profileState,
      "/api/client/profile-directory/conversation-items",
      conversationID,
    );
    return Array.isArray(payload.items) ? payload.items : [];
  }

  async function fetchReadOnlyAdapter(profileState, input, init = {}) {
    const body = await P.parseBody(input, init);
    const operation = P.operation(body);
    if (!operation) return window.fetch(input, init);
    const params = body?.params && typeof body.params === "object"
      ? body.params : (body || {});
    const conversationID = readOnlyConversationID(params);
    if (operation === "threads.list") {
      const conversations = await readOnlyConversations(profileState);
      return P.jsonResponse(P.page(conversations.map(item => (
        readOnlyThread(profileState.profileKey, item)
      ))));
    }
    if (operation === "threads.get_by_id") {
      const conversations = await readOnlyConversations(profileState);
      const conversation = conversations.find(
        item => String(item.conversation_id || "") === conversationID,
      );
      if (!conversation) return P.jsonResponse({error: "conversation not found"}, 404);
      return P.jsonResponse(readOnlyThread(
        profileState.profileKey,
        conversation,
        await readOnlyItems(profileState, conversationID),
      ));
    }
    if (operation === "items.list") {
      return P.jsonResponse(P.page((await readOnlyItems(profileState, conversationID)).map(
        (item, index) => readOnlyItem(profileState.profileKey, conversationID, item, index),
      )));
    }
    if ([
      "threads.create", "threads.add_user_message", "threads.update",
      "threads.delete", "threads.stop",
    ].includes(operation)) {
      return P.jsonResponse({error: "read-only conversation"}, 403);
    }
    return P.jsonResponse({error: `Unsupported read-only ChatKit operation: ${operation}`}, 400);
  }

  function create(profile, context, options = {}) {
    if (options.readOnly) {
      const profileKey = String(
        options.profileKey || profile.profile_key || profile.profile_id || "",
      ).trim();
      const profileState = {
        profileID: profile.profile_id,
        profileKey,
        profileScope: options.profileScope || "servers",
        context,
      };
      return {
        fetch: (input, init) => fetchReadOnlyAdapter(profileState, input, init),
        endpoint: CHATKIT_ENDPOINT,
        locale: P.chatLocale(context),
        dispose() {},
      };
    }
    const profileState = C.profileStateFor(profile, context, options.skills || []);
    return {
      fetch: (input, init) => fetchAdapter(profileState, input, init),
      endpoint: CHATKIT_ENDPOINT,
      locale: P.chatLocale(context),
      dispose() {
        C.dispose(profileState, S.closeSource);
      },
    };
  }

  window.FTProfileChatKit = Object.freeze({load, create});
})();
