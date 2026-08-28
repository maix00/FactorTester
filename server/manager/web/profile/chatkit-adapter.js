(() => {
  const P = window.FTProfileChatKitProtocol;
  const C = window.FTProfileChatKitConversations;
  const S = window.FTProfileChatKitStream;
  const CHATKIT_SCRIPT =
    "https://cdn.platform.openai.com/deployments/chatkit/chatkit.js";
  const CHATKIT_ENDPOINT = "/api/client/profile-agent/chatkit";
  const ITEM_VIEW = "timeline";
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

    function rememberPage(state, page) {
      state.items = page.items;
      state.itemPage = page;
    }

    if (operation === "threads.list") {
      const conversations = await C.loadConversations(profileState);
      return P.jsonResponse(P.page(conversations.map(conversation => {
        const state = C.conversationState(profileState, conversation);
        return P.threadObject(state, {
          includeItems: false,
          locked: profileState.historyOnly,
        });
      })));
    }
    if (operation === "threads.get_by_id") {
      const state = await C.getConversation(
        profileState, C.conversationIDFrom(params), !profileState.historyOnly,
      );
      const page = await S.stableAuthoritativePage(state);
      rememberPage(state, page);
      return P.jsonResponse(P.threadObject(
        {...state, items: page.items, itemPage: page},
        {locked: profileState.historyOnly},
      ));
    }
    if (operation === "items.list") {
      const state = await C.getConversation(
        profileState, C.conversationIDFrom(params), false,
      );
      const page = params.after
        ? await S.authoritativePage(state, params)
        : await S.stableAuthoritativePage(state);
      rememberPage(state, page);
      return P.jsonResponse(P.page(page.items, page));
    }
    if (operation === "threads.update") {
      if (profileState.historyOnly) {
        return P.jsonResponse({error: "Agent is stopped; history is read-only"}, 403);
      }
      const state = await C.getConversation(
        profileState, C.conversationIDFrom(params), false,
      );
      await C.updateConversation(profileState, state, {
        title: String(params.title || "").trim(),
      });
      return P.jsonResponse(P.threadObject(state));
    }
    if (operation === "threads.delete") {
      if (profileState.historyOnly) {
        return P.jsonResponse({error: "Agent is stopped; history is read-only"}, 403);
      }
      const state = await C.getConversation(
        profileState, C.conversationIDFrom(params), false,
      );
      await C.deleteConversation(profileState, state, S.closeSource);
      return P.jsonResponse({});
    }
    if (operation === "threads.stop") {
      if (profileState.historyOnly) return P.jsonResponse({});
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
      if (profileState.historyOnly) {
        return P.jsonResponse({
          error: "start the Profile Agent before sending a question",
        }, 409);
      }
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

  function readOnlyItem(profileKey, conversationID, item) {
    const nativeTypes = new Set([
      "user_message", "assistant_message", "client_tool_call", "widget",
      "generated_image", "structured_input", "workflow", "task",
      "end_of_turn",
    ]);
    if (!nativeTypes.has(String(item?.type || ""))) {
      throw new Error("conversation source returned a non-ChatKit item");
    }
    return {
      ...item,
      thread_id: conversationID,
      metadata: {...(item.metadata || {}), profile_key: profileKey},
    };
  }

  function readOnlyThread(profileKey, conversation, itemPage = {}) {
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
      items: P.page((itemPage.items || []).map(item => (
        readOnlyItem(profileKey, identifier, item)
      )), itemPage),
    };
  }

  function readOnlyURL(
    path, profileState, conversationID = "", pageParams = {},
  ) {
    const params = new URLSearchParams({
      profile_key: profileState.profileKey,
      scope: profileState.profileScope,
    });
    if (conversationID) params.set("conversation_id", conversationID);
    if (pageParams.limit) params.set("limit", String(pageParams.limit));
    if (pageParams.after) params.set("after", pageParams.after);
    if (pageParams.order) params.set("order", pageParams.order);
    params.set("view", ITEM_VIEW);
    return `${path}?${params}`;
  }

  async function readOnlyJSON(
    profileState, path, conversationID = "", pageParams = {},
  ) {
    const payload = await profileState.context.api(
      readOnlyURL(path, profileState, conversationID, pageParams),
    );
    return payload || {};
  }

  async function readOnlyConversations(profileState) {
    if (profileState.conversationCache
        && Date.now() - profileState.conversationCacheAt < 5000) {
      return profileState.conversationCache;
    }
    const payload = await readOnlyJSON(
      profileState,
      "/api/client/profile-directory/conversations",
    );
    profileState.conversationCache = Array.isArray(payload.conversations)
      ? payload.conversations : [];
    profileState.conversationCacheAt = Date.now();
    return profileState.conversationCache;
  }

  async function readOnlyItems(profileState, conversationID, params = {}) {
    const pageParams = P.itemPageParams(params);
    const pageKey = conversationID;
    const previous = profileState.itemPages.get(pageKey);
    const after = P.chronologicalPageAfter(
      previous, pageParams.after, ITEM_VIEW,
    );
    const requestParams = {...pageParams, after};
    const payload = await readOnlyJSON(
      profileState,
      "/api/client/profile-directory/conversation-items",
      conversationID,
      requestParams,
    );
    const order = payload.order || pageParams.order;
    const page = {
      items: P.chronologicalItems(payload.items, order),
      has_more: Boolean(payload.has_more),
      after: payload.after || null,
      order,
      view: ITEM_VIEW,
    };
    profileState.itemPages.set(pageKey, page);
    return page;
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
      profileState.onConversationChange?.({
        conversationID,
        conversation: {...conversation},
      });
      return P.jsonResponse(readOnlyThread(
        profileState.profileKey,
        conversation,
        await readOnlyItems(profileState, conversationID),
      ));
    }
    if (operation === "items.list") {
      const page = await readOnlyItems(
        profileState, conversationID, params,
      );
      const conversations = await readOnlyConversations(profileState);
      const conversation = conversations.find(
        item => String(item.conversation_id || "") === conversationID,
      );
      if (conversation) profileState.onConversationChange?.({
        conversationID,
        conversation: {...conversation},
      });
      return P.jsonResponse(P.page(page.items.map(
        item => readOnlyItem(profileState.profileKey, conversationID, item),
      ), page));
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
        onConversationChange: options.onConversationChange,
        conversationCache: null,
        conversationCacheAt: 0,
        itemPages: new Map(),
      };
      return {
        fetch: (input, init) => fetchReadOnlyAdapter(profileState, input, init),
        endpoint: CHATKIT_ENDPOINT,
        locale: P.chatLocale(context),
        dispose() {},
      };
    }
    const profileState = C.profileStateFor(profile, context, options.skills || []);
    profileState.historyOnly = Boolean(options.historyOnly);
    profileState.onConversationChange = options.onConversationChange;
    profileState.runtimeObserver = options.onRuntimeEvent;
    profileState.turnActivityObserver = options.onTurnActivity;
    for (const state of profileState.conversations.values()) {
      state.runtimeObserver = profileState.runtimeObserver;
      state.turnActivityObserver = profileState.turnActivityObserver;
    }
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
