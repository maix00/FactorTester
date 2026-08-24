(() => {
  const clientScope = new URLSearchParams(window.location?.search || "").get("client") || "web";
  window.FTTestClientScope = clientScope;
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
    installRunToolbar(context, null, () => {});
    context.content.replaceChildren(FTUI.loading(context.t("正在读取测试设置…")));
    const state = await loadState(context, kind, options);
    if (context.isRouteCurrent?.() === false) return;
    applyTabReturn(state, context);
    render(context, state);
  }

  function placeholderRunActions(context) {
    return ["查看运行配置", "运行", "清空"].map(label => {
      const action = context.button(
        context.t(label), () => {}, context.t("正在读取测试运行操作…"),
      );
      action.className = "test-workbench-header-action";
      action.disabled = true;
      return action;
    });
  }

  function installRunToolbar(context, state, refresh) {
    const toolbar = context.toolbar;
    if (!toolbar) return;
    toolbar.replaceChildren();
    let actions = null;
    if (state && window.FTTestRunBatch?.headerActions) {
      try {
        actions = window.FTTestRunBatch.headerActions(context, state, refresh);
      } catch (_) {
        // The run-batch model can arrive one tick after the page shell. Keep
        // the two stable header actions visible until its deferred group is
        // ready instead of allowing a stale/empty toolbar to flash.
      }
    }
    toolbar.append(...(actions || placeholderRunActions(context)));
  }

  function applyTabReturn(state, context) {
    const result = window.FTTabReturn?.consume(context.tabID);
    if (!result) return;
    const key = result.kind === "factor" ? "factors"
      : result.kind === "product_group" ? "products"
      : result.kind === "category" ? "categories" : "";
    if (!key) return;
    state.pendingTabReturn = {key, ref: String(result.ref || "")};
    if (state.lazy?.[key]?.status === "ready") applyPendingSelection(state, key);
    else if (state.lazy?.[key]) state.lazy[key].status = "idle";
  }

  function applyPendingSelection(state, key) {
    const pending = state.pendingTabReturn;
    if (!pending || pending.key !== key || !pending.ref) return false;
    let applied = false;
    if (key === "products") {
      const group = state.groups.find(item => FTTestProducts.groupID(item) === pending.ref
        || String(item.id || "") === pending.ref
        || String(item.name || "") === pending.ref);
      if (group) {
        FTTestProducts.selectNew(state, group);
        applied = true;
      }
    } else if (key === "factors") {
      const factor = state.factors.find(item => (
        FTTestFactorSelection.factorID(item) === pending.ref
        || FTTestFactorSelection.factorAlias(item) === pending.ref
        || String(item.id || "") === pending.ref
      ));
      if (factor) {
        FTTestFactorSelection.addCandidate(state, factor);
        applied = true;
      }
    } else if (key === "categories") {
      const category = (state.values?.category_candidates || []).find(item => (
        FTTestCategories.categoryID(item) === pending.ref
        || String(item.id || "") === pending.ref
      ));
      if (category) {
        state.values.category = FTTestCategories.categoryID(category);
        applied = true;
      }
    }
    if (!applied && state.lazy?.[key]?.status === "ready") {
      // A newly saved object may not be present in the cached catalog yet.
      // Re-open the lazy source once so the independent editor can return a
      // real object instead of leaving the picker silently unselected.
      state.lazy[key].status = "idle";
      if (key === "categories") state.values.category_candidates = [];
    }
    if (applied) delete state.pendingTabReturn;
    return applied;
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
    const requestedWorkspaceID = String(options.workspaceID || "");
    const savedDraft = requestedWorkspaceID ? null : sessions.durable?.testDrafts?.[kind];
    const application = definitions[kind].application;
    const clientQuery = clientScope === "web"
      ? ""
      : `?client=${encodeURIComponent(clientScope)}`;
    const savedWorkspaceID = requestedWorkspaceID || (
      savedDraft?.schemaVersion === 2 ? String(savedDraft.workspaceID || "") : ""
    );
    const savedWorkspaceConfigurationPromise = savedWorkspaceID
      ? context.api(`/api/workspaces/${encodeURIComponent(savedWorkspaceID)}/configuration`)
        .then(value => ({value, error: null}))
        .catch(error => ({value: null, error}))
      : Promise.resolve({value: null, error: null});
    const [manifest, workspaces, savedWorkspaceConfiguration] = await Promise.all([
      context.api(`/api/backtest/settings/${application}/summary${clientQuery}`),
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
      runtimeServers: null, runtimeServersLoaded: false,
      runtimeServersLoading: false,
      lazy: FTTestState.lazyState(),
      runValues: FTTestState.defaultRunValues(manifest),
      runCode: {status: "idle", error: "", promise: null},
      runBatchCode: {status: "idle", error: "", promise: null},
      backtestCode: {status: "idle", error: "", promise: null},
      settingsCode: {status: "idle", error: "", promise: null},
      settingsInitialized: false,
      settingsFieldsCode: {status: "idle", error: "", promise: null},
      settingsChipsCode: {status: "idle", error: "", promise: null},
      settingsTabLoads: Object.create(null),
      settingsLoadedTabs: new Set(),
      restoredWorkspaceID: savedWorkspaceID,
    };
    if (requestedWorkspaceID) {
      state.workspace = state.workspaces.find(item => (
        String(item.workspace_id || "") === requestedWorkspaceID
      )) || {workspace_id: requestedWorkspaceID};
    } else FTTestState.restoreWorkspace(state);
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
    FTTestState.restoreDraft(state, savedDraft);
    window.FTTestFactors?.prepare?.(state);
    window.FTTestProducts?.synchronize?.(state);
    window.FTBacktestGroups?.initialize?.(state);
    applyBacktestDerivedPrefill(state);
    state.restoredJob = options.restoredJob || null;
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

  function ensureBacktestCode(context, state, refresh) {
    if (state.kind !== "backtest" || window.FTBacktestGroups) return Promise.resolve();
    return FTTestLazyCode.ensureGroupCode(
      state, "backtestCode", "workbench-backtest",
      () => window.FTBacktestGroups?.initialize?.(state), refresh,
    );
  }

  function settingsRuntimeReady() {
    return Boolean(
      window.FTTestSettings
      && window.FTTestContentAdapters
      && window.FTSettingRules,
    );
  }

  function initializeSettings(state) {
    if (state.settingsInitialized) return true;
    if (!settingsRuntimeReady()) return false;
    state.settingsMountedTabs = FTTestSettings.initialMountedTabs(
      state.manifest, FTTestState.savedMountedTabs(state),
    );
    state.values = FTTestSettings.initialValues(
      state.manifest, FTTestState.savedSettings(state), state.settingsMountedTabs,
    );
    FTTestState.restoreTemporaryObjects?.(state);
    state.settingsInitialized = true;
    return true;
  }

  function ensureSettingsCode(context, state, refresh) {
    if (state.settingsInitialized) return Promise.resolve();
    const initialize = () => {
      if (!initializeSettings(state)) {
        throw new Error("测试设置模块尚未完成初始化");
      }
    };
    const record = state.settingsCode || (state.settingsCode = {
      status: "idle", error: "", promise: null,
    });
    const recoverReadyState = () => {
      // A previous loader could have marked the group ready before the
      // runtime globals were installed. Do not leave the workbench in an
      // eternal loading state; finish initialization on the next render.
      if (state.settingsInitialized || record.error) return;
      try {
        initialize();
        refresh?.();
      } catch (error) {
        record.status = "error";
        record.error = error.message || String(error);
        refresh?.();
      }
    };
    if (record.status === "ready") {
      recoverReadyState();
      return Promise.resolve();
    }
    return FTTestLazyCode.ensureGroupCode(
      state, "settingsCode", "workbench-settings",
      initialize, refresh,
    ).then(recoverReadyState);
  }

  function settingsFieldsRuntimeReady() {
    return Boolean(
      window.FTTestSettingFields
      && window.FTTestSettingsSchema
      && typeof window.FTTestSettingsSchema.ensureTab === "function",
    );
  }

  function settingsFieldsRecord(state) {
    return state.settingsFieldsCode || (state.settingsFieldsCode = {
      status: "idle", error: "", promise: null,
    });
  }

  function markSettingsFieldsError(state, error, refresh) {
    const record = settingsFieldsRecord(state);
    record.status = "error";
    record.error = error?.message || String(error || "测试设置字段模块加载不完整");
    record.promise = null;
    refresh?.();
  }

  function ensureSettingsFieldsCode(context, state, refresh) {
    const record = settingsFieldsRecord(state);
    if (settingsFieldsRuntimeReady()) {
      record.status = "ready";
      record.error = "";
      return Promise.resolve();
    }
    // A controls-only request can leave this shared record in `ready` before
    // the schema script has been evaluated.  Re-open the group instead of
    // allowing callers to dereference a missing global.
    if (record.status === "ready") {
      record.status = "idle";
      record.promise = null;
    }
    if (record.status === "error") return Promise.resolve();
    return FTTestLazyCode.ensureGroupCode(
      state, "settingsFieldsCode", "workbench-settings-fields", null, refresh,
    ).then(() => {
      if (!settingsFieldsRuntimeReady()) {
        markSettingsFieldsError(
          state,
          record.error || new Error("测试设置字段模块加载不完整"),
          refresh,
        );
      }
    }).catch(error => {
      // ensureGroupCode normally records failures itself, but keep this
      // boundary non-rejecting because it is also called from render paths.
      markSettingsFieldsError(state, error, refresh);
    });
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
    // Repaint immediately so the already-rendered field row can expose the
    // picker-local loading state while the catalog request is in flight.
    // The field layout never waits for this promise.
    refresh?.();
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
      applyPendingSelection(state, key);
      return;
    }
    if (key === "products") {
      await FTTestLazyCode.loadGroup("workbench-products");
      const value = await context.api("/api/catalog/product-groups");
      const catalog = Array.isArray(value.groups) ? value.groups : [];
      const selected = state.groups.filter(group => (
        group.temporary === true || group.source_kind === "transient"
        || ["inline", "test_inline"].includes(group.origin)
        || ["inline", "test_inline"].includes(group.source_origin)
        || (group._savedPlaceholder
          && state.groupRefs.includes(FTTestLazyCode.groupID(group)))
      ));
      // Merge refreshed catalog fields into inline/test-inline objects without
      // erasing their authoring origin; unresolved inline-only objects remain.
      const selectedByID = new Map(selected.map(group => [
        FTTestLazyCode.groupID(group), group,
      ]));
      const mergedCatalog = catalog.map(group => {
        const inline = selectedByID.get(FTTestLazyCode.groupID(group));
        if (!inline) return group;
        return {
          ...inline, ...group,
          ...(inline.origin ? {origin: inline.origin} : {}),
          ...(inline.source_origin ? {source_origin: inline.source_origin} : {}),
        };
      });
      state.groups = FTTestState.mergeByID(selected, mergedCatalog);
      FTTestProducts.synchronize(state);
      if (state.kind === "backtest") FTBacktestGroups.initialize(state);
      applyPendingSelection(state, key);
      return;
    }
    if (key === "categories") {
      await FTTestLazyCode.loadGroup("workbench-products");
      await FTTestCategories.initialize(context, state);
      applyPendingSelection(state, key);
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
    // Grouped IC opens from a module that already depends on the factor
    // picker. Avoid re-entering the manifest loader in that path: on a fresh
    // editor the redundant load could reject before the catalog request and
    // leave `lazy.factors` permanently idle/loading in the rendered picker.
    if (!window.FTTestFactors) {
      await FTTestLazyCode.loadGroup("workbench-factors");
    }
    await ensureLazyKey(context, state, "factors");
  }

  function render(context, state) {
    // Every deferred loader and job-progress callback closes over the route
    // token in this context. The shared content host may already belong to a
    // different left-rail tab by the time it resolves.
    if (context.isRouteCurrent?.() === false) return false;
    const durable = context.tabSession.durable || (context.tabSession.durable = {});
    durable.testDrafts = durable.testDrafts || {};
    durable.testDrafts[state.kind] = FTTestState.draftSnapshot(state);
    context.checkpointTabSession?.();
    installRunToolbar(context, state, () => render(context, state));
    if (!window.FTTestRunBatch && !state.runBatchCode?.error) {
      // The header owns the run actions. Load their small controller lazily;
      // do not reintroduce the removed lower run-task panel.
      ensureRunBatchCode(context, state, () => render(context, state));
    }
    const root = document.createElement("div");
    root.className = "test-workbench";
    root.dataset.ftRerenderOnTabRestore = "true";
    root.__ftBeforeTabSave = () => {
      window.FTTestRunProgress?.suspend?.(
        window.FTTestRunBatch?.submittedItems?.(state) || [],
      );
    };
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
      settingsFieldsLoadState: () => state.settingsFieldsCode,
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
    const groupSurfaces = (state.manifest?.surfaces || []).some(surface => (
      surface.kind === "list" && surface.mount === "group-settings"
    ));
    if (groupSurfaces) {
      const groupRenderer = window.FTConfigurationGroupSurface?.renderer?.(state.kind);
      if (groupRenderer?.render) {
        root.append(groupRenderer.render(context, state, () => render(context, state)));
      } else {
        const code = state.backtestCode || {};
        root.append(code.status === "error"
          ? FTUI.empty(context.t("读取配置组列表失败"), code.error)
          : FTUI.loading(context.t("正在读取配置组列表…")));
        if (state.kind === "backtest") ensureBacktestCode(context, state, () => render(context, state));
      }
    }
    if (window.FTTestRunBatch?.renderSubmitted) {
      const submitted = window.FTTestRunBatch.renderSubmitted(
        context, state, () => render(context, state),
      );
      if (submitted) root.append(submitted);
    }
    context.content.replaceChildren(root);
    return true;
  }

  async function clearDraft(context, state, refresh) {
    if (!window.confirm(context.t("确定清空当前测试配置吗？"))) return false;
    const workspaceID = String(state.workspace?.workspace_id || "");
    if (workspaceID) {
      await context.api(`/api/workspaces/${encodeURIComponent(workspaceID)}`, {
        method: "DELETE",
      });
    }
    FTTestState.clearDraft(state);
    initializeSettings(state);
    window.FTTestFactors?.prepare?.(state);
    window.FTTestProducts?.synchronize?.(state);
    window.FTBacktestGroups?.initialize?.(state);
    context.showNotice?.(context.t("当前测试配置已清空"));
    refresh?.();
    return true;
  }

  function ensureSettingsTab(context, state, tabKey, refresh) {
    // The schema loader belongs to the same deferred group as editable field
    // controls. A direct request must cross that code boundary first.
    return ensureSettingsFieldsCode(context, state, refresh)
      .then(() => {
        if (!settingsFieldsRuntimeReady()) {
          const error = new Error(
            settingsFieldsRecord(state).error || "测试设置字段模块加载不完整",
          );
          const load = state.settingsTabLoads[tabKey] || (state.settingsTabLoads[tabKey] = {
            status: "idle", error: "", promise: null,
          });
          load.status = "error";
          load.error = error.message;
          refresh?.();
          return null;
        }
        return window.FTTestSettingsSchema.ensureTab(context, state, tabKey, refresh);
      })
      .catch(error => {
        const load = state.settingsTabLoads[tabKey] || (state.settingsTabLoads[tabKey] = {
          status: "idle", error: "", promise: null,
        });
        load.status = "error";
        load.error = error.message || String(error);
        load.promise = null;
        refresh?.();
      });
  }

  window.FTTests = {
    applyBacktestDerivedPrefill,
    applyPendingSelection,
    ensureOutputCapabilities: async (context, state, refresh) => {
      await FTTestLazyCode.loadGroup("output-choice");
      return ensureLazyKey(context, state, "outputs", refresh);
    },
    ensureProfiles: (context, state, refresh) => ensureLazyKey(context, state, "profiles", refresh),
    ensureFactorsForExecution, ensureProductsForExecution, show,
    ensureRunCode,
    ensureRunBatchCode,
    ensureBacktestCode,
    ensureSettingsCode,
    ensureSettingsFieldsCode,
    ensureSettingsTab,
    ensureRunSubmitCode,
    ensureControl: (context, state, field, refresh) => (
      ensureControl(context, state, field, refresh)
    ),
    clearDraft,
    render,
  };
})();
