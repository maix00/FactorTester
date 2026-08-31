(() => {
  function attach(context, options = {}) {
    const shell = document.createElement("aside");
    shell.className = "page-agent-drawer";
    shell.dataset.ftPageAgentTab = context.tabID;
    shell.dataset.ftPageAgentRole = "drawer";
    shell.hidden = true;
    shell.setAttribute("role", "dialog");
    shell.setAttribute("aria-label", context.t("页面智能体助手"));
    const header = document.createElement("header");
    const title = document.createElement("div");
    title.className = "page-agent-drawer-title";
    const heading = document.createElement("strong");
    heading.textContent = options.title || context.t("智能体助手");
    const profileButton = document.createElement("button");
    profileButton.type = "button";
    profileButton.className = "page-agent-drawer-profile";
    profileButton.hidden = true;
    const profileMenuButton = document.createElement("button");
    profileMenuButton.type = "button";
    profileMenuButton.className = "page-agent-drawer-profile-menu-button";
    profileMenuButton.textContent = "▾";
    profileMenuButton.setAttribute("aria-label", context.t("切换研究身份"));
    profileMenuButton.hidden = true;
    const profileMenu = document.createElement("div");
    profileMenu.className = "page-agent-drawer-profile-menu";
    profileMenu.hidden = true;
    const close = document.createElement("button");
    close.type = "button";
    close.className = "page-agent-drawer-close";
    close.textContent = "×";
    close.setAttribute("aria-label", context.t("收起"));
    const body = document.createElement("div");
    body.className = "page-agent-drawer-body";
    title.append(heading, profileButton, profileMenuButton, profileMenu);
    header.append(title, close);
    shell.append(header, body);
    (options.host || document.body).append(shell);

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "page-agent-drawer-toggle";
    toggle.replaceChildren(FTIcons.node("person.crop.rectangle.stack"));
    toggle.title = options.buttonLabel || context.t("智能体助手");
    toggle.setAttribute("aria-label", toggle.title);
    toggle.dataset.ftPageAgentTab = context.tabID;
    toggle.dataset.ftPageAgentRole = "toggle";
    document.body.append(toggle);

    let mounted = false;
    let opening = null;
    let profileID = "";
    let activeProfile = null;
    let selectableProfiles = [];
    let desiredOpen = false;
    const setDesiredOpen = value => {
      desiredOpen = value === true;
      const serialized = desiredOpen ? "true" : "false";
      shell.dataset.ftPageAgentDesiredOpen = serialized;
      toggle.dataset.ftPageAgentDesiredOpen = serialized;
    };
    setDesiredOpen(false);
    const status = text => {
      const value = document.createElement("p");
      value.className = "page-agent-drawer-status";
      value.textContent = context.t(text);
      body.replaceChildren(value);
    };
    const profileLabel = profile => String(
      profile?.alias || profile?.title || profile?.name || profile?.profile_id || "",
    ).trim();
    const profileDetails = () => {
      if (!profileID) return;
      context.navigate?.(
        `/research?section=profiles&profile=${encodeURIComponent(profileID)}`,
      );
    };
    const renderProfileSelector = () => {
      profileButton.textContent = profileLabel(activeProfile);
      profileButton.hidden = !profileID;
      profileMenuButton.hidden = selectableProfiles.length < 2;
      profileMenu.replaceChildren(...selectableProfiles.map(profile => {
        const item = document.createElement("button");
        item.type = "button";
        item.textContent = profileLabel(profile);
        item.className = String(profile.profile_id) === profileID ? "active" : "";
        item.addEventListener("click", () => {
          profileMenu.hidden = true;
          void selectProfile(profile);
        });
        return item;
      }));
    };
    async function selectProfile(profile) {
      const nextID = String(profile?.profile_id || "").trim();
      if (!nextID || nextID === profileID) return;
      if (profileID) context.pageAgentLifecycle.hide(profileID, context.tabID);
      options.assistance.disconnect?.();
      options.onProfileChange?.(profile);
      profileID = nextID;
      activeProfile = profile;
      mounted = false;
      opening = null;
      body.classList.remove("page-agent-drawer-body-conversation-only");
      renderProfileSelector();
      await mountConversation();
      context.checkpointTabSession?.();
    }
    const registration = context.pageState?.register?.("page-agent-drawer", {
      // Preserve user intent rather than reading DOM visibility. The tab cache
      // temporarily hides both nodes while parking a view; that hidden state
      // must never overwrite an open drawer preference.
      capture: () => ({profile_id: profileID, open: desiredOpen}),
      restore: value => {
        profileID = String(value?.profile_id || profileID || "").trim();
        setDesiredOpen(value?.open === true);
        queueMicrotask(() => desiredOpen ? void open() : restoreClosed());
      },
      describe: () => ({
        page: options.pageKind || "",
        section: options.section || "",
        fields: [],
        agent_profile_id: profileID,
      }),
      dispose: () => {
        shell.remove();
        toggle.remove();
      },
    });

    async function mountConversation() {
      if (mounted) return;
      if (!opening) {
        opening = (async () => {
          status("正在加载智能体助手…");
          if (!selectableProfiles.length && options.resolveProfiles) {
            selectableProfiles = await options.resolveProfiles();
          }
          const profile = activeProfile || selectableProfiles.find(
            item => String(item.profile_id || "") === profileID,
          ) || await (options.resolveProfile?.() || options.profile);
          activeProfile = profile;
          profileID = String(profile?.profile_id || "").trim();
          if (!profileID) throw new Error(context.t("页面 Agent 缺少 Profile"));
          if (!selectableProfiles.length) selectableProfiles = [profile];
          renderProfileSelector();
          const lifecycle = await context.pageAgentLifecycle.open(profileID, context.tabID);
          body.classList.add("page-agent-drawer-body-conversation-only");
          const assistanceReady = options.assistance.connect
            ? options.assistance.connect()
            : Promise.resolve(options.assistance.prepare?.());
          const chatReady = window.FTAgentChat.render(context, profile, {
            conversationOnly: true,
            lifecycleManaged: true,
            runtimeStatus: lifecycle.runtimeStatus,
            profileKey: options.profileKey,
            profileScope: options.profileScope,
            mountHost: body,
          });
          const [chat] = await Promise.all([chatReady, assistanceReady]);
          if (!body.contains?.(chat)) body.replaceChildren(chat);
          mounted = true;
        })().catch(error => {
          if (profileID) context.pageAgentLifecycle.hide(profileID, context.tabID);
          status(`智能体助手加载失败：${String(error?.message || error)}`);
        }).finally(() => { opening = null; });
      }
      return opening;
    }

    async function open() {
      setDesiredOpen(true);
      shell.hidden = false;
      toggle.hidden = true;
      toggle.setAttribute("aria-expanded", "true");
      await window.FTStaticLoader?.loadGroups?.(["profile-agent-chat"]);
      return mountConversation();
    }

    function restoreClosed() {
      shell.hidden = true;
      toggle.hidden = false;
      toggle.setAttribute("aria-expanded", "false");
      if (profileID) context.pageAgentLifecycle.hide(profileID, context.tabID);
    }

    function hide() {
      setDesiredOpen(false);
      restoreClosed();
      context.checkpointTabSession?.();
    }

    shell.__ftRestorePageAgent = () => (
      desiredOpen ? void open() : restoreClosed()
    );

    toggle.addEventListener("click", () => shell.hidden ? void open() : hide());
    close.addEventListener("click", hide);
    profileButton.addEventListener("click", profileDetails);
    profileMenuButton.addEventListener("click", () => {
      profileMenu.hidden = !profileMenu.hidden;
    });
    return Object.freeze({hide, open, registration, shell, toggle});
  }

  window.FTPageAgentDrawer = Object.freeze({attach});
})();
