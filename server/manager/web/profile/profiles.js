(() => {
  let cached = [];

  function current(context) {
    return context.isRouteCurrent?.() !== false;
  }

  async function list(context, options = {}) {
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
    if (!embedded) {
      context.toolbar.append(context.button("↻", () => list(context, options), context.t("刷新")));
    }
    if (!cached.length) {
      context.content.replaceChildren(FTUI.empty(
        context.t("尚无已注册研究身份"),
        context.t("请使用 CLI 注册智能体研究身份"),
      ));
      return;
    }
    const view = FTUI.table([context.t("研究身份"), context.t("标识"), context.t("运行方式"), context.t("执行位置"), context.t("认领状态"), context.t("研究")], cached.map(item => [
      item.display_name || item.profile_id, item.profile_id,
      runtimeLabel(context, item.runtime), item.runtime?.executor_id || "",
      claimLabel(context, item.active_claim), (item.research_records || []).length,
    ]));
    [...view.body.rows].forEach((row, index) => {
      row.dataset.href = "true";
      row.addEventListener("click", () => {
        const profileID = encodeURIComponent(cached[index].profile_id);
        context.navigate(
          embedded
            ? `/research?section=profiles&profile=${profileID}`
            : `/profiles/${profileID}`,
        );
      });
    });
    context.content.replaceChildren(view.shell);
  }

  async function detail(context, profileID, options = {}) {
    const embedded = Boolean(options.embedded);
    if (!embedded) context.activeNav("research");
    if (!cached.length) {
      const payload = await context.api("/api/client/profiles");
      if (!current(context)) return;
      cached = payload.profiles || [];
    }
    const profile = cached.find(item => item.profile_id === profileID);
    if (!profile) throw new Error(context.t("Profile 不存在或不属于当前账户"));
    const root = document.createElement("div"); root.className = "detail-stack";
    if (!embedded) {
      context.setHeading(profile.display_name || profile.profile_id, `${context.t("研究身份")} · ${profile.profile_id}`);
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
    root.append(FTUI.table([context.t("字段"), context.t("值")], FTUI.fieldRows({
      profile_id: profile.profile_id, display_name: profile.display_name,
      workspace_root: profile.workspace_root, server: profile.server?.base_url,
      principal: profile.session_binding?.principal_ref,
      runtime_kind: runtimeLabel(context, runtime),
      executor_id: runtime.executor_id || context.t("未绑定"),
      workspace_relpath: runtime.workspace_relpath || context.t("未配置"),
      claim: claimLabel(context, claim),
      agent_id: claim?.agent_id || context.t("无"),
    })).shell);
    root.append(agentActions(context, profile, async () => {
      const payload = await context.api("/api/client/profiles");
      cached = payload.profiles || [];
      await detail(context, profileID, options);
    }));
    if (window.FTAgentSkills?.render) {
      root.append(await window.FTAgentSkills.render(context, profile, async () => {
        const payload = await context.api("/api/client/profiles");
        cached = payload.profiles || [];
        await detail(context, profileID, options);
      }));
    }
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

  function runtimeLabel(context, runtime) {
    if (!runtime || !runtime.runtime_kind) return context.t("未配置");
    const label = runtime.runtime_kind === "server"
      ? context.t("服务器运行") : context.t("客户端运行");
    return runtime.configured === false ? `${label} · ${context.t("未绑定")}` : label;
  }

  function claimLabel(context, claim) {
    return claim ? context.t("已认领") : context.t("未认领");
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
    bind.onclick = async () => {
      bind.disabled = true;
      try {
        await context.api("/api/client/profile-runtime", {
          method: "POST",
          body: JSON.stringify({
            profile_id: profile.profile_id,
            runtime_kind: runtimeSelect.value,
            executor_id: runtimeSelect.value === "server" ? "" : runtime.executor_id,
          }),
        });
        await refresh();
      } catch (error) {
        context.showNotice(error.message, true);
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
    claimButton.disabled = !claim;
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
      claimButton.disabled = Boolean(claim) || !values.length;
      if (!values.length && !claim) {
        const option = document.createElement("option");
        option.textContent = context.t("请先保存模型服务");
        option.disabled = true; option.selected = true;
        provider.append(option);
      }
    };
    provider.onchange = () => { claimButton.disabled = Boolean(claim) || !provider.value; };
    claimButton.onclick = async () => {
      claimButton.disabled = true;
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
        await refresh();
      } catch (error) {
        context.showNotice(error.message, true);
        claimButton.disabled = false;
      }
    };
    controls.append(provider, claimButton);
    root.append(heading, note, controls);
    if (!claim) loadProviders().catch(error => {
      const warning = document.createElement("p");
      warning.className = "settings-muted";
      warning.textContent = error.message || context.t("模型服务读取失败");
      root.append(warning);
    });
    return root;
  }

  function section(context, title, headers, rows) {
    const root = document.createElement("section"); root.className = "job-section";
    const heading = document.createElement("h2"); heading.textContent = title; root.append(heading);
    root.append(rows.length ? FTUI.table(headers, rows).shell : FTUI.empty(context.t("暂无 %@").replace("%@", context.t(title)), ""));
    return root;
  }

  window.FTProfiles = {detail, list};
})();
