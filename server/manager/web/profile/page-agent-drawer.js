(() => {
  const drawers = new Map();
  const pages = new Map();
  const DRAWER_ID = "global-agent-drawer";
  let activeContext = null;
  let globalToggle = null;
  let suppressClick = false;

  function headerBoundary() {
    const bottom = Number(document.querySelector(".topbar")?.getBoundingClientRect?.().bottom);
    return Number.isFinite(bottom) ? Math.max(0, bottom) : 0;
  }

  function applyDrawerBoundary(shell) {
    if (!shell) return;
    const top = Math.max(16, headerBoundary() + 8);
    shell.style.top = `${top}px`;
    shell.style.bottom = "16px";
  }

  function positionKey(context) {
    return `ft-page-agent-toggle-y:${String(context?.tabID || location.pathname)}`;
  }

  function clampPosition(value) {
    const half = (globalToggle?.getBoundingClientRect?.().height || 56) / 2;
    const minimum = headerBoundary() + 8 + half;
    return Math.max(minimum, Math.min(window.innerHeight - half - 8, value));
  }

  function applyPosition(context) {
    if (!globalToggle) return;
    const saved = localStorage.getItem(positionKey(context));
    const value = saved === null ? NaN : Number(saved);
    globalToggle.style.top = `${clampPosition(Number.isFinite(value) ? value : 0)}px`;
  }

  function ensureToggle(context) {
    activeContext = context || activeContext;
    if (globalToggle?.isConnected) {
      applyPosition(activeContext);
      return globalToggle;
    }
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "page-agent-drawer-toggle";
    toggle.replaceChildren(FTIcons.node("person.crop.rectangle.stack"));
    toggle.title = context.t("智能体助手");
    toggle.setAttribute("aria-label", toggle.title);
    toggle.setAttribute("aria-expanded", "false");
    document.body.append(toggle);
    let pointerID = null;
    let startY = 0;
    let moved = false;
    toggle.addEventListener("pointerdown", event => {
      pointerID = event.pointerId; startY = event.clientY; moved = false;
      toggle.setPointerCapture?.(pointerID);
    });
    toggle.addEventListener("pointermove", event => {
      if (event.pointerId !== pointerID) return;
      if (Math.abs(event.clientY - startY) > 3) moved = true;
      if (!moved) return;
      const top = clampPosition(event.clientY);
      toggle.style.top = `${top}px`;
    });
    const finishDrag = event => {
      if (event.pointerId !== pointerID) return;
      if (moved) {
        localStorage.setItem(positionKey(activeContext), String(clampPosition(event.clientY)));
        suppressClick = true;
      }
      pointerID = null;
    };
    toggle.addEventListener("pointerup", finishDrag);
    toggle.addEventListener("pointercancel", finishDrag);
    toggle.addEventListener("click", () => {
      if (suppressClick) { suppressClick = false; return; }
      let drawer = drawers.get(DRAWER_ID);
      if (!drawer && activeContext) {
        const context = activeContext;
        drawer = attach(context, {
          resolveProfiles: () => window.FTPageAgentProfiles.forPage(context),
          resolveProfile: () => window.FTPageAgentProfiles.self(context),
          assistanceEnabled: false,
        });
      }
      void drawer?.open();
    });
    globalToggle = toggle;
    applyPosition(activeContext);
    return toggle;
  }

  function activate(context) {
    activeContext = context;
    void window.FTPageAssistance?.resume?.(context);
    const toggle = ensureToggle(context);
    const current = drawers.get(DRAWER_ID);
    if (current) current.updatePage(context, pages.get(String(context?.tabID || "")) || {
      resolveProfiles: () => window.FTPageAgentProfiles.forPage(context),
      resolveProfile: () => window.FTPageAgentProfiles.self(context),
      assistanceEnabled: false,
    });
    const open = current?.shell?.dataset.ftPageAgentDesiredOpen === "true";
    if (current) {
      applyDrawerBoundary(current.shell);
      current.shell.hidden = !open;
    }
    toggle.hidden = Boolean(open);
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    applyPosition(context);
  }

  function attach(context, options = {}) {
    const pageID = String(context.tabID || "");
    const pageOptions = options;
    pages.set(pageID, pageOptions);
    context.pageState?.register?.("page-agent-scope", {
      capture: () => null, restore() {},
      dispose() {
        if (pages.get(pageID) === pageOptions) pages.delete(pageID);
        pageOptions.assistance?.disconnect?.();
      },
    });
    const tabID = DRAWER_ID;
    const previous = drawers.get(tabID);
    if (previous) { previous.updatePage(context, options); return previous; }
    const shell = document.createElement("aside");
    shell.className = "page-agent-drawer";
    // The tab view cache must never park or dispose the application drawer.
    shell.dataset.ftGlobalAgentDrawer = "true";
    shell.dataset.ftPageAgentRole = "drawer";
    shell.hidden = true;
    shell.setAttribute("role", "dialog");
    shell.setAttribute("aria-label", context.t("页面智能体助手"));
    applyDrawerBoundary(shell);
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
    document.body.append(shell);

    const toggle = ensureToggle(context);

    let workspaceReceiver = null;
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
    ).trim() + (profile?.runtime_bound_here === false
      ? ` · ${context.t("未绑定当前服务器/客户端")}` : "");
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
      options.assistance?.disconnect?.();
      workspaceReceiver?.dispose();
      workspaceReceiver = null;
      options.onProfileChange?.(profile);
      profileID = nextID;
      activeProfile = profile;
      body.querySelector?.("[data-ft-keep-connected-on-tab-save]")?.__ftBeforeTabSave?.();
      mounted = false;
      opening = null;
      body.classList.remove("page-agent-drawer-body-conversation-only");
      renderProfileSelector();
      await mountConversation();
      context.checkpointTabSession?.();
    }
    let pageGeneration = 0;
    function updatePage(nextContext, nextOptions) {
      if (context === nextContext && options === nextOptions) return;
      options.assistance?.disconnect?.();
      workspaceReceiver?.dispose(); workspaceReceiver = null;
      context = nextContext; options = nextOptions;
      const generation = ++pageGeneration;
      // Page scope changes the selector and authoring receiver, never the
      // mounted chat or its stream. A research profile can keep chatting but
      // receives no write receiver for an unrelated page.
      if (!mounted && !opening) return;
      void Promise.resolve(options.resolveProfiles?.() || []).then(async profiles => {
        if (generation !== pageGeneration) return;
        selectableProfiles = profiles;
        renderProfileSelector();
        if (!profiles.some(item => String(item.profile_id) === profileID)) return;
        options.onProfileChange?.(activeProfile);
        if (options.assistanceEnabled !== false) await options.assistance?.connect?.();
      }).catch(() => {});
    }
    const registration = null;

    async function mountConversation() {
      if (mounted) return;
      if (!opening) {
        const mountContext = context;
        const mountOptions = options;
        opening = (async () => {
          status("正在加载智能体助手…");
          if (!selectableProfiles.length && mountOptions.resolveProfiles) {
            selectableProfiles = await mountOptions.resolveProfiles();
          }
          const profile = activeProfile || selectableProfiles.find(
            item => String(item.profile_id || "") === profileID,
          ) || await (mountOptions.resolveProfile?.() || mountOptions.profile);
          activeProfile = profile;
          profileID = String(profile?.profile_id || "").trim();
          if (!profileID) throw new Error(mountContext.t("页面 Agent 缺少 Profile"));
          if (!selectableProfiles.length) selectableProfiles = [profile];
          renderProfileSelector();
          if (profile?.runtime_bound_here === false) {
            status("该 Profile 未绑定当前服务器/客户端");
            mounted = true;
            return;
          }
          const lifecycle = await mountContext.pageAgentLifecycle.open(profileID, DRAWER_ID);
          body.classList.add("page-agent-drawer-body-conversation-only");
          const assistanceReady = mountOptions.assistanceEnabled !== false
            && mountOptions.assistance?.connect
            ? mountOptions.assistance.connect()
            : (async () => {
              if (!mountContext.assistanceWorkspace) return;
              workspaceReceiver?.dispose();
              workspaceReceiver = window.FTPageAgentContext.create(mountContext, profileID, {
                snapshot: () => ({schema_version: 1, page_kind: "read-only",
                  revision: 0, document: {}, document_schema: {type: "object", additionalProperties: false},
                  navigation: {schema_version: 1, root_id: "page", nodes: {
                    page: {id: "page", kind: "page", children: []},
                  }}}),
              });
              await workspaceReceiver.start();
            })();
          const chatReady = window.FTAgentChat.render({...mountContext, isRouteCurrent: () => true}, profile, {
            conversationOnly: true,
            lifecycleManaged: true,
            runtimeStatus: lifecycle.runtimeStatus,
            profileKey: mountOptions.profileKey,
            profileScope: mountOptions.profileScope,
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
      applyDrawerBoundary(shell);
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

    close.addEventListener("click", hide);
    profileButton.addEventListener("click", profileDetails);
    profileMenuButton.addEventListener("click", () => {
      profileMenu.hidden = !profileMenu.hidden;
    });
    const api = Object.freeze({hide, open, registration, shell, toggle, updatePage});
    drawers.set(tabID, api);
    if (activeContext?.tabID === context.tabID) activate(context);
    return api;
  }

  window.addEventListener("resize", () => {
    drawers.forEach(drawer => applyDrawerBoundary(drawer.shell));
    applyPosition(activeContext);
  });

  window.FTPageAgentDrawer = Object.freeze({
    activate, applyDrawerBoundary, attach, ensureGlobal: activate, headerBoundary,
  });
})();
