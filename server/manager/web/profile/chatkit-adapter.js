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

  function create(profile, context, options = {}) {
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
