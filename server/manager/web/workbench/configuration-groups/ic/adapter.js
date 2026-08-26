(() => {
  const productHydrations = new WeakMap();
  const adapter = Object.freeze({
    render: configurationList,
    selected: state => FTICConfigurationGroupModel.selected(state),
    removeSelected: state => FTICConfigurationGroupModel.removeSelected(state),
    actions: Object.freeze({
      create: () => ({mode: "create"}),
      edit: (_state, selected) => ({
        mode: "edit", groupID: selected[0]?.config_group_id,
      }),
    }),
  });
  const adapters = Object.freeze({ic_configuration_groups: adapter});

  function initialize(state) {
    if (state.kind === "ic") FTICConfigurationGroupModel.initialize(state);
  }

  function render(context, state, refresh) {
    initialize(state);
    if (state.icConfigurationGroupShowConfigOpen === true) {
      hydrateSummaryProducts(context, state, refresh);
    }
    const editor = state.icConfigurationGroupEditor;
    if (editor?.groupID && !FTICConfigurationGroupModel.find(state, editor.groupID)) {
      state.icConfigurationGroupEditor = null;
    }
    if (state.icConfigurationGroupEditor && editorCatalogsNeedLoad(state)) {
      loadEditorCatalogs(
        context, state,
        {kind: state.icConfigurationGroupEditor.groupID ? "edit" : "create"},
        refresh,
      );
    }
    return FTConfigurationGroupSurface.render({
      context, state, refresh, adapters, initialize,
      title: "配置组设置",
      description: "每个配置组冻结一个因子、一个产品组和一个 Delay",
      count: `${state.analysis.configuration_groups.length} ${context.t("个配置组")}`,
      activeKey: "icConfigurationGroupSurfaceKey",
      openKey: "icConfigurationGroupsOpen",
      editorKey: "icConfigurationGroupEditor",
      className: "backtest-groups ic-configuration-groups",
      summaryClass: "backtest-group-summary ic-configuration-group-summary",
      countClass: "backtest-group-count ic-configuration-group-count",
      summaryCopyClass: "backtest-group-summary-copy",
      shellClass: "backtest-group-shell ic-configuration-group-shell",
      barClass: "backend-settings-tab-bar backtest-group-tab-bar",
      hostClass: "backend-settings-host backtest-group-host",
      panelClass: "backtest-group-panel ic-configuration-group-panel",
      onToggleConfig: open => {
        state.icConfigurationGroupShowConfigOpen = open;
        refresh();
      },
      emptyTitle: "暂无配置组设置",
      emptyDescription: "后端没有为 IC 注册配置组 surface",
      renderEditor: (ctx, current, editor, onFinish) => (
        FTICConfigurationGroupForm.render(ctx, current, editor, onFinish)
      ),
      onEditorOpened: ({flow}) => loadEditorCatalogs(context, state, flow, refresh),
    });
  }

  function configurationList(context, state, surface, refresh) {
    const groups = state.analysis.configuration_groups;
    if (!groups.length) {
      return FTUI.empty(
        context.t("暂无配置组"), context.t("使用“新增配置组”创建第一组 IC 配置"),
      );
    }
    return FTStrategyList.render({
      context,
      title: context.t("IC 配置组"),
      count: `${groups.length} ${context.t("个配置组")}`,
      selection: surface.selection === "single" ? "single" : "multi",
      batchSelection: false,
      showConfig: true,
      showConfigOpen: state.icConfigurationGroupShowConfigOpen === true,
      onToggleConfig: open => {
        state.icConfigurationGroupShowConfigOpen = open;
        if (open) hydrateSummaryProducts(context, state, refresh);
        refresh();
      },
      items: groups.map(group => ({
        key: group.config_group_id,
        label: group.name || group.config_group_id,
        editableName: true,
        onRename: name => {
          FTICConfigurationGroupModel.update(
            state, group.config_group_id, {name},
          );
          refresh();
          return true;
        },
        selected: state.selectedICConfigurationGroupIDs.includes(group.config_group_id),
        chips: summaryChips(context, state, group),
      })),
      onToggle: (item, checked) => {
        FTICConfigurationGroupModel.toggle(
          state, item.key, checked, surface.selection,
        );
        refresh();
      },
    });
  }

  function summaryChips(context, state, group) {
    const item = {
      factor_candidate_refs: [group.factor_ref],
      product_path_selection_id: group.product_scope_ref,
    };
    return FTTestSettingChips.render({
      context,
      manifest: state.manifest,
      values: {...(state.values || {}), ic_lags: [group.entry_delay_bars]},
      mountedTabs: ["factor", "product_path_selection", "delay"],
      sources: FTTestContentAdapters.chipSources(state, item),
      includeRun: false,
      includeStrategyChips: true,
      groupBy: "none",
      inline: true,
      onOverlay: descriptor => FTTestSettingChips.openDetail(
        context, state, descriptor,
      ),
    });
  }

  function loadEditorCatalogs(context, state, flow, refresh) {
    if (!["create", "edit"].includes(flow.kind)) return;
    const loaders = [
      window.FTTests?.ensureProductsForExecution?.(context, state, refresh),
      window.FTTests?.ensureFactorsForExecution?.(context, state, refresh),
    ];
    if (loaders.some(Boolean)) void Promise.all(loaders).then(refresh).catch(error => {
      state.icConfigurationGroupCatalogError = error.message || String(error);
      refresh();
    });
  }

  function editorCatalogsNeedLoad(state) {
    return ["factors", "products"].some(key => (
      state.lazy?.[key]?.status === "idle"
    ));
  }

  function hydrateSummaryProducts(context, state, refresh) {
    if (!needsProductLabels(state) || productHydrations.has(state)) return;
    const loader = window.FTTests?.ensureProductsForExecution;
    if (typeof loader !== "function") return;
    const promise = Promise.resolve(loader(context, state, refresh));
    productHydrations.set(state, promise);
    void promise.then(refresh).catch(error => {
      state.icConfigurationGroupCatalogError = error.message || String(error);
      refresh();
    }).finally(() => {
      if (productHydrations.get(state) === promise) productHydrations.delete(state);
    });
  }

  function needsProductLabels(state) {
    const catalog = Array.isArray(state.groups) ? state.groups : [];
    const index = state.productGroupIndex instanceof Map
      ? state.productGroupIndex
      : new Map(catalog.map(value => [productIdentity(value), value]));
    return (state.analysis?.configuration_groups || []).some(group => {
      const ref = String(group?.product_scope_ref || "");
      const value = index.get(ref);
      const label = value && typeof value === "object"
        ? value.title_zh || value.name || value.label || "" : "";
      return Boolean(ref && (!value || typeof value === "string"
        || value._savedPlaceholder === true || !label || label === ref));
    });
  }

  function productIdentity(value) {
    return String(window.FTTestProducts?.groupID?.(value)
      || value?.group_ref || value?.product_group_ref || value?.id || "");
  }

  const renderer = Object.freeze({initialize, render});
  FTConfigurationGroupSurface.register("ic", renderer);
  window.FTICConfigurationGroups = renderer;
})();
