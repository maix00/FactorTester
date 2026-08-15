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

  function initialRunValues(manifest) {
    const values = {};
    (manifest?.run_fields || []).forEach(item => {
      if (item.placement !== "outputs") values[item.key] = structuredClone(item.default);
    });
    return values;
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

  async function loadState(context, kind, options) {
    const sessions = context.tabSession || (context.tabSession = {});
    sessions.tests = sessions.tests || {};
    if (sessions.tests[kind]) return sessions.tests[kind];
    const application = definitions[kind].application;
    const savedWorkspaceID = localStorage.getItem(`ft-${kind}-workspace`) || "";
    const savedWorkspaceConfigurationPromise = savedWorkspaceID
      ? context.api(`/api/workspaces/${encodeURIComponent(savedWorkspaceID)}/configuration`)
        .then(value => ({value, error: null}))
        .catch(error => ({value: null, error}))
      : Promise.resolve({value: null, error: null});
    const [manifest, workspaces, savedWorkspaceConfiguration] = await Promise.all([
      context.api(`/api/backtest/settings/${application}/summary`),
      context.api("/api/workspace-summaries"),
      savedWorkspaceConfigurationPromise,
    ]);
    const state = {
      kind, manifest,
      factors: [], families: [], groups: [],
      workspaces: workspaces.workspaces || [], templates: [],
      workspace: null, factorRef: "", groupRef: "", groupRefs: [], analysis: {}, values: null,
      settingsTabKey: "", settingsMountedTabs: [],
      outputCapabilities: [], outputCapabilitiesLoaded: false,
      outputRequests: [],
      profiles: [], profilesLoaded: false,
      lazy: FTTestState.lazyState(),
      runValues: initialRunValues(manifest),
      runCode: {status: "idle", error: "", promise: null},
      runBatchCode: {status: "idle", error: "", promise: null},
      settingsCode: {status: "idle", error: "", promise: null},
      settingsInitialized: false,
      settingsFieldsCode: {status: "idle", error: "", promise: null},
      settingsChipsCode: {status: "idle", error: "", promise: null},
      settingsTabLoads: Object.create(null),
      settingsLoadedTabs: new Set(),
    };
    FTTestState.restoreWorkspace(state);
    if (state.workspace && !state.workspace.configuration) {
      let value = null;
      if (state.workspace.workspace_id === savedWorkspaceID) {
        if (savedWorkspaceConfiguration.error) throw savedWorkspaceConfiguration.error;
        value = savedWorkspaceConfiguration.value;
      } else {
        const workspaceID = encodeURIComponent(state.workspace.workspace_id);
        value = await context.api(`/api/workspaces/${workspaceID}/configuration`);
      }
      state.workspace.configuration = value?.configuration || null;
      FTTestState.applyWorkspaceConfiguration(state);
    }
    if (options.factorRef) state.factorRef = options.factorRef;
    if (options.groupRef) {
      state.groupRef = options.groupRef;
      state.groupRefs = [options.groupRef];
    }
    FTTestState.initializeInputState(state);
    if (kind === "factor_evaluation" && state.runValues.retention_mode === "summary") {
      state.runValues.retention_mode = "full";
    }
    FTTestState.seedSavedCatalogs(state);
    window.FTTestFactors?.prepare?.(state);
    window.FTTestProducts?.synchronize?.(state);
    window.FTBacktestGroups?.initialize?.(state);
    applyBacktestDerivedPrefill(state);
    sessions.tests[kind] = state;
    return state;
  }

  function lazyReady(state, key) {
    return state.lazy?.[key]?.status === "ready";
  }

  function lazyStatus(state, key) {
    return state.lazy?.[key] || {status: "ready", error: ""};
  }

  function ensureTab(context, state, tab, refresh) {
    const key = FTTestContentAdapters.lazyKey(tab);
    return FTTestLazyCode.loadGroup(FTTestLazyCode.codeGroupForTab(tab))
      .then(() => ensureLazyKey(context, state, key, refresh));
  }

  function ensureRunCode(context, state, refresh) {
    if (window.FTTestRunFields) return Promise.resolve();
    return FTTestLazyCode.ensureGroupCode(
      state, "runCode", "workbench-run", null, refresh,
    );
  }

  function ensureRunBatchCode(context, state, refresh) {
    return FTTestLazyCode.ensureRunBatchCode(state, refresh);
  }

  function initializeSettings(state) {
    if (state.settingsInitialized || !window.FTTestSettings) return;
    state.settingsMountedTabs = FTTestSettings.initialMountedTabs(
      state.manifest, FTTestState.savedMountedTabs(state),
    );
    state.values = FTTestSettings.initialValues(
      state.manifest, FTTestState.savedSettings(state), state.settingsMountedTabs,
    );
    state.settingsInitialized = true;
  }

  function ensureSettingsCode(context, state, refresh) {
    if (window.FTTestSettings) {
      initializeSettings(state);
      return Promise.resolve();
    }
    return FTTestLazyCode.ensureGroupCode(
      state, "settingsCode", "workbench-settings",
      () => initializeSettings(state), refresh,
    );
  }

  function ensureSettingsFieldsCode(context, state, refresh) {
    if (window.FTTestSettingFields) return Promise.resolve();
    return FTTestLazyCode.ensureGroupCode(
      state, "settingsFieldsCode", "workbench-settings-fields", null, refresh,
    );
  }

  function ensureRunSubmitCode(context, state) {
    // Building and persisting a configuration is an action boundary, not a
    // render dependency. Keep the compiler/Workspace writer out of the
    // initial test page and load it only when preview/run/template actions
    // actually need it. The loader coalesces repeated clicks safely.
    return FTTestLazyCode.loadGroup("workbench-run-submit");
  }

  function ensureControl(context, state, field, refresh) {
    const descriptor = window.FTStaticLoader?.controlDescriptor?.(
      field?.value_descriptor?.editor,
    );
    if (!descriptor?.group) return Promise.resolve();
    return FTTestControlLoader.ensure(state, descriptor.group, refresh);
  }

  function ensureLazyKey(context, state, key, refresh) {
    if (!key || lazyReady(state, key)) return Promise.resolve();
    const record = state.lazy[key];
    if (!record) return Promise.resolve();
    if (record.status === "loading" && record.promise) return record.promise;
    if (record.status === "error") return Promise.resolve();
    record.status = "loading";
    record.error = "";
    record.promise = loadLazyState(context, state, key)
      .then(() => { record.status = "ready"; refresh?.(); })
      .catch(error => {
        record.status = "error";
        record.error = error.message || String(error);
        refresh?.();
      });
    return record.promise;
  }

  async function loadLazyState(context, state, key) {
    if (key === "factors") {
      await FTTestLazyCode.loadGroup("workbench-factors");
      const value = await context.api("/api/catalog/factors");
      state.factors = FTTestState.mergeByID(state.factors, value.factors);
      state.families = FTTestState.mergeByID(state.families, value.families);
      await FTTestFactors.initialize(context, state);
      return;
    }
    if (key === "products") {
      await FTTestLazyCode.loadGroup("workbench-products");
      const value = await context.api("/api/catalog/product-groups");
      const catalog = Array.isArray(value.groups) ? value.groups : [];
      const selected = state.groups.filter(group => group._savedPlaceholder
        && state.groupRefs.includes(FTTestLazyCode.groupID(group)));
      // Replace placeholders while preserving unresolved selected references.
      state.groups = FTTestState.mergeByID(selected, catalog);
      FTTestProducts.synchronize(state);
      if (state.kind === "backtest") FTBacktestGroups.initialize(state);
      return;
    }
    if (key === "categories") {
      await FTTestLazyCode.loadGroup("workbench-products");
      await FTTestCategories.initialize(context, state);
      return;
    }
    if (key === "templates") {
      await FTTestLazyCode.loadGroup("workbench-templates");
      const value = await context.api("/api/configuration-templates");
      state.templates = Array.isArray(value.templates) ? value.templates : [];
      return;
    }
    if (key === "outputs") {
      const value = await context.api("/api/jobs/artifact-capabilities");
      state.outputCapabilities = Array.isArray(value.outputs) ? value.outputs : [];
      state.outputCapabilitiesLoaded = true;
      state.outputRequests = FTOutputChoices.initialSelection(
        state.outputCapabilities, state.kind,
        state.outputRequestsExplicit ? state.outputRequests : undefined,
      );
      return;
    }
    if (key === "profiles") {
      const value = await context.api("/api/client/profiles").catch(() => ({profiles: []}));
      state.profiles = Array.isArray(value.profiles) ? value.profiles : [];
      state.profilesLoaded = true;
    }
  }

  async function ensureProductsForExecution(context, state) {
    if (lazyReady(state, "products")) return;
    await ensureLazyKey(context, state, "products");
  }

  async function ensureFactorsForExecution(context, state) {
    await FTTestLazyCode.loadGroup("workbench-factors");
    await ensureLazyKey(context, state, "factors");
  }

  function render(context, state) {
    const root = document.createElement("div");
    root.className = "test-workbench";
    if (!window.FTTestSettings || !state.settingsInitialized) {
      const loading = FTUI.loading(context.t("正在读取测试设置代码…"));
      const error = state.settingsCode?.error;
      root.append(error
        ? FTUI.empty(context.t("读取测试设置失败"), error)
        : loading);
      if (!error) {
        ensureSettingsCode(context, state, () => render(context, state));
      }
      // Settings and run-spec code are independent dynamic groups. Starting
      // both from the lightweight manifest state avoids a serial waterfall;
      // neither group loads field controls, catalogs, strategy editors, or
      // result viewers for tabs that have not been mounted.
      if (!state.runCode?.error) {
        ensureRunCode(context, state, () => render(context, state));
      }
      context.content.replaceChildren(root);
      return;
    }
    const templateActions = FTTestTemplateActions.create(context, state, {
      ensureRunCode: () => ensureRunCode(context, state),
      ensureRunSubmitCode: () => ensureRunSubmitCode(context, state),
      render: () => render(context, state),
    });
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
      actions: {templates: templateActions},
      lazyState: key => lazyStatus(state, key),
      ensureControl: field => ensureControl(
        context, state, field, () => render(context, state),
      ),
      ensureRunCode: () => ensureRunCode(context, state, () => render(context, state)),
      ensureSettingsFieldsCode: () => ensureSettingsFieldsCode(
        context, state, () => render(context, state),
      ),
      ensureSettingsChipsCode: () => FTTestLazyCode.ensureGroupCode(
        state, "settingsChipsCode", "workbench-settings-chips", null,
        () => render(context, state),
      ),
      ensureSettingsTab: tabKey => ensureSettingsTab(
        context, state, tabKey, () => render(context, state),
      ),
      settingsTabReady: tabKey => state.settingsLoadedTabs.has(tabKey),
      settingsTabLoadState: tabKey => state.settingsTabLoads[tabKey],
      ensureTab: tab => ensureTab(context, state, tab, () => render(context, state)),
      onChipOpen: tabKey => {
        const runTab = state.manifest.run_settings?.key;
        if (tabKey === runTab) {
          state.settingsTabKey = tabKey;
          render(context, state);
          return;
        }
        if (!state.settingsMountedTabs.includes(tabKey)) {
          state.settingsMountedTabs = [...state.settingsMountedTabs, tabKey];
        }
        state.settingsTabKey = tabKey;
        render(context, state);
      },
      refresh: () => render(context, state),
    }));
    if (!window.FTTestSettingChips && !state.settingsChipsCode?.error) {
      // Keep the first paint independent from the value-to-chip formatter.
      // The settings shell remains interactive while this small presentation
      // module is fetched and then the shell is repainted once.
      FTTestLazyCode.ensureGroupCode(
        state, "settingsChipsCode", "workbench-settings-chips", null,
        () => render(context, state),
      );
    }
    if (state.kind === "backtest") {
      root.append(window.FTBacktestGroups?.render
        ? FTBacktestGroups.render(context, state, () => render(context, state))
        : FTTestLazyCode.deferredPanel(context, state, "分组策略", "workbench-backtest", () => render(context, state)));
    }
    if (window.FTTestRunBatch) {
      root.append(FTTestRunBatch.render(context, state, () => render(context, state)));
    } else {
      const runBatchCode = state.runBatchCode || {};
      if (FTTestLazyCode.hasSelectedProductPaths(state)) {
        root.append(runBatchCode.status === "error"
          ? FTUI.empty(context.t("读取任务代码失败"), runBatchCode.error)
          : FTUI.loading(context.t("正在读取产品路径任务代码…")));
        ensureRunBatchCode(context, state, () => render(context, state));
      } else {
        const deferred = document.createElement("section");
        deferred.className = "test-run-batch test-code-deferred-panel";
        const title = document.createElement("strong");
        title.textContent = context.t("产品路径任务");
        const note = document.createElement("small");
        note.textContent = context.t("选择产品路径后加载任务代码");
        deferred.append(title, note);
        root.append(deferred);
      }
    }
    context.content.replaceChildren(root);
  }

  function ensureSettingsTab(context, state, tabKey, refresh) {
    // The schema loader belongs to the same deferred group as editable field
    // controls. A direct request must cross that code boundary first.
    return ensureSettingsFieldsCode(context, state, refresh)
      .then(() => FTTestSettingsSchema.ensureTab(context, state, tabKey, refresh));
  }

  window.FTTests = {
    applyBacktestDerivedPrefill,
    ensureOutputCapabilities: async (context, state, refresh) => {
      await FTTestLazyCode.loadGroup("output-choice");
      return ensureLazyKey(context, state, "outputs", refresh);
    },
    ensureProfiles: (context, state, refresh) => ensureLazyKey(context, state, "profiles", refresh),
    ensureFactorsForExecution, ensureProductsForExecution, show,
    ensureRunCode,
    ensureRunBatchCode,
    ensureSettingsCode,
    ensureSettingsFieldsCode,
    ensureSettingsTab,
    ensureRunSubmitCode,
    ensureControl: (context, state, field, refresh) => (
      ensureControl(context, state, field, refresh)
    ),
  };
})();
