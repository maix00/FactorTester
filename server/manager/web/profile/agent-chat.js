(() => {
  function section(context) {
    const root = document.createElement("section");
    root.className = "job-section profile-agent-chat";
    const heading = document.createElement("h2");
    heading.textContent = context.t("Agent 对话");
    root.append(heading);
    return root;
  }

  function passiveRuntimeControls() {
    return {
      dispose() {},
      observeEvent() {},
      setConversation() {},
    };
  }

  function message(context, title, detail = "") {
    return FTUI.empty(context.t(title), detail ? context.t(detail) : "");
  }

  async function loadSkills(context, profile) {
    const payload = await context.api(
      `/api/client/profile-skills?profile_id=${encodeURIComponent(profile.profile_id)}`,
    );
    return (payload.skills || [])
      .filter(item => item.selected)
      .map(item => item.skill_id);
  }

  function locale(context) {
    return String(
      context.locale || context.language || context.lang
      || document.documentElement.lang || navigator.language || "zh-Hans",
    );
  }

  async function mountChatKit(context, profile, host, status, options = {}) {
    if (!window.FTProfileChatKit) {
      throw new Error(context.t("Agent 对话组件尚未加载"));
    }
    const skills = options.readOnly || options.historyOnly
      ? [] : await loadSkills(context, profile);
    await window.FTProfileChatKit.load();
    if (!options.conversationOnly && !window.FTProfileAgentRuntimeControls) {
      throw new Error(context.t("Agent 运行设置组件尚未加载"));
    }
    const runtimeControls = options.conversationOnly
      ? passiveRuntimeControls()
      : window.FTProfileAgentRuntimeControls.create(
        profile, context, {readOnly: Boolean(options.readOnly)},
      );
    if (!options.conversationOnly) {
      options.settingsHost?.replaceChildren(runtimeControls.element);
    }
    let selectedConversationID = "";
    const adapter = window.FTProfileChatKit.create(profile, context, {
      skills,
      readOnly: Boolean(options.readOnly),
      profileKey: options.profileKey,
      profileScope: options.profileScope,
      historyOnly: Boolean(options.historyOnly),
      onConversationChange: conversation => {
        selectedConversationID = String(
          conversation?.conversationID
          || conversation?.conversation?.conversation_id
          || "",
        ).trim();
        runtimeControls.setConversation(conversation);
      },
      onRuntimeEvent: runtimeControls.observeEvent,
    });
    const chatStage = document.createElement("div");
    chatStage.className = "profile-chatkit-stage";
    const target = document.createElement("openai-chatkit");
    target.className = "profile-chatkit";
    target.setOptions({
      api: {
        // ChatKit is the UI protocol only. The Manager adapter owns the
        // Profile-scoped thread catalog and provider-thread mapping.
        url: adapter.endpoint,
        domainKey: "factor-tester-profile-agent",
        fetch: adapter.fetch,
      },
      locale: adapter.locale || locale(context),
      history: {enabled: true},
      ...(selectedConversationID
        ? {initialThread: selectedConversationID}
        : (options.readOnly || options.historyOnly ? {initialThread: null} : {})),
      header: {
        enabled: true,
        title: {enabled: true, text: context.t("研究身份 Agent")},
      },
      startScreen: {
        greeting: context.t("可以向这个研究 Agent 提问"),
        prompts: [
          {label: context.t("查看下一步"), prompt: context.t("请根据当前研究状态告诉我下一步")},
          {label: context.t("检查研究状态"), prompt: context.t("请检查当前研究身份的状态")},
        ],
      },
      composer: {
        placeholder: context.t("输入要交给 Agent 的研究问题…"),
        attachments: {enabled: false},
      },
    });
    target.addEventListener("chatkit.ready", () => {
      status.textContent = context.t("Agent 对话已连接");
      if ((options.readOnly || options.historyOnly)
          && typeof target.showHistory === "function") {
        // Read-only entry is a history-list entry point, not a new-thread
        // entry point.  ChatKit owns the list and will open a thread only
        // after the viewer selects one.
        Promise.resolve(target.showHistory()).catch(error => {
          status.textContent = `${context.t("历史会话读取失败")}: ${
            error?.message || context.t("请重试")}`;
        });
      }
    });
    target.addEventListener("chatkit.error", event => {
      const error = event.detail?.error;
      status.textContent = `${context.t("Agent 对话发生错误")}: ${
        error?.message || context.t("请检查 Agent 状态")}`;
    });
    target.addEventListener("chatkit.thread.change", event => {
      const identifier = String(event.detail?.threadId || "").trim();
      if (identifier) selectedConversationID = identifier;
    });
    chatStage.append(target);
    host.replaceChildren(chatStage);
    if (options.readOnly) {
      const composerNote = document.createElement("div");
      composerNote.className = "profile-chatkit-readonly-composer";
      composerNote.setAttribute("role", "note");
      composerNote.setAttribute("aria-live", "polite");
      composerNote.textContent = context.t(
        "只读会话：可以查看历史消息，但不能发送问题。",
      );
      host.append(composerNote);
    }
    return {
      adapter,
      runtimeControls,
      chat: target,
    };
  }

  async function render(context, profile, options = {}) {
    const root = section(context);
    const conversationOnly = Boolean(options.conversationOnly);
    if (conversationOnly) {
      root.classList.add("profile-agent-chat-conversation-only");
      root.replaceChildren();
    }
    const runtime = profile.runtime || {};
    const readOnly = Boolean(options.readOnly);
    if (readOnly) {
      const note = document.createElement("p");
      note.className = "settings-muted";
      note.textContent = context.t(
        "这是只读会话副本。可以查看历史消息，但不能发送问题、修改文件、停止或删除 Agent。",
      );
      const status = document.createElement("p");
      status.className = "settings-muted profile-agent-status";
      status.setAttribute("aria-live", "polite");
      const settingsHost = document.createElement("div");
      settingsHost.className = "profile-agent-settings-host";
      const host = document.createElement("div");
      host.className = "profile-chatkit-host profile-chatkit-readonly";
      host.setAttribute("aria-readonly", "true");
      root.append(note, status, settingsHost, host);
      try {
        status.textContent = context.t("正在读取只读会话…");
        await mountChatKit(
          context, profile, host, status, {...options, settingsHost},
        );
        status.textContent = context.t("只读会话");
      } catch (error) {
        host.replaceChildren(message(
          context, "只读会话读取失败", error.message || "",
        ));
        status.textContent = context.t("只读会话");
      }
      return root;
    }
    if (runtime.runtime_kind !== "server") {
      root.append(message(
        context,
        "当前 Profile 不是服务器运行",
        "客户端运行的 Skill 由客户端随应用管理。",
      ));
      return root;
    }
    const note = document.createElement("p");
    note.className = "settings-muted";
    note.textContent = context.t(
      "会话属于当前研究身份；停止、解绑或更换 Agent 不会删除会话。对话事件不会把模型令牌或服务器本地路径发送给浏览器。",
    );
    const status = document.createElement("p");
    status.className = "settings-muted profile-agent-status";
    status.setAttribute("aria-live", "polite");
    const host = document.createElement("div");
    host.className = "profile-chatkit-host";
    // ChatKit keeps internal request state in the custom element.  The tab
    // cache may detach and later reattach that element, which leaves its
    // history sidebar in an unfinished loading state in some browsers.  Ask
    // the tab cache to remount this host when the tab is activated again.
    host.dataset.ftRerenderOnTabRestore = "true";
    host.setAttribute("aria-live", "polite");
    const settingsHost = document.createElement("div");
    settingsHost.className = "profile-agent-settings-host";
    if (conversationOnly) root.append(host);
    else root.append(note, status, settingsHost, host);

    let mounted = null;
    let leaving = false;
    let activationPromise = null;

    function disposeChat() {
      mounted?.adapter.dispose();
      mounted?.runtimeControls.dispose();
      mounted = null;
      settingsHost.replaceChildren();
      host.replaceChildren();
    }

    const isCurrent = () => context.isRouteCurrent?.() !== false;

    async function activateAgent() {
      if (!isCurrent() || leaving) return;
      const payload = await context.api(
        `/api/client/profile-agent?profile_id=${encodeURIComponent(profile.profile_id)}`,
      );
      if (!isCurrent() || leaving) return;
      if (!profile.active_claim) {
        status.textContent = context.t(
          "请先认领这个服务器 Profile；历史会话仍可读取",
        );
        mounted = await mountChatKit(
          context, profile, host, status,
          {...options, historyOnly: true, settingsHost},
        );
        return;
      }
      if (!options.lifecycleManaged && !payload.status?.running) {
        status.textContent = context.t("正在启动 Agent…");
        await context.api("/api/client/profile-agent/start", {
          method: "POST",
          body: JSON.stringify({profile_id: profile.profile_id}),
        });
      }
      if (!isCurrent() || leaving) return;
      status.textContent = context.t("正在加载 Agent 对话…");
      mounted = await mountChatKit(
        context, profile, host, status, {...options, settingsHost},
      );
      if (!isCurrent()) disposeChat();
    }

    async function deactivateAgent() {
      if (leaving) return;
      leaving = true;
      disposeChat();
      try {
        await activationPromise;
      } catch (_) {
        // A failed activation has no live Agent to stop.
      }
      if (!profile.active_claim) return;
      await context.api("/api/client/profile-agent/stop", {
        method: "POST",
        body: JSON.stringify({profile_id: profile.profile_id}),
      }).catch(() => {});
    }

    host.__ftBeforeTabSave = () => {
      if (options.lifecycleManaged) disposeChat();
      else void deactivateAgent();
    };
    activationPromise = activateAgent();
    activationPromise.catch(error => {
      if (leaving) return;
      status.textContent = error.message || context.t("读取 Agent 状态失败");
      if (conversationOnly) {
        host.replaceChildren(message(
          context,
          "Agent 对话读取失败",
          error.message || "",
        ));
      }
    });
    return root;
  }

  window.FTAgentChat = {render};
})();
