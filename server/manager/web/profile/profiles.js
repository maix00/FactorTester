(() => {
  let cached = [];

  function current(context) {
    return context.isRouteCurrent?.() !== false;
  }

  function isSelfProfile(profile) {
    return profile?.profile_kind === "self" || profile?.profile_id === "self";
  }

  function profileName(context, profile) {
    return profile.display_name || profile.profile_id;
  }

  function selfBadge(context) {
    const badge = document.createElement("span");
    badge.className = "profile-self-badge";
    badge.textContent = context.t("本人身份");
    return badge;
  }

  function profileIdentity(context, profile) {
    const identity = document.createElement("div");
    identity.className = "profile-directory-identity";
    const name = document.createElement("strong");
    name.textContent = profileName(context, profile);
    identity.append(name);
    if (isSelfProfile(profile)) identity.append(selfBadge(context));
    return identity;
  }

  async function list(context, options = {}) {
    if (window.FTProfileDirectory?.list) {
      return window.FTProfileDirectory.list(context, options);
    }
    const embedded = Boolean(options.embedded);
    const nav = options.nav || "research";
    const heading = options.heading || "研究身份";
    if (!embedded) {
      context.activeNav(nav);
      if (options.heading) {
        context.setHeading(context.t(heading), context.t("本地研究身份"));
      } else {
        context.setHeading(context.t("研究身份"), context.t("本地研究身份"));
      }
    }
    context.content.replaceChildren(FTUI.loading(context.t("正在读取本地 Profiles…")));
    const payload = await context.api("/api/client/profiles");
    if (!current(context)) return;
    cached = payload.profiles || [];
    const create = context.button(
      "+", () => openCreate(context, options),
      context.t("创建独立 Profile"),
    );
    create.className = "primary";
    context.toolbar.append(create);
    if (!embedded) {
      context.toolbar.append(FTUI.refreshButton(
        context, () => list(context, options),
      ));
    }
    if (!cached.length) {
      context.content.replaceChildren(FTUI.empty(
        context.t("尚无已注册研究身份"),
        context.t("尚无已注册 Profile。可在下方创建，注册完成后会立即显示。"),
      ));
      return;
    }
    const view = FTUI.table([context.t("研究身份"), context.t("标识"), context.t("运行方式"), context.t("执行位置"), context.t("认领状态")], cached.map(item => [
      profileIdentity(context, item), item.profile_id,
      runtimeLabel(context, item.runtime), item.runtime?.executor_id || "",
      claimLabel(context, item.active_claim),
    ]));
    [...view.body.rows].forEach((row, index) => {
      if (isSelfProfile(cached[index])) {
        row.classList.add("profile-directory-row-self");
      }
      row.dataset.href = "true";
      row.addEventListener("click", () => {
        const profileID = encodeURIComponent(cached[index].profile_id);
        // A Profile is a durable research identity, not a subsection of the
        // research list.  Always open its own closable detail tab so the
        // four detail tabs keep their state independently of the list.
        context.navigate(`/profiles/${profileID}`);
      });
    });
    context.content.replaceChildren(view.shell);
  }

  async function detail(context, profileID, options = {}) {
    const profileKey = new URLSearchParams(location.search).get("profile_key");
    if (profileKey && window.FTProfileDirectory?.detail) {
      return window.FTProfileDirectory.detail(context, profileID, options);
    }
    const embedded = Boolean(options.embedded);
    if (!embedded) context.activeNav("research");
    // The list may have been rendered from a stale local/peer projection.
    // Reload when entering a detail tab so synced agents, workspaces and
    // research records are not permanently hidden by the module cache.
    const payload = await context.api("/api/client/profiles");
    if (!current(context)) return;
    cached = payload.profiles || [];
    const profile = cached.find(item => item.profile_id === profileID);
    if (!profile) throw new Error(context.t("Profile 不存在或不属于当前账户"));
    const root = document.createElement("div"); root.className = "detail-stack";
    if (!embedded) {
      context.setHeading(profileName(context, profile), `${context.t("研究身份")} · ${profile.profile_id}`);
      context.updateActiveTab?.({
        title: profileName(context, profile),
      });
      context.toolbar.append(context.button(
        "‹", () => context.navigate("/research?section=profiles"),
        context.t("返回研究身份")
      ));
    } else {
      const actions = document.createElement("div");
      actions.className = "detail-actions";
      actions.append(context.button(
        "‹", () => context.navigate("/research?section=profiles"),
        context.t("返回研究身份")
      ));
      root.append(actions);
    }
    const runtime = profile.runtime || {};
    const claim = profile.active_claim || null;
    const selectedTab = selectedProfileTab();
    root.append(profileTabBar(context, profileID, embedded, selectedTab));
    const refresh = async () => {
      const payload = await context.api("/api/client/profiles");
      cached = payload.profiles || [];
      await detail(context, profileID, options);
    };
    if (selectedTab === "overview") {
      root.append(FTUI.table([context.t("字段"), context.t("值")], FTUI.fieldRows({
        profile_id: profile.profile_id, display_name: profile.display_name,
        workspace_root: profile.workspace_root || context.t("路径由服务器保护"),
        server: profile.server?.base_url || context.t("未配置"),
        principal: profile.session_binding?.principal_ref,
        runtime_kind: runtimeLabel(context, runtime),
        executor_id: runtime.executor_id || context.t("未绑定"),
        workspace_relpath: runtime.workspace_relpath || context.t("未配置"),
        claim: claimLabel(context, claim),
        agent_id: claim?.agent_id || context.t("无"),
      })).shell);
      root.append(agentActions(context, profile, refresh));
      const projectionNote = document.createElement("p");
      projectionNote.className = "settings-muted profile-projection-note";
      projectionNote.textContent = context.t(
        "详情显示 Profile 元数据与运行绑定；技能、Agent 会话和工作区按选项卡读取。",
      );
      root.append(projectionNote);
      const agents = (profile.agents || []).map(item => [
        item.agent_id, item.role, item.status, item.next_action,
      ]);
      if (!agents.length && claim?.agent_id) {
        agents.push([
          claim.agent_id, context.t("研究 Agent"), claim.status || context.t("运行中"),
          context.t("由当前认领会话提供"),
        ]);
      }
      const workspaces = (profile.workspaces || []).map(item => [
        item.workspace_id, item.access_mode, FTUI.userDisplay(item.owner_ref, item.owner_alias), item.server_workspace_ref,
      ]);
      if (!workspaces.length && runtime.workspace_relpath) {
        workspaces.push([
          runtime.workspace_relpath, context.t("服务器工作区"),
          profile.session_binding?.principal_ref || "",
          runtime.server_id || runtime.executor_id || "",
        ]);
      }
      const agentSection = section(
        context, "Agents",
        ["Agent", context.t("角色"), context.t("状态"), context.t("下一步")], agents,
      );
      const workspaceSection = section(
        context, context.t("工作区"),
        [context.t("工作区"), context.t("访问模式"), context.t("所有者"), context.t("服务端引用")],
        workspaces,
      );
      [agentSection, workspaceSection]
        .filter(Boolean)
        .forEach(item => root.append(item));
    } else if (selectedTab === "skills") {
      if (window.FTAgentSkills?.render) {
        root.append(await window.FTAgentSkills.render(context, profile, refresh));
      }
    } else if (selectedTab === "session") {
      const session = sessionSection(context, claim);
      if (session) root.append(session);
      if (window.FTAgentChat?.render) {
        root.append(await window.FTAgentChat.render(context, profile));
      }
    } else if (window.FTProfileWorkspace?.render) {
      root.append(window.FTProfileWorkspace.render(context, profile));
    }
    context.content.replaceChildren(root);
  }

  function sessionSection(context, claim) {
    const rows = claim ? FTUI.fieldRows({
      claim: claimLabel(context, claim),
      agent_id: claim.agent_id,
      provider_id: claim.provider_id,
      runtime_kind: claim.runtime_kind,
      executor_id: claim.executor_id,
      status: claim.status,
      claimed_at: claim.claimed_at,
      last_heartbeat_at: claim.last_heartbeat_at,
    }) : [];
    return section(
      context,
      "Agent 会话",
      [context.t("字段"), context.t("值")],
      rows,
    );
  }

  function formField(context, label, control) {
    const row = document.createElement("div");
    row.className = "settings-row";
    const title = document.createElement("b");
    title.textContent = context.t(label);
    const value = document.createElement("div");
    value.className = "settings-value";
    value.append(control);
    row.append(title, value);
    return row;
  }

  async function openCreate(context, options = {}) {
    const embedded = Boolean(options.embedded);
    const dialog = document.createElement("dialog");
    dialog.className = "profile-create-dialog";
    dialog.dataset.ftTabID = context.tabID || "";
    const card = document.createElement("form");
    card.method = "dialog";
    card.className = "dialog-card profile-create-card";
    const heading = document.createElement("h2");
    heading.textContent = context.t("创建独立 Profile");
    const note = document.createElement("p");
    note.className = "settings-muted";
    note.textContent = context.t(
      "Profile 只绑定当前登录身份；创建后再从服务器授权列表选择初始化因子库。",
    );
    const profileID = document.createElement("input");
    profileID.className = "inline-setting";
    profileID.type = "text";
    profileID.required = true;
    profileID.autocomplete = "off";
    profileID.autocapitalize = "off";
    profileID.spellcheck = false;
    profileID.placeholder = "maxc";
    const displayName = document.createElement("input");
    displayName.className = "inline-setting";
    displayName.type = "text";
    displayName.required = true;
    displayName.autocomplete = "off";
    displayName.placeholder = "MaxC";
    const runtime = document.createElement("span");
    runtime.className = "settings-muted";
    runtime.textContent = context.t("服务器运行");
    const status = document.createElement("p");
    status.className = "settings-muted";
    const actions = document.createElement("div");
    actions.className = "dialog-actions";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "secondary";
    cancel.textContent = context.t("取消");
    const save = document.createElement("button");
    save.type = "submit";
    save.className = "primary";
    save.textContent = context.t("保存 Profile");
    actions.append(cancel, save);
    card.append(
      heading, note,
      formField(context, "标识", profileID),
      formField(context, "显示名称", displayName),
      formField(context, "运行方式", runtime),
      actions, status,
    );
    dialog.append(card);
    document.body.append(dialog);
    const close = () => {
      if (dialog.open) dialog.close();
      dialog.remove();
    };
    cancel.addEventListener("click", close);
    dialog.addEventListener("close", () => dialog.remove(), {once: true});
    dialog.showModal();
    card.addEventListener("submit", async event => {
      event.preventDefault();
      const identifier = profileID.value.trim();
      const label = displayName.value.trim();
      if (identifier === "self") {
        status.textContent = context.t("self 是系统保留的本人研究身份标识");
        return;
      }
      if (!/^[a-z0-9][a-z0-9._-]{0,63}$/.test(identifier) || !label) {
        status.textContent = context.t(
          "Profile 标识只能使用小写字母、数字、点、下划线或短横线；显示名称不能为空",
        );
        return;
      }
      save.disabled = true;
      cancel.disabled = true;
      status.textContent = context.t("正在保存…");
      try {
        const receipt = await context.api("/api/client/profiles/create", {
          method: "POST",
          body: JSON.stringify({profile_id: identifier, display_name: label}),
        });
        const refreshed = await context.api("/api/client/profiles");
        if (!current(context)) {
          close();
          return;
        }
        cached = refreshed.profiles || [];
        close();
        if (receipt.pending) {
          context.showNotice(context.t(
            "研究身份已在本地创建，等待中央数据库同步",
          ));
        }
        context.navigate(
          embedded
            ? `/research?section=profiles&profile=${encodeURIComponent(identifier)}`
            : `/profiles/${encodeURIComponent(identifier)}`,
        );
      } catch (error) {
        status.textContent = error.status === 409
          ? context.t("该研究身份标识已经存在")
          : (error.message || context.t("保存失败"));
        save.disabled = false;
        cancel.disabled = false;
      }
    });
  }

  function runtimeLabel(context, runtime) {
    if (!runtime || !runtime.runtime_kind) return context.t("未配置");
    const label = runtime.runtime_kind === "server"
      ? context.t("服务器运行") : context.t("客户端运行");
    return runtime.configured === false ? `${label} · ${context.t("未绑定")}` : label;
  }

  function claimLabel(context, claim) {
    return claim ? context.t("已认领") : context.t("未认领");
  }

  const PROFILE_TABS = [
    ["overview", "详情"],
    ["skills", "技能管理"],
    ["session", "Agent 会话"],
    ["workspace", "工作区"],
  ];

  function selectedProfileTab() {
    const value = new URLSearchParams(location.search).get("profile_tab");
    return PROFILE_TABS.some(([id]) => id === value) ? value : "overview";
  }

  function profileTabBar(context, profileID, embedded, selected) {
    const nav = document.createElement("nav");
    nav.className = "profile-detail-tabs";
    nav.setAttribute("aria-label", context.t("研究身份详情"));
    PROFILE_TABS.forEach(([id, label]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `profile-detail-tab${id === selected ? " active" : ""}`;
      button.textContent = context.t(label);
      button.setAttribute("aria-current", id === selected ? "page" : "false");
      button.onclick = () => {
        const encoded = encodeURIComponent(profileID);
        const path = `/profiles/${encoded}?profile_tab=${id}`;
        context.navigate(path);
      };
      nav.append(button);
    });
    return nav;
  }

  function agentActions(context, profile, refresh) {
    const root = document.createElement("section");
    root.className = "job-section profile-agent-actions";
    const heading = document.createElement("h2");
    heading.textContent = context.t("智能体运行");
    const note = document.createElement("p");
    note.className = "settings-muted";
    note.textContent = context.t("一个研究身份只能由一个客户端或一个服务器 Agent 认领；Agent 直接使用该 Profile 的正式工作区，不创建临时副本。");
    const controls = document.createElement("div");
    controls.className = "settings-inline-actions";
    const runtime = profile.runtime || {};
    const runtimeSelect = document.createElement("select");
    runtimeSelect.className = "inline-setting";
    [
      ["client", context.t("客户端运行")],
      ["server", context.t("服务器运行")],
    ].forEach(([value, label]) => {
      const option = document.createElement("option");
      option.value = value; option.textContent = label;
      option.selected = runtime.runtime_kind === value;
      runtimeSelect.append(option);
    });
    const bind = document.createElement("button");
    bind.className = "secondary";
    bind.textContent = context.t("绑定运行位置");
    const status = document.createElement("p");
    status.className = "settings-muted";
    status.setAttribute("aria-live", "polite");
    bind.onclick = async () => {
      bind.disabled = true;
      status.textContent = context.t("正在绑定运行位置…");
      try {
        await context.api("/api/client/profile-runtime", {
          method: "POST",
          body: JSON.stringify({
            profile_id: profile.profile_id,
            runtime_kind: runtimeSelect.value,
            executor_id: runtimeSelect.value === "server" ? "" : runtime.executor_id,
          }),
        });
        status.textContent = context.t("运行位置已绑定，工作区已创建");
        context.showNotice(context.t("运行位置绑定成功"));
        await refresh();
      } catch (error) {
        status.textContent = error.message || context.t("运行位置绑定失败");
        context.showNotice(status.textContent, true);
      } finally {
        bind.disabled = false;
      }
    };
    controls.append(runtimeSelect, bind);

    const provider = document.createElement("select");
    provider.className = "inline-setting";
    const claim = profile.active_claim;
    const claimButton = document.createElement("button");
    claimButton.className = "primary";
    claimButton.textContent = claim ? context.t("释放认领") : context.t("认领 Agent");
    claimButton.disabled = !claim && runtime.configured === false;
    const loadProviders = async () => {
      provider.replaceChildren();
      const payload = await context.api(
        `/api/client/agent-models?runtime_kind=${encodeURIComponent(runtime.runtime_kind || "server")}`,
      );
      const values = payload.providers || [];
      values.forEach(item => {
        const option = document.createElement("option");
        option.value = item.provider_id;
        option.textContent = `${item.label} · ${item.default_model}`;
        provider.append(option);
      });
      claimButton.disabled = Boolean(claim) || runtime.configured === false || !values.length;
      if (!values.length && !claim) {
        const option = document.createElement("option");
        option.textContent = context.t("请先保存模型服务");
        option.disabled = true; option.selected = true;
        provider.append(option);
      }
    };
    provider.onchange = () => {
      claimButton.disabled = Boolean(claim)
        || runtime.configured === false || !provider.value;
    };
    claimButton.onclick = async () => {
      claimButton.disabled = true;
      status.textContent = claim
        ? context.t("正在释放 Agent 认领…")
        : context.t("正在认领 Agent…");
      try {
        if (claim) {
          await context.api("/api/client/profile-claims/release", {
            method: "POST",
            body: JSON.stringify({claim_id: claim.claim_id, agent_id: claim.agent_id}),
          });
        } else {
          await context.api("/api/client/profile-claims", {
            method: "POST",
            body: JSON.stringify({profile_id: profile.profile_id, provider_id: provider.value}),
          });
        }
        status.textContent = claim
          ? context.t("Agent 已释放")
          : context.t("Agent 已认领");
        context.showNotice(claim
          ? context.t("Agent 认领已释放")
          : context.t("Agent 认领成功"));
        await refresh();
      } catch (error) {
        status.textContent = error.message || context.t("Agent 操作失败");
        context.showNotice(status.textContent, true);
        claimButton.disabled = false;
      }
    };
    controls.append(provider, claimButton);
    root.append(heading, note, controls, status);
    if (!claim) loadProviders().catch(error => {
      const warning = document.createElement("p");
      warning.className = "settings-muted";
      warning.textContent = error.message || context.t("模型服务读取失败");
      root.append(warning);
    });
    return root;
  }

  function section(context, title, headers, rows) {
    if (!rows.length) return null;
    const root = document.createElement("section"); root.className = "job-section";
    const heading = document.createElement("h2"); heading.textContent = title; root.append(heading);
    root.append(FTUI.table(headers, rows).shell);
    return root;
  }

  window.FTProfiles = {
    detail,
    list,
    // The directory detail reuses the established binding UI for the
    // current user's Profile; remote rows never receive this capability.
    renderBinding: agentActions,
  };
})();
