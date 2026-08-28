(() => {
  const TABS = [
    ["overview", "详情"],
    ["skills", "技能管理"],
    ["session", "Agent 会话"],
    ["workspace", "工作区"],
  ];

  function current(context) {
    return context.isRouteCurrent?.() !== false;
  }

  function text(value) {
    return value == null ? "" : String(value);
  }

  function params() {
    return new URLSearchParams(location.search);
  }

  function selectedTab() {
    const value = params().get("profile_tab");
    return TABS.some(item => item[0] === value) ? value : "overview";
  }

  function tabBar(context, profile, scope, tab) {
    const nav = document.createElement("nav");
    nav.className = "profile-detail-tabs";
    nav.setAttribute("aria-label", context.t("研究身份详情"));
    TABS.forEach(([id, label]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `profile-detail-tab${id === tab ? " active" : ""}`;
      button.textContent = context.t(label);
      button.setAttribute("aria-current", id === tab ? "page" : "false");
      button.onclick = () => {
        const query = new URLSearchParams({
          profile_key: text(profile.profile_key),
          profile_scope: scope,
          profile_tab: id,
        });
        context.navigate(`/profiles/${encodeURIComponent(profile.profile_id)}?${query}`);
      };
      nav.append(button);
    });
    return nav;
  }

  function fields(context, values) {
    return FTUI.table(
      [context.t("字段"), context.t("值")],
      Object.entries(values).filter(([, value]) => (
        value == null || ["string", "number", "boolean"].includes(typeof value)
      )).map(([key, value]) => [context.t(key), text(value)]),
    ).shell;
  }

  function note(context, value) {
    const element = document.createElement("p");
    element.className = "settings-muted profile-directory-note";
    element.textContent = context.t(value);
    return element;
  }

  function conversationAccessNote(context, profile) {
    if (profile.read_only && profile.capabilities?.view_conversations) {
      return note(
        context,
        "直属下级研究身份的 Agent 会话默认对直属上级只读可见；不会获得文件修改或 Agent 控制权限。",
      );
    }
    if (profile.capabilities?.edit === true) {
      return note(context, "当前研究身份可以管理自己的 Agent 会话。直属上级查看时始终为只读。");
    }
    return note(context, "该研究身份及其 Agent 会话对当前用户不可见。");
  }

  function overview(context, profile) {
    const root = document.createElement("div");
    root.className = "detail-stack";
    root.append(fields(context, {
      profile_id: profile.profile_id,
      profile_kind: profile.profile_kind,
      display_name: profile.display_name,
      owner_ref: profile.owner_ref,
      owner_alias: profile.owner_alias,
      source_server_id: profile.source_server_id,
      source_server_ids: Array.isArray(profile.source_server_ids)
        ? profile.source_server_ids.join("\n") : profile.source_server_id,
      runtime_kind: profile.runtime_kind,
      binding_status: profile.binding_status,
      agent_status: profile.agent_status,
      agent_id: profile.agent_id,
      conversation_count: profile.conversation_count,
      read_only: profile.read_only ? context.t("是") : context.t("否"),
    }));
    root.append(binding(context, profile));
    root.append(conversationAccessNote(context, profile));
    return root;
  }

  function binding(context, profile) {
    if (!profile.read_only && window.FTProfiles?.renderBinding) {
      return window.FTProfiles.renderBinding(context, profile, () => (
        window.FTProfileDirectoryDetail.detail(context, profile.profile_id)
      ));
    }
    return fields(context, {
      runtime_kind: profile.runtime_kind,
      execution_server_id: profile.execution_server_id,
      binding_status: profile.binding_status,
      agent_status: profile.agent_status,
      agent_id: profile.agent_id || context.t("无"),
    });
  }

  async function skills(context, profile) {
    if (!profile.read_only && window.FTAgentSkills?.render) {
      return window.FTAgentSkills.render(context, profile, () => (
        window.FTProfileDirectoryDetail.detail(context, profile.profile_id)
      ));
    }
    return fields(context, {
      access_mode: context.t("只读"),
      skills: context.t("技能绑定仅由研究身份所有者管理"),
    });
  }

  function sessionMeta(context, profile) {
    return fields(context, {
      conversation_count: profile.conversation_count,
      conversation_access: profile.capabilities?.view_conversations
        ? (profile.read_only ? context.t("直属上级只读可见") : context.t("本人可管理"))
        : context.t("不可见"),
      access_mode: profile.read_only ? context.t("只读") : context.t("可管理"),
    });
  }

  async function session(context, profile, scope) {
    const root = document.createElement("div");
    root.className = "detail-stack";
    root.append(sessionMeta(context, profile));
    if (!profile.capabilities?.view_conversations) {
      root.append(FTUI.empty(
        context.t("会话不可见"),
        context.t("该研究身份的 Agent 会话对当前用户不可见。"),
      ));
      return root;
    }
    if (window.FTAgentChat?.render) {
      root.append(await window.FTAgentChat.render(context, profile, {
        readOnly: Boolean(profile.read_only),
        profileKey: profile.profile_key,
        profileScope: scope,
      }));
    }
    return root;
  }

  function workspace(context, profile) {
    if (!profile.read_only && window.FTProfileWorkspace?.render) {
      return window.FTProfileWorkspace.render(context, profile);
    }
    return fields(context, {
      source_server_id: profile.source_server_id,
      execution_server_id: profile.execution_server_id,
      access_mode: context.t("只读元数据"),
    });
  }

  async function loadProfile(context, profileID, scope, profileKey) {
    let key = text(profileKey).trim();
    if (!key) {
      const directory = await context.api(
        `/api/client/profile-directory?scope=${encodeURIComponent(scope)}&query=${encodeURIComponent(profileID)}&page_size=100`,
      );
      const item = (directory.items || []).find(value => value.profile_id === profileID);
      key = text(item?.profile_key);
    }
    if (!key) throw new Error(context.t("研究身份不存在或不可见"));
    const payload = await context.api(
      `/api/client/profile-directory/profile?profile_key=${encodeURIComponent(key)}&scope=${encodeURIComponent(scope)}`,
    );
    const profile = {
      ...payload.profile,
      ...(payload.owner_profile || {}),
      profile_key: key,
      owner_ref: payload.profile.owner_ref,
      capabilities: payload.profile.capabilities,
      read_only: payload.read_only,
    };
    // Keep the existing owner controls for the current user's local Profile.
    // Remote and subordinate projections intentionally never receive these
    // extra fields, so they cannot accidentally become writable.
    return {profile, readOnly: Boolean(payload.read_only), key};
  }

  async function detail(context, profileID) {
    context.activeNav("research");
    const query = params();
    const scope = query.get("profile_scope") || "mine";
    const loaded = await loadProfile(
      context, profileID, scope, query.get("profile_key") || "",
    );
    if (!current(context)) return;
    const {profile, readOnly, key} = loaded;
    profile.read_only = readOnly;
    const tab = selectedTab();
    context.setHeading(
      profile.display_name || profile.profile_id,
      `${context.t("研究身份")} · ${profile.owner_alias || profile.owner_ref}`,
    );
    context.updateActiveTab?.({title: profile.display_name || profile.profile_id});
    context.toolbar.replaceChildren();
    const sectionTabs = window.FTResearch?.sectionTabs?.(
      context,
      "profiles",
      new URLSearchParams(location.search).get("presentation") === "embedded",
    );
    if (sectionTabs) context.toolbar.append(sectionTabs);
    context.toolbar.append(context.button(
      "‹", () => context.navigate("/research?section=profiles"),
      context.t("返回研究身份"),
    ));
    const root = document.createElement("div");
    root.className = "detail-stack profile-directory-detail";
    root.append(tabBar(context, profile, scope, tab));
    if (tab === "overview") root.append(overview(context, profile));
    else if (tab === "skills") root.append(await skills(context, profile));
    else if (tab === "session") root.append(await session(context, profile, scope));
    else root.append(workspace(context, profile));
    context.content.replaceChildren(root);
  }

  window.FTProfileDirectoryDetail = {detail};
  window.FTProfileDirectory = Object.assign(window.FTProfileDirectory || {}, {detail});
})();
