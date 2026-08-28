(() => {
  const profileStates = new Map();
  const CONVERSATION_LIST_TIMEOUT_MS = 10000;
  const SELECTED_CONVERSATION_KEY = "ft-profile-agent-selected-conversation:";

  function profileKey(profile) {
    return String(profile?.profile_id || "").trim();
  }

  function conversationKey(conversation) {
    return String(conversation?.conversation_id || "").trim();
  }

  function selectedConversationStorageKey(profileID) {
    return `${SELECTED_CONVERSATION_KEY}${encodeURIComponent(String(profileID || ""))}`;
  }

  function readSelectedConversation(profileID) {
    try {
      return String(
        sessionStorage.getItem(selectedConversationStorageKey(profileID)) || "",
      ).trim();
    } catch (_) {
      return "";
    }
  }

  function rememberSelectedConversation(profileID, conversationID) {
    const value = String(conversationID || "").trim();
    try {
      const key = selectedConversationStorageKey(profileID);
      if (value) sessionStorage.setItem(key, value);
      else sessionStorage.removeItem(key);
    } catch (_) {
      // Private browsing and embedded WebViews may deny sessionStorage.
    }
  }

  function withTimeout(promise, milliseconds) {
    let timer = null;
    const timeout = new Promise((_, reject) => {
      timer = setTimeout(() => reject(
        new Error("Profile Agent conversation history timed out"),
      ), milliseconds);
    });
    return Promise.race([promise, timeout]).finally(() => {
      if (timer !== null) clearTimeout(timer);
    });
  }

  function dateValue(value, fallback = new Date().toISOString()) {
    if (typeof value === "number" && Number.isFinite(value)) {
      return new Date(value < 100000000000 ? value * 1000 : value).toISOString();
    }
    if (typeof value === "string" && value.trim()) {
      const parsed = Date.parse(value);
      if (Number.isFinite(parsed)) return new Date(parsed).toISOString();
    }
    return fallback;
  }

  function profileStateFor(profile, context, skills) {
    const identifier = profileKey(profile);
    if (!identifier) throw new Error("profile_id is required");
    let state = profileStates.get(identifier);
    if (state) {
      state.context = context;
      state.skills = [...skills];
      return state;
    }
    state = {
      profileID: identifier,
      context,
      skills: [...skills],
      conversations: new Map(),
      selectedID: readSelectedConversation(identifier),
      conversationListPromise: null,
    };
    profileStates.set(identifier, state);
    return state;
  }

  function conversationState(profileState, conversation) {
    const identifier = conversationKey(conversation);
    if (!identifier) throw new Error("conversation_id is required");
    let state = profileState.conversations.get(identifier);
    if (state) {
      state.conversation = {...state.conversation, ...conversation};
      state.context = profileState.context;
      state.skills = [...profileState.skills];
      state.runtimeObserver = profileState.runtimeObserver;
      state.turnActivityObserver = profileState.turnActivityObserver;
      return state;
    }
    state = {
      profileID: profileState.profileID,
      conversationID: identifier,
      context: profileState.context,
      skills: [...profileState.skills],
      conversation: {...conversation},
      threadID: String(conversation.provider_thread_id || "").trim(),
      threadTitle: String(conversation.title || "").trim(),
      createdAt: dateValue(conversation.created_at),
      cursor: 0,
      items: [],
      source: null,
      turnID: "",
      assistant: null,
      active: false,
      threadPromise: null,
      runtimePromise: null,
      runtimeAttached: false,
      restored: false,
      runtimeObserver: profileState.runtimeObserver,
      turnActivityObserver: profileState.turnActivityObserver,
    };
    profileState.conversations.set(identifier, state);
    return state;
  }

  async function loadConversations(profileState) {
    if (profileState.conversationListPromise) {
      return profileState.conversationListPromise;
    }
    let pending;
    pending = withTimeout(profileState.context.api(
      `/api/client/profile-agent/conversations?profile_id=${encodeURIComponent(profileState.profileID)}`,
    ), CONVERSATION_LIST_TIMEOUT_MS).then(payload => {
      const conversations = Array.isArray(payload.conversations)
        ? payload.conversations : [];
      return conversations;
    }).then(conversations => {
      const selectedID = profileState.selectedID;
      const seen = new Set();
      for (const conversation of conversations) {
        const identifier = conversationKey(conversation);
        if (!identifier) continue;
        const state = conversationState(profileState, conversation);
        const providerThreadID = String(conversation.provider_thread_id || "").trim();
        if (state.threadID !== providerThreadID) {
          state.threadID = providerThreadID;
          state.restored = false;
          state.runtimeAttached = false;
          state.items = [];
        }
        state.threadTitle = String(conversation.title || state.threadTitle || "").trim();
        state.createdAt = dateValue(conversation.created_at, state.createdAt);
        seen.add(identifier);
      }
      for (const identifier of profileState.conversations.keys()) {
        if (!seen.has(identifier)) profileState.conversations.delete(identifier);
      }
      const selected = conversations.find(item => item.active) || conversations[0];
      if (!selectedID || !profileState.conversations.has(selectedID)) {
        profileState.selectedID = conversationKey(selected);
      }
      rememberSelectedConversation(profileState.profileID, profileState.selectedID);
      const current = profileState.conversations.get(profileState.selectedID);
      if (current) profileState.onConversationChange?.(current);
      return conversations;
    }).finally(() => {
      if (profileState.conversationListPromise === pending) {
        profileState.conversationListPromise = null;
      }
    });
    profileState.conversationListPromise = pending;
    return pending;
  }

  async function createConversation(profileState, title = "") {
    const payload = await profileState.context.api(
      "/api/client/profile-agent/conversations/create",
      {
        method: "POST",
        body: JSON.stringify({profile_id: profileState.profileID, title}),
      },
    );
    const state = conversationState(profileState, payload.conversation);
    profileState.selectedID = state.conversationID;
    rememberSelectedConversation(profileState.profileID, state.conversationID);
    profileState.onConversationChange?.(state);
    return state;
  }

  async function getConversation(profileState, requestedID = "", activate = false) {
    await loadConversations(profileState);
    const identifier = String(
      requestedID || profileState.selectedID || "",
    ).trim();
    const state = profileState.conversations.get(identifier);
    if (!state) throw new Error("conversation not found");
    if (activate && profileState.selectedID !== identifier) {
      const payload = await profileState.context.api(
        "/api/client/profile-agent/conversations/select",
        {
          method: "POST",
          body: JSON.stringify({
            profile_id: profileState.profileID,
            conversation_id: identifier,
          }),
        },
      );
      if (payload.conversation) {
        state.conversation = {...state.conversation, ...payload.conversation};
      }
    }
    profileState.selectedID = identifier;
    rememberSelectedConversation(profileState.profileID, identifier);
    profileState.onConversationChange?.(state);
    return state;
  }

  async function updateConversation(profileState, state, values) {
    const payload = await profileState.context.api(
      "/api/client/profile-agent/conversations/update",
      {
        method: "POST",
        body: JSON.stringify({
          profile_id: profileState.profileID,
          conversation_id: state.conversationID,
          ...values,
        }),
      },
    );
    if (payload.conversation) {
      state.conversation = {...state.conversation, ...payload.conversation};
      state.threadTitle = String(state.conversation.title || state.threadTitle || "");
      profileState.onConversationChange?.(state);
    }
    return state;
  }

  async function deleteConversation(profileState, state, closeSource) {
    await profileState.context.api(
      "/api/client/profile-agent/conversations/delete",
      {
        method: "POST",
        body: JSON.stringify({
          profile_id: profileState.profileID,
          conversation_id: state.conversationID,
        }),
      },
    );
    closeSource(state);
    profileState.conversations.delete(state.conversationID);
    if (profileState.selectedID === state.conversationID) {
      profileState.selectedID = "";
      rememberSelectedConversation(profileState.profileID, "");
    }
  }

  function conversationIDFrom(params) {
    return String(params?.thread_id || params?.threadId || "").trim();
  }

  function dispose(profileState, closeSource) {
    for (const state of profileState.conversations.values()) {
      closeSource(state);
      state.active = false;
    }
    if (profileStates.get(profileState.profileID) === profileState) {
      profileStates.delete(profileState.profileID);
    }
  }

  window.FTProfileChatKitConversations = Object.freeze({
    conversationIDFrom,
    conversationState,
    createConversation,
    deleteConversation,
    dispose,
    getConversation,
    loadConversations,
    profileStateFor,
    updateConversation,
  });
})();
