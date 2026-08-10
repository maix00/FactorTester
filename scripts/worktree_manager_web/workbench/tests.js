(() => {
  async function show(context, kind) {
    context.activeNav(kind === "ic" ? "ic-test" : "backtest");
    context.setHeading(
      kind === "ic" ? context.t("IC 测试") : context.t("回测"),
      context.t("测试"),
    );
    context.content.replaceChildren(FTUI.loading(context.t("正在读取测试设置…")));
    const state = await loadState(context, kind);
    render(context, state);
  }

  async function loadState(context, kind) {
    const sessions = context.tabSession || (context.tabSession = {});
    sessions.tests = sessions.tests || {};
    if (sessions.tests[kind]) return sessions.tests[kind];
    const application = kind === "ic" ? "ic_test" : "group_test";
    const [manifest, library, groups, workspaces, templates, outputs] = await Promise.all([
      context.api(`/api/backtest/settings/${application}`),
      context.api("/api/catalog/factors"),
      context.api("/api/catalog/product-groups"),
      context.api("/api/workspaces"),
      context.api("/api/configuration-templates"),
      context.api("/api/jobs/artifact-capabilities"),
    ]);
    const state = {
      kind, manifest,
      factors: Array.isArray(library.factors) ? library.factors : [],
      families: Array.isArray(library.families) ? library.families : [],
      groups: Array.isArray(groups.groups) ? groups.groups : [],
      workspaces: workspaces.workspaces || [], templates: templates.templates || [],
      workspace: null, factorRef: "", groupRef: "", groupRefs: [], analysis: {}, values: null,
      settingsTabKey: "",
      outputCapabilities: Array.isArray(outputs.outputs) ? outputs.outputs : [],
      outputRequests: [],
    };
    restoreWorkspace(state);
    state.values = FTTestSettings.initialValues(manifest, savedSettings(state));
    FTTestProducts.synchronize(state);
    await FTTestFactors.initialize(context, state);
    await FTTestCategories.initialize(context, state);
    FTBacktestGroups.initialize(state);
    sessions.tests[kind] = state;
    return state;
  }

  function restoreWorkspace(state) {
    const key = localStorage.getItem(`ft-${state.kind}-workspace`) || "";
    if (!state.workspace || state.workspace.workspace_id !== key) {
      state.workspace = state.workspaces.find(item => item.workspace_id === key) || null;
    }
    applyWorkspaceConfiguration(state);
  }

  function applyWorkspaceConfiguration(state) {
    const payload = state.workspace?.configuration?.payload || {};
    state.analysis = structuredClone(payload.analyses?.[state.kind] || {});
    state.factorRef = payload.shared?.factors?.[0]?.factor_ref || "";
    state.groupRefs = FTTestProducts.restoreReferences(
      state.analysis, payload.ui?.[state.kind] || {},
    );
    state.groupRef = state.groupRefs[0] || "";
    const savedOutputs = payload.ui?.[state.kind]?.output_requests;
    state.outputRequests = FTOutputChoices.initialSelection(
      state.outputCapabilities, state.kind, savedOutputs,
    );
  }

  function savedSettings(state) {
    return state.analysis.local_settings || state.analysis.settings || {};
  }

  function render(context, state) {
    const root = document.createElement("div");
    root.className = "test-workbench";
    root.append(selectionPanel(context, state));
    if (state.kind === "backtest") {
      root.append(FTBacktestGroups.render(context, state, () => render(context, state)));
    }
    root.append(FTTestSettings.render(state.manifest, state.values, context, {
      kind: state.kind,
      activeTab: state.settingsTabKey,
      onTabChange: key => {
        state.settingsTabKey = key;
        render(context, state);
      },
      refresh: () => render(context, state),
    }));
    root.append(FTTestOutputs.render(context, state));
    if (state.manifest.defaults?.setting_template) {
      root.append(FTTestTemplates.list(context, state.templates, state.kind, {
        save: () => saveTemplate(context, state),
        load: template => loadTemplate(context, state, template),
        overwrite: template => overwriteTemplate(context, state, template),
        delete: template => deleteTemplate(context, state, template),
      }));
    }
    const actions = document.createElement("div");
    actions.className = "test-run-actions";
    const status = document.createElement("span");
    actions.append(
      context.button(context.t("预览冻结配置"), () => preview(context, state, status)),
      context.button(context.t("运行测试"), () => run(context, state, status)),
      status,
    );
    root.append(actions);
    context.content.replaceChildren(root);
  }

  function selectionPanel(context, state) {
    const root = document.createElement("section");
    root.className = "test-selection-panel";
    const heading = document.createElement("div");
    heading.className = "section-heading";
    heading.innerHTML = `<div><h2>${context.t("测试对象")}</h2><p>${context.t("端口由设置统一提供；本页只冻结测试对象和设置")}</p></div>`;
    heading.append(context.button(context.t("新建产品组"), () => showProductGroupCreator(context, state, root)));
    const grid = document.createElement("div");
    grid.className = "test-selection-grid";
    grid.append(
      FTTestFactors.panel(context, state, () => render(context, state)),
      FTTestProducts.panel(context, state),
    );
    const categories = FTTestCategories.panel(context, state, () => render(context, state));
    if (categories) grid.append(categories);
    root.append(heading, grid);
    return root;
  }

  function showProductGroupCreator(context, state, root) {
    root.querySelector(".test-inline-creator")?.remove();
    const form = document.createElement("form");
    form.className = "test-inline-creator";
    const name = document.createElement("input");
    name.required = true;
    name.placeholder = context.t("产品组名称");
    const paths = document.createElement("textarea");
    paths.required = true;
    paths.rows = 4;
    paths.placeholder = context.t("每行一个产品路径");
    const status = document.createElement("span");
    const save = context.button(context.t("创建并选中"), () => {});
    save.type = "submit";
    const cancel = context.button(context.t("取消"), () => form.remove());
    cancel.type = "button";
    form.append(name, paths, save, cancel, status);
    form.addEventListener("submit", async event => {
      event.preventDefault();
      const selectedPaths = paths.value.split(/\r?\n/).map(value => value.trim()).filter(Boolean);
      if (!selectedPaths.length) {
        status.textContent = context.t("请填写至少一个产品路径");
        return;
      }
      try {
        const value = await context.api("/api/catalog/product-groups", {
          method: "POST",
          body: JSON.stringify({name: name.value.trim(), paths: selectedPaths}),
        });
        state.groups.push(value.group);
        FTTestProducts.selectNew(state, value.group);
        render(context, state);
      } catch (error) { status.textContent = error.message; }
    });
    root.append(form);
    name.focus();
  }

  async function saveTemplate(context, state) {
    const name = prompt(context.t("模板名称"));
    if (!name?.trim()) return;
    const group = executionGroups(context, state)[0];
    await FTTestConfiguration.save(context, state, group);
    const value = await context.api(
      `/api/workspaces/${encodeURIComponent(state.workspace.workspace_id)}/configuration/templates`,
      {method: "POST", body: JSON.stringify({name: name.trim()})},
    );
    state.templates.unshift(value.template);
    render(context, state);
  }

  async function loadTemplate(context, state, template) {
    if (!state.workspace) {
      state.factorRef = template.payload?.shared?.factors?.[0]?.factor_ref || state.factorRef;
      await FTTestConfiguration.ensureWorkspace(context, state);
    }
    const value = await context.api(
      `/api/workspaces/${encodeURIComponent(state.workspace.workspace_id)}/configuration/load-template`,
      {
        method: "POST",
        body: JSON.stringify({
          configuration_id: template.configuration_id,
          expected_revision: state.workspace.configuration.revision,
        }),
      },
    );
    state.workspace.configuration = value.configuration;
    const listed = state.workspaces.findIndex(item => item.workspace_id === state.workspace.workspace_id);
    if (listed >= 0) state.workspaces[listed] = state.workspace;
    applyWorkspaceConfiguration(state);
    state.values = FTTestSettings.initialValues(state.manifest, savedSettings(state));
    FTTestProducts.synchronize(state);
    await FTTestFactors.initialize(context, state);
    await FTTestCategories.initialize(context, state);
    render(context, state);
  }

  async function overwriteTemplate(context, state, template) {
    if (!confirm(`${context.t("用当前设置覆盖模板")}「${template.name}」？`)) return;
    try {
      const group = executionGroups(context, state)[0];
      await FTTestConfiguration.save(context, state, group);
      const value = await context.api(
        `/api/configuration-templates/${encodeURIComponent(template.configuration_id)}`,
        {
          method: "PUT",
          body: JSON.stringify({workspace_id: state.workspace.workspace_id}),
        },
      );
      const index = state.templates.findIndex(item => (
        item.configuration_id === template.configuration_id
      ));
      if (index >= 0) state.templates[index] = value.template;
      render(context, state);
    } catch (error) {
      alert(error.message);
    }
  }

  async function deleteTemplate(context, state, template) {
    if (!confirm(`${context.t("确定删除模板")}「${template.name}」？`)) return;
    try {
      await context.api(
        `/api/configuration-templates/${encodeURIComponent(template.configuration_id)}`,
        {method: "DELETE"},
      );
      state.templates = state.templates.filter(item => (
        item.configuration_id !== template.configuration_id
      ));
      render(context, state);
    } catch (error) {
      alert(error.message);
    }
  }

  async function preview(context, state, status) {
    try {
      const groups = executionGroups(context, state);
      const hashes = [];
      for (const [index, group] of groups.entries()) {
        status.textContent = `${context.t("正在冻结配置")} ${index + 1}/${groups.length}`;
        const config = await FTTestConfiguration.save(context, state, group);
        const value = await context.api(context.servicePath("/api/runs/preview"), {
          method: "POST",
          body: JSON.stringify({
            workspace_id: state.workspace.workspace_id,
            configuration_revision: config.revision,
            analyses: [state.kind],
            output_requests: FTTestOutputs.selection(state),
          }),
        });
        hashes.push(`${FTTestProducts.groupLabel(group)}: ${value.run_spec_hash}`);
      }
      status.textContent = `${context.t("冻结配置")}: ${hashes.join(" · ")}`;
    } catch (error) { status.textContent = error.message; }
  }

  async function run(context, state, status) {
    const submitted = [];
    try {
      const groups = executionGroups(context, state);
      for (const [index, group] of groups.entries()) {
        status.textContent = `${context.t("正在提交")} ${index + 1}/${groups.length}`;
        const config = await FTTestConfiguration.save(context, state, group);
        const value = await context.api(context.servicePath("/api/runs"), {
          method: "POST",
          body: JSON.stringify({
            workspace_id: state.workspace.workspace_id,
            configuration_revision: config.revision,
            analyses: [state.kind],
            output_requests: FTTestOutputs.selection(state),
          }),
        });
        const job = value.jobs?.[0];
        if (!job?.job_id) throw new Error(context.t("任务提交响应缺少 Job ID"));
        submitted.push({job, port: value.port || 0});
      }
      if (submitted.length === 1) {
        const value = submitted[0];
        context.navigate(`/jobs/${value.port}/${encodeURIComponent(value.job.job_id)}`);
      } else {
        status.textContent = `${context.t("已提交任务")}: ${submitted.length}`;
        context.navigate("/jobs");
      }
    } catch (error) {
      const prefix = submitted.length
        ? `${context.t("已提交任务")}: ${submitted.length} · ` : "";
      status.textContent = `${prefix}${error.message}`;
    }
  }

  function executionGroups(context, state) {
    const groups = FTTestProducts.selectedGroups(state);
    if (!groups.length) throw new Error(context.t("请选择产品组"));
    const requested = state.kind === "ic" ? state.groupRefs : [state.groupRef];
    if (groups.length !== requested.filter(Boolean).length) {
      throw new Error(context.t("所选产品组已不可用，请重新选择"));
    }
    return groups;
  }

  window.FTTests = {show};
})();
