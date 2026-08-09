(() => {
  let cached = [];

  async function list(context) {
    context.activeNav("profiles"); context.setHeading("Profiles", context.t("本地研究身份"));
    context.content.replaceChildren(FTUI.loading(context.t("正在读取本地 Profiles…")));
    cached = (await context.api("/api/client/profiles")).profiles || [];
    context.toolbar.append(context.button("↻", () => list(context), context.t("刷新")));
    if (!cached.length) {
      context.content.replaceChildren(FTUI.empty(context.t("尚无已注册 Profile"), context.t("请使用 CLI 注册研究 Agent Profile")));
      return;
    }
    const view = FTUI.table(["Profile", context.t("标识"), "Agent", context.t("研究"), context.t("服务器")], cached.map(item => [
      item.display_name || item.profile_id, item.profile_id,
      (item.agents || []).length, (item.research_records || []).length,
      item.server?.base_url || "",
    ]));
    [...view.body.rows].forEach((row, index) => {
      row.dataset.href = "true";
      row.addEventListener("click", () => context.navigate(`/profiles/${encodeURIComponent(cached[index].profile_id)}`));
    });
    context.content.replaceChildren(view.shell);
  }

  async function detail(context, profileID) {
    context.activeNav("profiles");
    if (!cached.length) cached = (await context.api("/api/client/profiles")).profiles || [];
    const profile = cached.find(item => item.profile_id === profileID);
    if (!profile) throw new Error(context.t("Profile 不存在或不属于当前账户"));
    context.setHeading(profile.display_name || profile.profile_id, `Profile · ${profile.profile_id}`);
    context.toolbar.append(context.button("‹", () => context.navigate("/profiles"), context.t("返回 Profiles")));
    const root = document.createElement("div"); root.className = "detail-stack";
    root.append(FTUI.table([context.t("字段"), context.t("值")], FTUI.fieldRows({
      profile_id: profile.profile_id, display_name: profile.display_name,
      workspace_root: profile.workspace_root, server: profile.server?.base_url,
      principal: profile.session_binding?.principal_ref,
    })).shell);
    root.append(section(context, "Agents", ["Agent", context.t("角色"), context.t("状态"), context.t("下一步")], (profile.agents || []).map(item => [
      item.agent_id, item.role, item.status, item.next_action,
    ])));
    root.append(section(context, context.t("工作区"), [context.t("工作区"), context.t("访问模式"), context.t("所有者"), context.t("服务端引用")], (profile.workspaces || []).map(item => [
      item.workspace_id, item.access_mode, item.owner_ref, item.server_workspace_ref,
    ])));
    root.append(section(context, context.t("研究记录"), [context.t("研究"), context.t("分支"), context.t("节点"), "Checkpoint"], (profile.research_records || []).map(item => [
      item.title || item.work_package_id || item.record_id, item.branch_id,
      item.current_node || item.node_id, item.checkpoint_ref,
    ])));
    context.content.replaceChildren(root);
  }

  function section(context, title, headers, rows) {
    const root = document.createElement("section"); root.className = "job-section";
    const heading = document.createElement("h2"); heading.textContent = title; root.append(heading);
    root.append(rows.length ? FTUI.table(headers, rows).shell : FTUI.empty(context.t("暂无 %@").replace("%@", context.t(title)), ""));
    return root;
  }

  window.FTProfiles = {detail, list};
})();
