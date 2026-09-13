(() => {
  const SCOPES = [
    ["mine", "我的研究身份", "只显示当前登录用户创建的研究身份。"],
    ["subordinates", "下级用户研究身份", "只显示直属下级用户的研究身份；详情与 Agent 会话自动只读可见。"],
    ["servers", "服务器研究身份", "显示当前可见服务器上的研究身份；非本用户拥有的内容为只读。"],
  ];

  function current(context) {
    return context.isRouteCurrent?.() !== false;
  }

  function text(value) {
    return value == null ? "" : String(value);
  }

  function queryValue(value) {
    return encodeURIComponent(text(value).trim());
  }

  function scopeLabel(context, scope) {
    return context.t(SCOPES.find(item => item[0] === scope)?.[1] || scope);
  }

  function scopeDescription(context, scope) {
    return context.t(SCOPES.find(item => item[0] === scope)?.[2] || "");
  }

  async function fetchDirectory(context, state) {
    const params = new URLSearchParams({
      scope: state.scope,
      query: state.query,
      page: String(state.page),
      page_size: String(state.pageSize),
      server_id: state.serverID,
      binding: state.binding,
      agent: state.agent,
    });
    return context.api(`/api/client/profile-directory?${params}`);
  }

  function profilePath(item, scope) {
    const profileID = queryValue(item.profile_id);
    const params = new URLSearchParams({
      profile_key: text(item.profile_key),
      profile_scope: scope,
      profile_tab: "overview",
    });
    return `/profiles/${profileID}?${params}`;
  }

  function filterSelect(context, label, value, values, onChange) {
    const select = document.createElement("select");
    select.className = "inline-setting profile-directory-filter";
    select.setAttribute("aria-label", context.t(label));
    values.forEach(([optionValue, optionLabel]) => {
      const option = document.createElement("option");
      option.value = optionValue;
      option.textContent = context.t(optionLabel);
      option.selected = optionValue === value;
      select.append(option);
    });
    select.addEventListener("change", () => onChange(select.value));
    return select;
  }

  function controls(context, state, load) {
    const root = document.createElement("div");
    root.className = "settings-inline-actions profile-directory-controls";
    const search = document.createElement("input");
    search.className = "inline-setting profile-directory-search";
    search.type = "search";
    search.placeholder = context.t("搜索研究身份、用户或服务器");
    search.value = state.query;
    search.addEventListener("keydown", event => {
      if (event.key !== "Enter") return;
      state.query = search.value.trim();
      state.page = 1;
      load();
    });
    root.append(search);
    root.append(filterSelect(
      context, "绑定状态", state.binding,
      [["", "全部绑定状态"], ["bound", "已绑定"], ["unbound", "未绑定"]],
      value => { state.binding = value; state.page = 1; load(); },
    ));
    root.append(filterSelect(
      context, "Agent 状态", state.agent,
      [["", "全部 Agent 状态"], ["claimed", "已认领"], ["unclaimed", "未认领"]],
      value => { state.agent = value; state.page = 1; load(); },
    ));
    const server = document.createElement("input");
    server.className = "inline-setting profile-directory-server-filter";
    server.placeholder = context.t("服务器 ID（可选）");
    server.value = state.serverID;
    server.addEventListener("keydown", event => {
      if (event.key !== "Enter") return;
      state.serverID = server.value.trim();
      state.page = 1;
      load();
    });
    root.append(server);
    root.append(FTUI.refreshButton(context, () => {
      state.page = 1;
      return load();
    }));
    return root;
  }

  function rowValues(context, item, scope) {
    const readOnly = item.read_only || item.capabilities?.edit !== true;
    const identity = document.createElement("div");
    identity.className = "profile-directory-identity";
    const name = document.createElement("strong");
    name.textContent = text(item.display_name || item.profile_id);
    const id = document.createElement("small");
    id.textContent = text(item.profile_id);
    identity.append(name);
    if (item.is_self_profile || item.profile_kind === "self") {
      const badge = document.createElement("span");
      badge.className = "profile-self-badge";
      badge.textContent = context.t("本人身份");
      identity.append(badge);
    }
    identity.append(id);
    const owner = FTUI.userDisplay(item.owner_ref, item.owner_alias);
    const sourceServers = Array.isArray(item.source_server_ids) && item.source_server_ids.length
      ? item.source_server_ids
      : [item.source_server_id];
    const executionServers = Array.isArray(item.execution_server_ids) && item.execution_server_ids.length
      ? item.execution_server_ids
      : [item.execution_server_id];
    const server = `${sourceServers.filter(Boolean).map(text).join("\n")}\n${executionServers.filter(Boolean).map(text).join("\n")}`.trim();
    const runtime = `${context.t(item.runtime_kind === "server" ? "服务器运行" : "客户端运行")} · ${context.t(item.binding_status === "bound" ? "已绑定" : "未绑定")}`;
    const agent = item.agent_status === "claimed"
      ? `${context.t("已认领")} · ${text(item.agent_id)}${item.agent_runtime_status ? ` · ${text(item.agent_runtime_status)}` : ""}`
      : context.t("未认领");
    const access = readOnly ? context.t("只读") : context.t("可管理");
    return [identity, owner, server, runtime, agent, text(item.conversation_count || 0), access];
  }

  function table(context, state, payload, load) {
    const headers = [
      context.t("研究身份"), context.t("所有者"), context.t("来源服务器"),
      context.t("运行绑定"), context.t("Agent"), context.t("会话数"),
      context.t("访问权限"),
    ];
    const view = FTUI.pagedTable(
      headers,
      (payload.items || []).map(item => rowValues(context, item, state.scope)),
      {
        remote: true,
        page: payload.page,
        pageSize: payload.page_size,
        total: payload.total,
        onPageChange: page => { state.page = page; load(); },
        pageLabel: (page, total) => `${page} / ${total}`,
        totalLabel: total => `${context.t("共")} ${total} ${context.t("项")}`,
      },
    );
    [...view.body.rows].forEach((row, index) => {
      const item = payload.items[index];
      if (!item) return;
      row.classList.add("profile-directory-row");
      if (item.is_self_profile || item.profile_kind === "self") {
        row.classList.add("profile-directory-row-self");
      }
      row.tabIndex = 0;
      const open = () => context.navigate(profilePath(item, state.scope));
      row.addEventListener("click", open);
      row.addEventListener("keydown", event => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          open();
        }
      });
    });
    return view.shell;
  }

  function section(context, scope) {
    const root = document.createElement("section");
    root.className = `job-section profile-directory-section profile-directory-${scope}`;
    const header = document.createElement("div");
    header.className = "profile-directory-section-heading";
    const title = document.createElement("h2");
    title.textContent = scopeLabel(context, scope);
    const note = document.createElement("p");
    note.className = "settings-muted";
    note.textContent = scopeDescription(context, scope);
    header.append(title, note);
    const content = document.createElement("div");
    content.className = "profile-directory-section-content";
    const state = {
      scope, page: 1, pageSize: 20, query: "", serverID: "", binding: "", agent: "",
    };
    const load = async () => {
      content.replaceChildren(FTUI.loading(context.t("正在读取研究身份…")));
      try {
        const payload = await fetchDirectory(context, state);
        if (!current(context)) return;
        content.replaceChildren(controls(context, state, load), table(context, state, payload, load));
      } catch (error) {
        if (!current(context)) return;
        content.replaceChildren(FTUI.empty(
          context.t("无法读取"), error.message || context.t("研究身份目录读取失败"),
        ));
      }
    };
    root.append(header, content);
    load();
    return root;
  }

  async function list(context) {
    context.activeNav("research");
    context.setHeading(context.t("研究身份"), context.t("我的研究身份、下级用户与服务器目录"));
    context.toolbar.replaceChildren();
    const sectionTabs = window.FTResearch?.sectionTabs?.(context, "profiles", false);
    if (sectionTabs) context.toolbar.append(sectionTabs);
    context.toolbar.append(FTUI.refreshButton(context, () => list(context)));
    const root = document.createElement("div");
    root.className = "detail-stack profile-directory";
    SCOPES.forEach(([scope]) => root.append(section(context, scope)));
    context.content.replaceChildren(root);
  }

  window.FTProfileDirectory = {
    fetchDirectory,
    list,
    profilePath,
    scopeDescription,
    scopeLabel,
  };
})();
