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
      context.api(context.servicePath(`/api/backtest/settings/${application}`)),
      context.api("/api/catalog/factors"),
      context.api("/api/catalog/product-groups"),
      context.api(context.servicePath("/api/workspaces")),
      context.api(context.servicePath("/api/configuration-templates")),
      context.api(context.servicePath("/api/jobs/artifact-capabilities")),
    ]);
    const state = {
      kind, manifest,
      factors: Array.isArray(library.factors) ? library.factors : [],
      families: Array.isArray(library.families) ? library.families : [],
      groups: Array.isArray(groups.groups) ? groups.groups : [],
      workspaces: workspaces.workspaces || [], templates: templates.templates || [],
      workspace: null, factorRef: "", groupRef: "", groupRefs: [], analysis: {}, values: null,
      outputCapabilities: Array.isArray(outputs.outputs) ? outputs.outputs : [],
      outputRequests: [],
    };
    restoreWorkspace(state);
    state.values = FTTestSettings.initialValues(manifest, savedSettings(state));
    FTTestProducts.synchronize(state);
    await FTTestFactors.initialize(context, state);
    await FTTestCategories.initialize(context, state);
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
    root.append(FTTestSettings.render(state.manifest, state.values, context, {
      kind: state.kind,
      refresh: () => render(context, state),
    }));
    root.append(FTTestOutputs.render(context, state));
    if (state.manifest.defaults?.setting_template) {
      root.append(FTTestTemplates.list(context, state.templates, state.kind, {
        save: () => saveTemplate(context, state),
        load: template => loadTemplate(context, state, template),
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

  async function ensureWorkspace(context, state) {
    if (state.workspace) return state.workspace;
    const factor = selectedFactor(state);
    if (!factor) throw new Error(context.t("请选择因子"));
    const factors = selectedFactors(state);
    const families = uniqueFamilies(state, factors);
    const body = {
      title: `${state.kind === "ic" ? "IC" : "Backtest"} · ${factor.factor_alias || factor.alias || factor.name || factor.factor_ref}`,
      factor_families: families.map(item => familyRecord(item.family, item.factor)),
      factors: factors.map(item => factorRecord(item, selectedFamily(state, item))),
    };
    const value = await context.api(context.servicePath("/api/workspaces"), {
      method: "POST", body: JSON.stringify(body),
    });
    state.workspace = value.workspace;
    localStorage.setItem(`ft-${state.kind}-workspace`, state.workspace.workspace_id);
    return state.workspace;
  }

  async function saveConfiguration(context, state, group) {
    await ensureWorkspace(context, state);
    const factor = selectedFactor(state);
    if (!factor) throw new Error(context.t("请选择因子"));
    if (!group) throw new Error(context.t("请选择产品组"));
    FTTestProducts.synchronize(state);
    const factors = selectedFactors(state);
    const families = uniqueFamilies(state, factors);
    const family = selectedFamily(state, factor);
    const configuration = state.workspace.configuration;
    const payload = structuredClone(configuration.payload || {});
    payload.schema_version = 1;
    payload.shared = payload.shared || {};
    payload.shared.factor_families = families.map(item => familyRecord(item.family, item.factor));
    payload.shared.factors = factors.map(item => factorRecord(item, selectedFamily(state, item)));
    payload.analyses = payload.analyses || {};
    state.analysis = buildAnalysis(state, factors, family, group);
    payload.analyses[state.kind] = state.analysis;
    payload.ui = payload.ui || {};
    payload.ui[state.kind] = {
      settings: state.values,
      factor_ref: state.factorRef,
      product_group_ref: FTTestProducts.groupID(group),
      product_group_refs: state.groupRefs,
      output_requests: FTTestOutputs.selection(state),
    };
    const value = await context.api(context.servicePath(`/api/workspaces/${encodeURIComponent(state.workspace.workspace_id)}/configuration`), {
      method: "PUT",
      body: JSON.stringify({expected_revision: configuration.revision, payload}),
    });
    state.workspace.configuration = value.configuration;
    return value.configuration;
  }

  function buildAnalysis(state, factors, familyRecordValue, group) {
    const prior = structuredClone(state.analysis || {});
    const settings = structuredClone(state.values);
    const factor = factors[0];
    const alias = factor.factor_alias || factor.alias || factor.name;
    const family = familyRecordValue?.factor_family_alias
      || familyRecordValue?.alias
      || factor.factor_family_alias || factor.family_alias || alias;
    if (state.kind === "ic") {
      const selection = FTTestProducts.projection(group);
      return {
        ...prior,
        ...settings,
        product_path_selection_id: selection.product_path_selection_id,
        product_path_selection: selection,
        product_path_selections: FTTestProducts.selectedProjections(state),
        paths: selection.selected_paths,
        factor_family_alias: family,
        factors: factors.map(item => ({
          alias: item.factor_alias || item.alias || item.name,
          factor_ref: item.factor_ref || item.target_ref || "",
          return_freq: item.return_freq || "",
        })),
        settings,
        local_settings: settings,
      };
    }
    const groups = Array.isArray(prior.groups) && prior.groups.length ? prior.groups : [{
      id: "group-1", name: "默认分组", factorAlias: alias,
      splitCount: 5, groupIndex: 1, product_path_selection: group,
    }];
    return {
      ...prior,
      ...settings,
      local_settings: settings,
      groups,
      ls_configs: prior.ls_configs || [],
      factor_family_alias: family,
    };
  }

  async function saveTemplate(context, state) {
    const name = prompt(context.t("模板名称"));
    if (!name?.trim()) return;
    const group = executionGroups(context, state)[0];
    await saveConfiguration(context, state, group);
    const value = await context.api(context.servicePath(`/api/workspaces/${encodeURIComponent(state.workspace.workspace_id)}/configuration/templates`), {
      method: "POST", body: JSON.stringify({name: name.trim()}),
    });
    state.templates.unshift(value.template);
    render(context, state);
  }

  async function loadTemplate(context, state, template) {
    if (!state.workspace) {
      state.factorRef = template.payload?.shared?.factors?.[0]?.factor_ref || state.factorRef;
      await ensureWorkspace(context, state);
    }
    const value = await context.api(context.servicePath(`/api/workspaces/${encodeURIComponent(state.workspace.workspace_id)}/configuration/load-template`), {
      method: "POST",
      body: JSON.stringify({configuration_id: template.configuration_id, expected_revision: state.workspace.configuration.revision}),
    });
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

  async function preview(context, state, status) {
    try {
      const groups = executionGroups(context, state);
      const hashes = [];
      for (const [index, group] of groups.entries()) {
        status.textContent = `${context.t("正在冻结配置")} ${index + 1}/${groups.length}`;
        const config = await saveConfiguration(context, state, group);
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
        const config = await saveConfiguration(context, state, group);
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

  function selectedFactor(state) { return FTTestFactors.selectedFactor(state); }
  function selectedFactors(state) {
    if (state.kind !== "ic") return [selectedFactor(state)].filter(Boolean);
    const selected = Array.isArray(state.values.factor_selections)
      ? state.values.factor_selections : [];
    return selected.length ? selected : [selectedFactor(state)].filter(Boolean);
  }
  function selectedFamily(state, factor) {
    return FTTestFactors.selectedFamily(state, factor);
  }
  function uniqueFamilies(state, factors) {
    const seen = new Set();
    const result = [];
    for (const factor of factors) {
      const family = selectedFamily(state, factor);
      const key = family?.family_ref || factor.family_ref
        || family?.family || factor.family || factor.factor_family_alias;
      if (!key || seen.has(key)) continue;
      seen.add(key);
      result.push({family, factor});
    }
    return result;
  }
  function familyRecord(family, factor) {
    return {
      alias: family?.factor_family_alias || family?.alias || family?.family
        || factor.factor_family_alias || factor.family_alias
        || factor.factor_alias || factor.alias,
      family_ref: family?.family_ref || factor.family_ref
        || factor.factor_family_ref || "",
    };
  }
  function factorRecord(factor, family) {
    return {
      alias: factor.factor_alias || factor.alias || factor.name,
      factor_family_alias: family?.factor_family_alias || family?.alias || family?.family
        || factor.factor_family_alias || factor.family_alias
        || factor.factor_alias || factor.alias,
      factor_ref: factor.factor_ref || factor.target_ref || "",
      family_ref: factor.family_ref || factor.factor_family_ref
        || family?.family_ref || "",
      owner_ref: factor.owner_ref || "",
      git_commit: factor.git_commit || "",
      git_blob: factor.git_blob || "",
      params: factor.params || {},
    };
  }

  window.FTTests = {show};
})();
