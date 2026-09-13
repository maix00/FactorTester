(() => {
  function current(context) {
    return context.isRouteCurrent?.() !== false;
  }

  function section(context, title, subtitle = "") {
    const root = document.createElement("section");
    root.className = "settings-section manager-directory-section";
    const heading = document.createElement("h3");
    heading.textContent = context.t(title);
    root.append(heading);
    if (subtitle) {
      const note = document.createElement("p");
      note.className = "settings-muted";
      note.textContent = context.t(subtitle);
      root.append(note);
    }
    return root;
  }

  function field(context, label, control) {
    const wrapper = document.createElement("label");
    wrapper.className = "manager-directory-field";
    const caption = document.createElement("span");
    caption.textContent = context.t(label);
    wrapper.append(caption, control);
    return wrapper;
  }

  function selectOptions(select, values, selected, label) {
    select.replaceChildren();
    values.forEach(item => {
      const option = document.createElement("option");
      option.value = item.value;
      option.textContent = item.label;
      option.selected = item.value === selected;
      select.append(option);
    });
    if (!values.length) {
      const option = document.createElement("option");
      option.textContent = label;
      option.disabled = true;
      select.append(option);
    }
  }

  function dialog(context, title) {
    const root = document.createElement("dialog");
    root.dataset.ftTabID = context.tabID || "";
    root.className = "manager-directory-dialog";
    const form = document.createElement("form");
    form.method = "dialog";
    form.className = "dialog-card manager-directory-form";
    const heading = document.createElement("h3");
    heading.textContent = context.t(title);
    const fields = document.createElement("div");
    fields.className = "manager-directory-form-fields";
    const status = document.createElement("p");
    status.className = "settings-muted";
    const actions = document.createElement("div");
    actions.className = "dialog-actions";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "secondary";
    cancel.textContent = context.t("取消");
    cancel.onclick = () => root.close();
    const save = document.createElement("button");
    save.type = "submit";
    save.className = "primary";
    save.textContent = context.t("保存");
    actions.append(cancel, save);
    form.append(heading, fields, status, actions);
    root.append(form);
    root.addEventListener("close", () => root.remove(), {once: true});
    document.body.append(root);
    root.showModal();
    return {root, form, fields, status, save};
  }

  function showUserDialog(context, payload, account, refresh) {
    const editing = Boolean(account);
    const view = dialog(context, editing ? "编辑用户" : "新增用户");
    const alias = document.createElement("input");
    alias.value = account?.alias || "";
    alias.required = true;
    alias.disabled = editing;
    const password = document.createElement("input");
    password.type = "password";
    password.minLength = 6;
    password.required = !editing;
    password.placeholder = editing ? context.t("留空表示不修改") : "";
    const organization = document.createElement("select");
    const level = document.createElement("select");
    const parent = document.createElement("select");
    const role = document.createElement("select");
    const organizations = (payload.organizations || []).map(item => ({
      value: item.id, label: `${item.name || item.id} (${item.id})`,
    }));
    const allLevels = payload.levels || [];
    const allUsers = (payload.users || []).filter(item => item.active !== false);
    const roles = Object.entries(payload.role_labels || {}).map(([value, label]) => ({value, label: context.t(label)}));
    selectOptions(organization, organizations, account?.organization_id || organizations[0]?.value || "", context.t("暂无机构"));
    selectOptions(role, roles, account?.role || "user", context.t("暂无角色"));

    function refreshHierarchy() {
      const orgID = organization.value;
      const levels = allLevels.filter(item => item.organization_id === orgID).map(item => ({
        value: item.id, label: item.name || item.id,
      }));
      selectOptions(level, levels, account?.level_id || levels[0]?.value || "", context.t("暂无层级"));
      const users = allUsers.filter(item => item.organization_id === orgID && item.username !== account?.username).map(item => ({
        value: item.username, label: `${FTUI.userLabel(item.username, item.alias)} · ${item.username}`,
      }));
      selectOptions(parent, [{value: "", label: context.t("不设置上级用户")}, ...users], account?.parent_username || "", "");
    }
    organization.onchange = refreshHierarchy;
    refreshHierarchy();
    view.fields.append(
      field(context, "别名", alias),
      field(context, "密码", password),
      field(context, "机构", organization),
      field(context, "层级", level),
      field(context, "上级用户", parent),
      field(context, "角色", role),
    );
    view.form.onsubmit = async event => {
      event.preventDefault();
      view.save.disabled = true;
      view.status.textContent = context.t("正在保存…");
      const body = {
        organization_id: organization.value,
        level_id: level.value,
        parent_username: parent.value,
        role: role.value,
      };
      if (!editing) body.alias = alias.value.trim();
      if (password.value) body.password = password.value;
      try {
        await context.api(editing
          ? `/api/admin/users/${encodeURIComponent(account.username)}`
          : "/api/admin/users", {
            method: editing ? "PUT" : "POST",
            body: JSON.stringify(body),
          });
        view.root.close();
        context.showNotice(context.t("用户已保存"));
        await refresh();
      } catch (error) {
        view.status.textContent = error.message || context.t("保存失败");
        view.save.disabled = false;
      }
    };
  }

  function showOrganizationDialog(context, refresh) {
    const view = dialog(context, "新增机构");
    const id = document.createElement("input");
    const name = document.createElement("input");
    const description = document.createElement("textarea");
    id.placeholder = context.t("可选，默认从名称生成");
    name.required = true;
    view.fields.append(field(context, "机构标识", id), field(context, "名称", name), field(context, "描述", description));
    view.form.onsubmit = async event => {
      event.preventDefault(); view.save.disabled = true;
      try {
        await context.api("/api/admin/organizations", {method: "POST", body: JSON.stringify({id: id.value.trim(), name: name.value.trim(), description: description.value.trim()})});
        view.root.close(); context.showNotice(context.t("机构已保存")); await refresh();
      } catch (error) { view.status.textContent = error.message || context.t("保存失败"); view.save.disabled = false; }
    };
  }

  function showLevelDialog(context, payload, refresh, existing = null) {
    const view = dialog(context, existing ? "编辑层级" : "新增层级");
    const organization = document.createElement("select");
    const name = document.createElement("input");
    const parent = document.createElement("select");
    const manager = document.createElement("input");
    const organizations = (payload.organizations || []).map(item => ({value: item.id, label: `${item.name || item.id} (${item.id})`}));
    selectOptions(organization, organizations, existing?.organization_id || organizations[0]?.value || "", context.t("暂无机构"));
    name.value = existing?.name || ""; name.required = true;
    manager.value = existing?.manager_username || "";
    function refreshParents() {
      const choices = (payload.levels || []).filter(item => item.organization_id === organization.value && item.id !== existing?.id).map(item => ({value: item.id, label: item.name || item.id}));
      selectOptions(parent, [{value: "", label: context.t("根层级")}, ...choices], existing?.parent_level_id || "", "");
    }
    organization.onchange = refreshParents; refreshParents();
    view.fields.append(field(context, "机构", organization), field(context, "层级名称", name), field(context, "上级层级", parent), field(context, "层级管理员用户名", manager));
    view.form.onsubmit = async event => {
      event.preventDefault(); view.save.disabled = true;
      const body = {organization_id: organization.value, name: name.value.trim(), parent_level_id: parent.value, manager_username: manager.value.trim()};
      try {
        await context.api(existing ? `/api/admin/levels/${encodeURIComponent(existing.id)}` : "/api/admin/levels", {method: existing ? "PUT" : "POST", body: JSON.stringify(body)});
        view.root.close(); context.showNotice(context.t("层级已保存")); await refresh();
      } catch (error) { view.status.textContent = error.message || context.t("保存失败"); view.save.disabled = false; }
    };
  }

  function render(context, payload, refresh) {
    const root = document.createElement("div");
    root.className = "manager-directory-content";
    const intro = section(context, "用户与机构", "管理用户、机构、层级和研究权限；中央 PostgreSQL 是权威数据源，Manager SQLite 仅保留离线登录镜像。");
    const actions = document.createElement("div"); actions.className = "settings-inline-actions";
    const addUser = document.createElement("button"); addUser.className = "primary"; addUser.textContent = context.t("新增用户"); addUser.onclick = () => showUserDialog(context, payload, null, refresh);
    const addOrg = document.createElement("button"); addOrg.className = "secondary"; addOrg.textContent = context.t("新增机构"); addOrg.onclick = () => showOrganizationDialog(context, refresh);
    const addLevel = document.createElement("button"); addLevel.className = "secondary"; addLevel.textContent = context.t("新增层级"); addLevel.onclick = () => showLevelDialog(context, payload, refresh);
    actions.append(addUser, addOrg, addLevel); intro.append(actions); root.append(intro);

    const users = section(context, "用户", "用户可以移动到其他机构或层级，完整用户名会保留为不可变的登录标识。");
    const userTable = FTManagerAccessTable.create(context, {headers: ["用户", "机构", "层级", "上级用户", "角色", "操作"], searchPlaceholder: "搜索用户", empty: "暂无用户", searchText: item => [item.alias, item.username, item.organization_id, item.organization_name, item.level_id, item.parent_username, item.role].join(" "), cells: item => [FTUI.userDisplay(item.username, item.alias), item.organization_name || item.organization_id || "", item.level_id || context.t("未设置"), FTUI.userDisplay(item.parent_username, (payload.users || []).find(user => user.username === item.parent_username)?.alias || (item.parent_username ? "" : context.t("无"))), context.t((payload.role_labels || {})[item.role] || item.role || ""), (ctx, value) => { const button = document.createElement("button"); button.className = "secondary"; button.textContent = ctx.t("编辑"); button.onclick = () => showUserDialog(ctx, payload, value, refresh); return button; }]});
    userTable.setRows(payload.users || []); users.append(userTable.root); root.append(users);

    const organizations = section(context, "机构", "机构是用户名和服务器管理范围的一级边界。");
    const orgTable = FTManagerAccessTable.create(context, {headers: ["机构标识", "名称", "描述"], searchPlaceholder: "搜索机构", empty: "暂无机构", searchText: item => [item.id, item.name, item.description].join(" "), cells: item => [item.id, item.name, item.description || ""]});
    orgTable.setRows(payload.organizations || []); organizations.append(orgTable.root); root.append(organizations);

    const levels = section(context, "层级", "层级可以建立父子关系；用户和层级管理员必须属于同一机构。");
    const levelTable = FTManagerAccessTable.create(context, {headers: ["层级", "机构", "上级层级", "层级管理员", "操作"], searchPlaceholder: "搜索层级", empty: "暂无层级", searchText: item => [item.id, item.name, item.organization_id, item.parent_level_id, item.manager_username].join(" "), cells: item => [item.name || item.id, item.organization_id || "", item.parent_level_id || context.t("根层级"), FTUI.userDisplay(item.manager_username, (payload.users || []).find(user => user.username === item.manager_username)?.alias || (item.manager_username ? "" : context.t("未设置"))), (ctx, value) => { const button = document.createElement("button"); button.className = "secondary"; button.textContent = ctx.t("编辑"); button.onclick = () => showLevelDialog(ctx, payload, refresh, value); return button; }]});
    levelTable.setRows(payload.levels || []); levels.append(levelTable.root); root.append(levels);
    return root;
  }

  async function show(context, body) {
    if (context.session?.role !== "super_admin") {
      body.append(section(context, "需要超级管理员", "只有超级管理员可以管理用户、机构和层级。"));
      return;
    }
    const mount = document.createElement("div");
    body.append(mount);
    const refresh = async () => {
      const payload = await context.api("/api/admin/account-directory");
      if (!current(context)) return;
      mount.replaceChildren(render(context, payload, refresh));
    };
    try { await refresh(); } catch (error) {
      mount.replaceChildren(section(context, "读取失败", "中央控制数据库不可用；用户与机构管理不会使用本地陈旧副本。"));
      const detail = document.createElement("small"); detail.textContent = error.message || ""; mount.firstChild.append(detail);
    }
  }

  window.FTManagerAccounts = Object.freeze({show});
})();
