(() => {
  const definitions = {
    ic: {application: "ic_test", nav: "ic-test", title: "IC 测试"},
    backtest: {application: "group_test", nav: "backtest", title: "回测"},
    factor_evaluation: {
      application: "factor_evaluation", nav: "factors", title: "因子序列",
    },
  };

  async function show(context, kind, options = {}) {
    const definition = definitions[kind];
    if (!definition) throw new Error(context.t("未知测试类型"));
    context.activeNav(definition.nav);
    context.setHeading(context.t(definition.title), context.t("测试"));
    context.content.replaceChildren(FTUI.loading(context.t("正在读取测试设置…")));
    const state = await loadState(context, kind, options);
    render(context, state);
  }

  async function loadState(context, kind, options) {
    const sessions = context.tabSession || (context.tabSession = {});
    sessions.tests = sessions.tests || {};
    if (sessions.tests[kind]) return sessions.tests[kind];
    const application = definitions[kind].application;
    const [manifest, library, groups, workspaces, templates, outputs, profiles] = await Promise.all([
      context.api(`/api/backtest/settings/${application}`),
      context.api("/api/catalog/factors"),
      context.api("/api/catalog/product-groups"),
      context.api("/api/workspaces"),
      context.api("/api/configuration-templates"),
      context.api("/api/jobs/artifact-capabilities"),
      // Profile selection is a client-side identity feature.  A service can
      // still be used directly (or by CLI), so an unavailable client profile
      // endpoint must not make the test authoring page unusable.
      context.api("/api/client/profiles").catch(() => ({profiles: []})),
    ]);
    const state = {
      kind, manifest,
      factors: Array.isArray(library.factors) ? library.factors : [],
      families: Array.isArray(library.families) ? library.families : [],
      groups: Array.isArray(groups.groups) ? groups.groups : [],
      workspaces: workspaces.workspaces || [], templates: templates.templates || [],
      workspace: null, factorRef: "", groupRef: "", groupRefs: [], analysis: {}, values: null,
      settingsTabKey: "", settingsMountedTabs: [],
      outputCapabilities: Array.isArray(outputs.outputs) ? outputs.outputs : [],
      outputRequests: [],
      profiles: Array.isArray(profiles.profiles) ? profiles.profiles : [],
      runValues: {
        ...FTTestRunFields.initialValues(manifest),
        task_name: "",
        acting_profile_ref: "",
        acting_profile_name: "",
      },
    };
    restoreWorkspace(state);
    if (options.factorRef) state.factorRef = options.factorRef;
    if (options.groupRef) {
      state.groupRef = options.groupRef;
      state.groupRefs = [options.groupRef];
    }
    state.settingsMountedTabs = FTTestSettings.initialMountedTabs(
      manifest, savedMountedTabs(state),
    );
    state.values = FTTestSettings.initialValues(
      manifest, savedSettings(state), state.settingsMountedTabs,
    );
    FTTestInputState.initialize(state);
    if (kind === "factor_evaluation" && state.runValues.retention_mode === "summary") {
      state.runValues.retention_mode = "full";
    }
    FTTestProducts.synchronize(state);
    await FTTestFactors.initialize(context, state);
    await FTTestCategories.initialize(context, state);
    FTBacktestGroups.initialize(state);
    applyBacktestDerivedPrefill(state);
    sessions.tests[kind] = state;
    return state;
  }

  function applyBacktestDerivedPrefill(state) {
    if (state.kind !== "backtest") return;
    const raw = sessionStorage.getItem("ft-backtest-derived-prefill");
    if (!raw) return;
    let value;
    try { value = JSON.parse(raw); } catch (_) { return; }
    if (!value || value.workspaceID !== state.workspace?.workspace_id) return;
    sessionStorage.removeItem("ft-backtest-derived-prefill");
    const parentID = String(value.parentID || "");
    if (!state.analysis.groups.some(group => String(group.id || "") === parentID)) return;
    state.backtestGroupEditor = {
      mode: "derived", parentID,
      productMask: Array.isArray(value.products) ? value.products : [],
      name: String(value.name || ""),
    };
    state.backtestGroupsOpen = true;
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
    const payload = state.workspace?.configuration?.payload || {};
    return payload.ui?.[state.kind]?.settings
      || state.analysis.local_settings || state.analysis.settings || {};
  }

  function savedMountedTabs(state) {
    const saved = state.workspace?.configuration?.payload?.ui?.[state.kind]?.mounted_tabs;
    return Array.isArray(saved) ? saved : undefined;
  }

  function render(context, state) {
    const root = document.createElement("div");
    root.className = "test-workbench";
    root.append(FTTestSettings.render(state.manifest, state.values, context, {
      kind: state.kind,
      activeTab: state.settingsTabKey,
      mountedTabs: state.settingsMountedTabs,
      onTabChange: key => {
        state.settingsTabKey = key;
      },
      onMountedTabsChange: tabs => {
        state.settingsMountedTabs = tabs;
        state.settingsTabKey = "__manage__";
        render(context, state);
      },
      state,
      chipSources: FTTestContentAdapters.chipSources(state),
      actions: {templates: {
        save: () => saveTemplate(context, state),
        load: template => loadTemplate(context, state, template),
        overwrite: template => overwriteTemplate(context, state, template),
        delete: template => deleteTemplate(context, state, template),
      }},
      onChipOpen: tabKey => {
        if (!state.settingsMountedTabs.includes(tabKey)) {
          state.settingsMountedTabs = [...state.settingsMountedTabs, tabKey];
        }
        state.settingsTabKey = tabKey;
        render(context, state);
      },
      refresh: () => render(context, state),
    }));
    if (state.kind === "backtest") {
      root.append(FTBacktestGroups.render(context, state, () => render(context, state)));
    }
    const runOptions = FTTestRunFields.render(
      context, state, () => render(context, state),
    );
    if (runOptions) root.append(runOptions);
    if (FTOutputChoices.available(state.outputCapabilities, state.kind).length) {
      root.append(FTTestOutputs.render(context, state));
    }
    root.append(FTTestRunBatch.render(context, state, () => render(context, state)));
    context.content.replaceChildren(root);
  }

  async function saveTemplate(context, state) {
    const name = prompt(context.t("模板名称"));
    if (!name?.trim()) return;
    const group = selectedExecutionGroup(context, state);
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
    state.settingsMountedTabs = FTTestSettings.initialMountedTabs(
      state.manifest, savedMountedTabs(state),
    );
    state.values = FTTestSettings.initialValues(
      state.manifest, savedSettings(state), state.settingsMountedTabs,
    );
    state.settingsTabKey = "";
    FTTestProducts.synchronize(state);
    await FTTestFactors.initialize(context, state);
    await FTTestCategories.initialize(context, state);
    render(context, state);
  }

  async function overwriteTemplate(context, state, template) {
    if (!confirm(`${context.t("用当前设置覆盖模板")}「${template.name}」？`)) return;
    try {
      const group = selectedExecutionGroup(context, state);
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

  function selectedExecutionGroup(context, state) {
    const groups = FTTestProducts.selectedGroups(state);
    if (!groups.length) throw new Error(context.t("请选择产品组"));
    const requested = state.kind === "ic" ? state.groupRefs : [state.groupRef];
    if (groups.length !== requested.filter(Boolean).length) {
      throw new Error(context.t("所选产品组已不可用，请重新选择"));
    }
    return groups[0];
  }

  window.FTTests = {applyBacktestDerivedPrefill, show};
})();
