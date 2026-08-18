(() => {
  const sources = new Map();

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

  function threadID(response) {
    const result = response?.response?.result || response?.result || {};
    return String(
      result.thread?.id || result.threadId || result.thread_id || "",
    ).trim();
  }

  function addEvent(context, transcript, payload) {
    const params = payload?.params || {};
    const delta = params.delta || params.text || params.content;
    if (typeof delta === "string" && payload?.method?.includes("agentMessage")) {
      let target = transcript.lastElementChild;
      if (!target || target.dataset.kind !== "agent-message") {
        target = document.createElement("div");
        target.dataset.kind = "agent-message";
        target.className = "profile-agent-message profile-agent-message-assistant";
        transcript.append(target);
      }
      target.textContent += delta;
      transcript.scrollTop = transcript.scrollHeight;
      return;
    }
    const detail = document.createElement("pre");
    detail.className = "profile-agent-event";
    detail.textContent = JSON.stringify(payload, null, 2);
    transcript.append(detail);
    transcript.scrollTop = transcript.scrollHeight;
  }

  async function render(context, profile) {
    const root = section(context);
    const runtime = profile.runtime || {};
    if (runtime.runtime_kind !== "server") {
      root.append(message(context, "当前 Profile 不是服务器运行", "客户端运行的 Skill 由客户端随应用管理。"));
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
    status.className = "settings-muted";
    const actions = document.createElement("div");
    actions.className = "settings-inline-actions";
    const start = document.createElement("button");
    start.className = "primary";
    start.textContent = context.t("启动 Agent");
    const stop = document.createElement("button");
    stop.className = "secondary";
    stop.textContent = context.t("停止 Agent");
    actions.append(start, stop);
    const transcript = document.createElement("div");
    transcript.className = "profile-agent-transcript";
    const composer = document.createElement("textarea");
    composer.className = "profile-agent-composer";
    composer.placeholder = context.t("输入要交给 Agent 的研究问题…");
    composer.rows = 4;
    const send = document.createElement("button");
    send.className = "primary";
    send.textContent = context.t("发送消息");
    const composerRow = document.createElement("div");
    composerRow.className = "settings-inline-actions";
    composerRow.append(composer, send);
    root.append(note, status, actions, transcript, composerRow);

    const oldSource = sources.get(profile.profile_id);
    oldSource?.close();
    sources.delete(profile.profile_id);
    let cursor = 0;
    let thread = "";
    let selectedSkills = [];

    function connect() {
      const url = `/api/client/profile-agent/events?profile_id=${encodeURIComponent(profile.profile_id)}&after=${cursor}`;
      const source = new EventSource(url);
      sources.set(profile.profile_id, source);
      source.onmessage = event => {
        if (event.lastEventId) cursor = Number(event.lastEventId) || cursor;
        try { addEvent(context, transcript, JSON.parse(event.data)); } catch (_) { return; }
      };
      source.onerror = () => { status.textContent = context.t("对话连接已断开"); };
    }

    async function loadSkills() {
      const payload = await context.api(
        `/api/client/profile-skills?profile_id=${encodeURIComponent(profile.profile_id)}`,
      );
      selectedSkills = (payload.skills || [])
        .filter(item => item.selected)
        .map(item => item.skill_id);
    }

    async function ensureThread() {
      if (thread) return;
      const response = await context.api("/api/client/profile-agent/rpc", {
        method: "POST",
        body: JSON.stringify({profile_id: profile.profile_id, method: "thread/start", params: {}}),
      });
      thread = threadID(response);
      if (!thread) throw new Error(context.t("Agent 启动失败"));
    }

    async function refreshStatus() {
      const payload = await context.api(
        `/api/client/profile-agent?profile_id=${encodeURIComponent(profile.profile_id)}`,
      );
      const running = Boolean(payload.status?.running);
      start.disabled = running;
      stop.disabled = !running;
      send.disabled = !running;
      status.textContent = running ? context.t("Agent 已启动") : context.t("Agent 尚未启动");
      if (running) {
        await loadSkills();
        await ensureThread();
        if (!sources.get(profile.profile_id)) connect();
      }
    }

    start.onclick = async () => {
      start.disabled = true;
      status.textContent = context.t("正在启动 Agent…");
      try {
        await context.api("/api/client/profile-agent/start", {
          method: "POST", body: JSON.stringify({profile_id: profile.profile_id}),
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
          method: "POST", body: JSON.stringify({profile_id: profile.profile_id}),
        });
        sources.get(profile.profile_id)?.close();
        sources.delete(profile.profile_id);
        thread = "";
        await refreshStatus();
      } catch (error) {
        status.textContent = error.message || context.t("停止 Agent");
      }
    };
    send.onclick = async () => {
      const prompt = composer.value.trim();
      if (!prompt) return;
      send.disabled = true;
      status.textContent = context.t("正在发送…");
      try {
        await ensureThread();
        await context.api("/api/client/profile-agent/rpc", {
          method: "POST",
          body: JSON.stringify({
            profile_id: profile.profile_id,
            method: "turn/start",
            params: {threadId: thread, prompt, skill_ids: selectedSkills},
          }),
        });
        composer.value = "";
        status.textContent = context.t("Agent 已启动");
      } catch (error) {
        status.textContent = error.message || context.t("发送消息");
      } finally {
        send.disabled = false;
      }
    };
    start.disabled = true;
    stop.disabled = true;
    send.disabled = true;
    refreshStatus().catch(error => {
      status.textContent = error.message || context.t("Agent 启动失败");
    });
    return root;
  }

  window.FTAgentChat = {render};
})();
