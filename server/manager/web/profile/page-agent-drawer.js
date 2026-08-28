(() => {
  function attach(context, options = {}) {
    const shell = document.createElement("aside");
    shell.className = "page-agent-drawer";
    shell.dataset.ftPageAgentTab = context.tabID;
    shell.hidden = true;
    shell.setAttribute("role", "dialog");
    shell.setAttribute("aria-label", context.t("页面智能体助手"));
    const header = document.createElement("header");
    const heading = document.createElement("strong");
    heading.textContent = options.title || context.t("智能体助手");
    const close = document.createElement("button");
    close.type = "button";
    close.className = "page-agent-drawer-close";
    close.textContent = "×";
    close.setAttribute("aria-label", context.t("收起"));
    const body = document.createElement("div");
    body.className = "page-agent-drawer-body";
    header.append(heading, close);
    shell.append(header, body);
    (options.host || document.body).append(shell);

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "page-agent-drawer-toggle";
    toggle.replaceChildren(FTIcons.node("person.crop.rectangle.stack"));
    toggle.title = options.buttonLabel || context.t("智能体助手");
    toggle.setAttribute("aria-label", toggle.title);
    toggle.dataset.ftPageAgentTab = context.tabID;
    document.body.append(toggle);

    let mounted = false;
    let opening = null;
    let bridge = null;
    let profileID = "";
    const status = text => {
      const value = document.createElement("p");
      value.className = "page-agent-drawer-status";
      value.textContent = context.t(text);
      body.replaceChildren(value);
    };
    const registration = context.pageState?.register?.("page-agent-drawer", {
      // Drawer visibility is intentionally ephemeral. Restoring an open
      // drawer would start Profile resolution, Agent startup and ChatKit while
      // the page itself is still restoring, recreating the eager-load race
      // this shared boundary exists to prevent.
      capture: () => ({profile_id: profileID}),
      restore: () => {},
      describe: () => ({
        page: options.pageKind || "",
        section: options.section || "",
        fields: [],
        agent_profile_id: profileID,
      }),
      dispose: () => {
        bridge?.dispose();
        shell.remove();
        toggle.remove();
      },
    });

    async function open() {
      shell.hidden = false;
      toggle.hidden = true;
      toggle.setAttribute("aria-expanded", "true");
      if (mounted) return;
      if (!opening) {
        opening = (async () => {
          status("正在加载智能体助手…");
          const [profile] = await Promise.all([
            options.resolveProfile?.() || options.profile,
            window.FTStaticLoader?.loadGroups?.(["profile"]),
            options.assistance.prepare?.(),
          ]);
          profileID = String(profile?.profile_id || "").trim();
          if (!profileID) throw new Error(context.t("页面 Agent 缺少 Profile"));
          await context.pageAgentLifecycle.open(profileID, context.tabID);
          bridge = window.FTPageAgentContext.create(
            context, profileID, options.assistance, {isActive: () => !shell.hidden},
          );
          await bridge.start();
          const chat = await window.FTAgentChat.render(context, profile, {
            conversationOnly: true,
            lifecycleManaged: true,
            profileKey: options.profileKey,
            profileScope: options.profileScope,
          });
          body.classList.add("page-agent-drawer-body-conversation-only");
          body.replaceChildren(chat);
          mounted = true;
        })().catch(error => {
          bridge?.dispose();
          bridge = null;
          if (profileID) context.pageAgentLifecycle.hide(profileID, context.tabID);
          status(`智能体助手加载失败：${String(error?.message || error)}`);
        }).finally(() => { opening = null; });
      }
      return opening;
    }

    function hide() {
      shell.hidden = true;
      toggle.hidden = false;
      toggle.setAttribute("aria-expanded", "false");
      bridge?.pause();
      if (profileID) context.pageAgentLifecycle.hide(profileID, context.tabID);
      context.checkpointTabSession?.();
    }

    toggle.addEventListener("click", () => shell.hidden ? void open() : hide());
    close.addEventListener("click", hide);
    return Object.freeze({hide, open, registration, shell, toggle});
  }

  window.FTPageAgentDrawer = Object.freeze({attach});
})();
