(() => {
  function attach(context, options = {}) {
    const profile = options.profile || {};
    const profileID = String(profile.profile_id || "").trim();
    if (!profileID) throw new Error(context.t("页面 Agent 缺少 Profile"));

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
    toggle.textContent = options.buttonLabel || context.t("智能体助手");
    (options.buttonHost || context.toolbar || context.content).append(toggle);

    let mounted = false;
    let opening = null;
    let bridge = null;
    const registration = context.pageState?.register?.("page-agent-drawer", {
      capture: () => ({open: !shell.hidden, profile_id: profileID}),
      restore: value => {
        if (value?.open) queueMicrotask(() => { void open(); });
      },
      describe: () => ({
        page: options.pageKind || "",
        section: options.section || "",
        fields: [],
        agent_profile_id: profileID,
      }),
      dispose: () => {
        bridge?.dispose();
        shell.remove();
      },
    });

    async function open() {
      shell.hidden = false;
      toggle.setAttribute("aria-expanded", "true");
      if (mounted) return;
      if (!opening) {
        opening = (async () => {
          await context.pageAgentLifecycle.open(profileID, context.tabID);
          bridge = window.FTPageAgentContext.create(context, profileID);
          await bridge.start();
          await window.FTStaticLoader?.ensureGroup?.("profile");
          const chat = await window.FTAgentChat.render(context, profile, {
            lifecycleManaged: true,
            profileKey: options.profileKey,
            profileScope: options.profileScope,
          });
          body.replaceChildren(chat);
          mounted = true;
        })().finally(() => { opening = null; });
      }
      return opening;
    }

    function hide() {
      shell.hidden = true;
      toggle.setAttribute("aria-expanded", "false");
      context.pageAgentLifecycle.hide(profileID, context.tabID);
      context.checkpointTabSession?.();
    }

    toggle.addEventListener("click", () => shell.hidden ? void open() : hide());
    close.addEventListener("click", hide);
    return Object.freeze({hide, open, registration, shell, toggle});
  }

  window.FTPageAgentDrawer = Object.freeze({attach});
})();
