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
    // Catalogs and adapters load only when their backend-declared tab is used.
    // The route only loads the small workbench coordinator.  Settings are a
    // separate code seam because their tab/chip renderer is not needed by
    // the route guard or by the initial API requests.  Start both requests
    // together so code fetch and server latency overlap, then construct the
    // state only after the settings implementation is available.
    const [manifest, workspaces] = await Promise.all([
      context.api(`/api/backtest/settings/${application}`),
      context.api("/api/workspaces"),
      FTTestLazyCode.loadGroup("workbench-settings"),
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
    };
    FTTestState.restoreWorkspace(state);
    if (options.factorRef) state.factorRef = options.factorRef;
    if (options.groupRef) {
      state.groupRef = options.groupRef;
      state.groupRefs = [options.groupRef];
    }
    state.settingsMountedTabs = FTTestSettings.initialMountedTabs(
      manifest, FTTestState.savedMountedTabs(state),
    );
    state.values = FTTestSettings.initialValues(
      manifest, FTTestState.savedSettings(state), state.settingsMountedTabs,
    );
    FTTestInputState.initialize(state);
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
    if (window.FTTestRunFields && window.FTTestRunBatch) return Promise.resolve();
    const record = state.runCode || (state.runCode = {
      status: "idle", error: "", promise: null,
    });
    if (record.status === "ready") return Promise.resolve();
    if (record.status === "loading" && record.promise) return record.promise;
    record.status = "loading";
    record.error = "";
    record.promise = FTTestLazyCode.loadGroup("workbench-run")
      .then(() => {
        record.status = "ready";
        refresh?.();
      })
      .catch(error => {
        record.status = "error";
        record.error = error.message || String(error);
        refresh?.();
      });
    return record.promise;
  }

  function ensureRunSubmitCode(context, state) {
    // Building and persisting a configuration is an action boundary, not a
    // render dependency. Keep the compiler/Workspace writer out of the
    // initial test page and load it only when preview/run/template actions
    // actually need it. The loader coalesces repeated clicks safely.
    return FTTestLazyCode.loadGroup("workbench-run-submit");
  }

  function ensureControl(context, state, field, refresh) {
    const descriptor = window.FTStaticLoader?.controlDescriptor?.(field?.control_template);
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
    if (state.kind === "backtest") {
      root.append(window.FTBacktestGroups?.render
        ? FTBacktestGroups.render(context, state, () => render(context, state))
        : FTTestLazyCode.deferredPanel(context, state, "分组策略", "workbench-backtest", () => render(context, state)));
    }
    if (window.FTTestRunBatch) {
      root.append(FTTestRunBatch.render(context, state, () => render(context, state)));
    } else {
      const runCode = state.runCode || {};
      root.append(runCode.status === "error"
        ? FTUI.empty(context.t("读取运行配置失败"), runCode.error)
        : FTUI.loading(context.t("正在读取运行配置…")));
      ensureRunCode(context, state, () => render(context, state));
    }
    context.content.replaceChildren(root);
  }

  window.FTTests = {
    applyBacktestDerivedPrefill,
    ensureOutputCapabilities: (context, state, refresh) => (
      ensureLazyKey(context, state, "outputs", refresh)
    ),
    ensureProfiles: (context, state, refresh) => ensureLazyKey(context, state, "profiles", refresh),
    ensureFactorsForExecution, ensureProductsForExecution, show,
    ensureRunCode,
    ensureRunSubmitCode,
    ensureControl: (context, state, field, refresh) => (
      ensureControl(context, state, field, refresh)
    ),
  };
})();
