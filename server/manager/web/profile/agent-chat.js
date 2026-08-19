(() => {
  function section(context) {
    const root = document.createElement("section");
    root.className = "job-section profile-agent-chat";
    const heading = document.createElement("h2");
    heading.textContent = context.t("Agent 对话");
    root.append(heading);
    return root;
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

  async function mountChatKit(context, profile, host, status) {
    if (!window.FTProfileChatKit) {
      throw new Error(context.t("Agent 对话组件尚未加载"));
    }
    const skills = await loadSkills(context, profile);
    await window.FTProfileChatKit.load();
    const adapter = window.FTProfileChatKit.create(profile, context, {skills});
    const chat = document.createElement("openai-chatkit");
    chat.className = "profile-chatkit";
    chat.addEventListener("chatkit.ready", () => {
      status.textContent = context.t("Agent 对话已连接");
    });
    chat.addEventListener("chatkit.error", event => {
      const error = event.detail?.error;
      status.textContent = `${context.t("Agent 对话发生错误")}: ${
        error?.message || context.t("请检查 Agent 状态")}`;
    });
    chat.setOptions({
      api: {
        // ChatKit is the UI protocol only. The Manager adapter routes each
        // Profile to its configured provider without exposing provider keys.
        url: adapter.endpoint,
        domainKey: "factor-tester-profile-agent",
        fetch: adapter.fetch,
      },
      locale: adapter.locale || locale(context),
      history: {enabled: false},
      header: {
        enabled: true,
        title: {enabled: true, text: context.t("Agent 对话")},
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
    host.replaceChildren(chat);
    return {adapter, chat};
  }

  async function render(context, profile) {
    const root = section(context);
    const runtime = profile.runtime || {};
    if (runtime.runtime_kind !== "server") {
      root.append(message(
        context,
        "当前 Profile 不是服务器运行",
        "客户端运行的 Skill 由客户端随应用管理。",
      ));
      return root;
    }
    if (!profile.active_claim) {
      root.append(message(context, "请先认领这个服务器 Profile"));
      return root;
    }

    const note = document.createElement("p");
    note.className = "settings-muted";
    note.textContent = context.t(
      "服务器 Agent 通过当前 Profile 的正式工作区运行；对话事件不会把模型令牌或服务器本地路径发送给浏览器。",
    );
    const status = document.createElement("p");
    status.className = "settings-muted profile-agent-status";
    status.setAttribute("aria-live", "polite");
    const actions = document.createElement("div");
    actions.className = "settings-inline-actions profile-agent-actions-bar";
    const start = document.createElement("button");
    start.className = "primary";
    start.textContent = context.t("启动 Agent");
    const stop = document.createElement("button");
    stop.className = "secondary";
    stop.textContent = context.t("停止 Agent");
    actions.append(start, stop);

    const host = document.createElement("div");
    host.className = "profile-chatkit-host";
    host.setAttribute("aria-live", "polite");
    root.append(note, status, actions, host);

    let mounted = null;
    async function refreshStatus() {
      const payload = await context.api(
        `/api/client/profile-agent?profile_id=${encodeURIComponent(profile.profile_id)}`,
      );
      const running = Boolean(payload.status?.running);
      start.disabled = running;
      stop.disabled = !running;
      if (!running) {
        mounted?.adapter.dispose();
        mounted = null;
        host.replaceChildren(message(context, "Agent 尚未启动"));
        status.textContent = context.t("Agent 尚未启动");
        return;
      }
      status.textContent = context.t("正在加载 Agent 对话…");
      if (!mounted) mounted = await mountChatKit(context, profile, host, status);
    }

    start.onclick = async () => {
      start.disabled = true;
      status.textContent = context.t("正在启动 Agent…");
      try {
        await context.api("/api/client/profile-agent/start", {
          method: "POST",
          body: JSON.stringify({profile_id: profile.profile_id}),
        });
        await refreshStatus();
      } catch (error) {
        status.textContent = `${context.t("Agent 启动失败")}: ${error.message || ""}`;
        start.disabled = false;
      }
    };
    stop.onclick = async () => {
      stop.disabled = true;
      try {
        await context.api("/api/client/profile-agent/stop", {
          method: "POST",
          body: JSON.stringify({profile_id: profile.profile_id}),
        });
        mounted?.adapter.dispose();
        mounted = null;
        await refreshStatus();
      } catch (error) {
        status.textContent = error.message || context.t("停止 Agent");
      }
    };

    start.disabled = true;
    stop.disabled = true;
    refreshStatus().catch(error => {
      status.textContent = error.message || context.t("Agent 启动失败");
    });
    return root;
  }

  window.FTAgentChat = {render};
})();
