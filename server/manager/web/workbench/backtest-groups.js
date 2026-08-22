(() => {
  const adapters = Object.freeze({
    backtest_groups: Object.freeze({
      render: groupList,
      selected: state => FTBacktestGroupModel.selected(state),
      removeSelected: state => FTBacktestGroupModel.removeSelected(state),
      actions: Object.freeze({
        create: (_state, _selected) => ({mode: "base"}),
        derive: (_state, selected) => ({mode: "derived", parentID: selected[0]?.id}),
        edit: (_state, selected) => ({mode: "edit", groupID: selected[0]?.id}),
        rename: (_state, selected) => ({
          mode: "rename", strategyKind: "group", strategyID: selected[0]?.id,
        }),
        compose: (_state, selected) => ({
          mode: "ls", groupIDs: selected.map(group => group.id),
        }),
      }),
    }),
    backtest_long_short: Object.freeze({
      render: longShortList,
      selected: state => FTBacktestGroupModel.selectedLongShort(state),
      removeSelected: state => FTBacktestGroupModel.removeSelectedLongShort(state),
      actions: Object.freeze({
        create: (_state, _selected) => ({mode: "ls"}),
        edit: (_state, selected) => ({mode: "ls", strategyID: selected[0]?.id}),
        rename: (_state, selected) => ({
          mode: "rename", strategyKind: "long_short", strategyID: selected[0]?.id,
        }),
        swap: (state, selected) => {
          const id = selected[0]?.id;
          if (id) FTBacktestGroupModel.swapLongShort(state, id);
        },
      }),
    }),
    backtest_custom_strategies: Object.freeze({
      render: customStrategyList,
      selected: () => [],
      removeSelected: () => [],
      actions: Object.freeze({}),
    }),
  });

  function initialize(state) {
    if (state.kind === "backtest") FTBacktestGroupModel.initialize(state);
  }

  function render(context, state, refresh) {
    return FTConfigurationGroupSurface.render({
      context, state, refresh, adapters, initialize,
      title: "策略组设置",
      description: "下方策略与组合会冻结在同一次回测任务中",
      count: `${strategyCount(state)} ${context.t("项策略")}`,
      activeKey: "backtestGroupSurfaceKey",
      openKey: "backtestGroupsOpen",
      editorKey: "backtestGroupEditor",
      className: "backtest-groups",
      summaryClass: "backtest-group-summary",
      countClass: "backtest-group-count",
      summaryCopyClass: "backtest-group-summary-copy",
      shellClass: "backtest-group-shell",
      barClass: "backend-settings-tab-bar backtest-group-tab-bar",
      hostClass: "backend-settings-host backtest-group-host",
      panelClass: "backtest-group-panel",
      emptyTitle: "暂无策略组设置",
      emptyDescription: "后端没有为该测试注册策略组 surface",
      renderEditor: (ctx, current, editor, onFinish) => (
        FTBacktestGroupForm.render(ctx, current, editor, onFinish)
      ),
      onEditorOpened: ({flow}) => loadEditorCatalogs(context, state, flow, refresh),
    });
  }

  function loadEditorCatalogs(context, state, flow, refresh) {
    // The editor is intentionally lightweight on first paint, but its fallback
    // scope is the same visible catalog used by the factor/product tabs.
    if (!["create", "derive", "edit"].includes(flow.kind)) return;
    const loaders = [
      window.FTTests?.ensureProductsForExecution?.(context, state, refresh),
      window.FTTests?.ensureFactorsForExecution?.(context, state, refresh),
    ];
    if (loaders.some(Boolean)) void Promise.all(loaders).then(refresh).catch(error => {
      state.backtestGroupCatalogError = error.message || String(error);
      refresh();
    });
  }

  function groupList(context, state, surface, refresh) {
    const batches = FTBacktestGroupModel.groupBatches(state).map(batch => ({
      key: batch.key,
      label: batchLabel(context, batch),
      description: `${batch.items.length} ${context.t("个策略")}`,
      selected: batch.items.every(item => state.selectedBacktestGroupIDs.includes(item.group.id)),
      expanded: batchExpanded(state, batch.key),
      chips: null,
      items: batch.items.map(item => ({
        key: item.group.id,
        // The strategy name is the only user-facing label; its id remains the
        // stable machine identity used by selection and execution.
        label: item.group.name || FTBacktestGroupModel.groupLabel(item.group),
        depth: item.depth,
        editableName: true,
        onRename: name => {
          model().renameGroup(state, item.group.id, name);
          refresh();
          return true;
        },
        selected: state.selectedBacktestGroupIDs.includes(item.group.id),
        chips: groupOverrideChips(context, state, item.group),
        actions: rowActions(context, state, surface, item.group, refresh),
      })),
    }));
    return FTStrategyList.render({
      context, title: context.t("分组组合"),
      count: `${state.analysis.groups.length} ${context.t("个组")} / ${batches.length} ${context.t("个添加批次")}`,
      batches, selection: selectionType(surface) === "radio" ? "single" : "multi",
      showConfigOpen: state.backtestGroupConfigOpen === true,
      onToggleConfig: open => { state.backtestGroupConfigOpen = open; refresh(); },
      onToggleBatch: (key, open) => {
        state.backtestExpandedBatches = {...(state.backtestExpandedBatches || {}), [key]: open};
        refresh();
      },
      onToggle: (item, checked) => {
        FTBacktestGroupModel.toggle(state, item.key, checked, surface.selection); refresh();
      },
      onToggleBatchSelection: (batch, checked) => {
        for (const item of batch.items) FTBacktestGroupModel.toggle(
          state, item.group.id, checked, surface.selection,
        );
        refresh();
      },
    });
  }

  function longShortList(context, state, surface, refresh) {
    const values = state.analysis.ls_configs || [];
    if (!values.length) {
      return FTUI.empty(
        context.t("暂无 Long-Short 组合"),
        context.t("选择两个分组后使用“创建 Long-Short 组合”"),
      );
    }
    return FTStrategyList.render({
      context, title: context.t("Long-Short 组合"), count: `${values.length} ${context.t("项")}`,
      selection: selectionType(surface) === "radio" ? "single" : "multi",
      batchSelection: false,
      showConfig: true,
      showConfigOpen: state.backtestGroupConfigOpen === true,
      items: values.map(item => ({
        key: item.id, label: item.name || item.id, editableName: true,
        onRename: name => {
          model().renameLongShort(state, item.id, name);
          refresh();
          return true;
        },
        selected: state.selectedBacktestLongShortIDs.includes(item.id),
        chips: groupOverrideChips(context, state, item),
        actions: rowActions(context, state, surface, item, refresh),
      })),
      onToggle: (item, checked) => {
        FTBacktestGroupModel.toggleLongShort(state, item.key, checked, surface.selection);
        refresh();
      },
      onToggleConfig: open => { state.backtestGroupConfigOpen = open; refresh(); },
    });
  }

  function customStrategyList(context, state, surface, refresh) {
    if (!window.FTTestSourceUpload?.customStrategyPanel) {
      return FTUI.empty(
        context.t("自定义策略暂不可用"), context.t("策略输入组件尚未加载"),
      );
    }
    return FTTestSourceUpload.customStrategyPanel(context, state, refresh, {
      title: "自定义策略",
      description: "策略源码和配置随本次任务冻结保存",
      ...(surface.content_options || {}),
    });
  }

  function runFlow(context, state, surface, flow, selected, refresh) {
    return FTConfigurationGroupSurface.runFlow({
      context, state, surface, flow, selected,
      adapter: adapterFor(surface),
      editorKey: "backtestGroupEditor",
      refresh,
      onEditorOpened: () => loadEditorCatalogs(context, state, flow, refresh),
    });
  }

  function flows(state, surfaceKey) {
    return FTConfigurationGroupSurface.flows(state, surfaceKey);
  }

  function surfaces(state) {
    return FTConfigurationGroupSurface.surfaces(state);
  }

  function adapterFor(surface) {
    const name = String(surface?.content_adapter || "settings");
    const adapter = adapters[name];
    if (!adapter) throw new Error(`未实现的策略组内容适配器: ${name}`);
    return adapter;
  }

  function strategyCount(state) {
    return Number(state.analysis.groups?.length || 0)
      + Number(state.analysis.ls_configs?.length || 0)
      + Number(state.transientStrategySources?.length || 0);
  }

  function selectionType(surface) {
    return surface.selection === "single" ? "radio" : "checkbox";
  }

  function enabled(flow, count) {
    if (flow.min_selected != null && count < Number(flow.min_selected)) return false;
    if (flow.max_selected != null && count > Number(flow.max_selected)) return false;
    return true;
  }

  function batchExpanded(state, key) {
    return (state.backtestExpandedBatches || {})[key] !== false;
  }

  function batchLabel(context, batch) {
    const ordinal = batch.order
      ? `${context.t("添加批次")} ${batch.order}` : context.t("策略添加批次");
    return `${ordinal} · ${batch.key}`;
  }

  function groupOverrideChips(context, state, group) {
    if (!state.backtestGroupConfigOpen || !window.FTTestSettingChips?.render) return null;
    const overrides = FTBacktestGroupModel.registeredOverrides(group, state.manifest);
    const onlyKeys = Object.keys(overrides);
    const sources = window.FTTestContentAdapters?.chipSources?.(state, group) || {};
    const hasIdentity = Object.values(sources).some(value => (
      Array.isArray(value) ? value.length > 0 : value !== "" && value != null
    ));
    if (!onlyKeys.length && !hasIdentity) return null;
    const defaultTabs = Object.values(state.manifest?.defaults || {})
      .map(field => field?.tab_key).filter(Boolean);
    const mountedTabs = [...new Set([
      ...defaultTabs,
      ...(Array.isArray(group?.override_mounted_tabs) ? group.override_mounted_tabs : []),
    ])];
    return FTTestSettingChips.render({
      context,
      manifest: state.manifest,
      values: {...(state.values || {}), ...overrides},
      mountedTabs,
      onlyKeys,
      sources,
      includeUnregistered: true,
      includeRun: false,
      includeStrategyChips: true,
      groupBy: "none",
      onOverlay: descriptor => openChipDetail(context, state, descriptor),
    });
  }

  function openChipDetail(context, state, descriptor) {
    const action = descriptor?.detailOverlay;
    const target = action?.target;
    if (!action || !target || !window.FTTestObjectEditorOverlay?.open) return false;
    const value = target.value && typeof target.value === "object" ? target.value : null;
    const temporary = Boolean(value?.temporary
      || value?.source_kind === "transient"
      || value?.source_origin === "test_inline");
    void FTTestObjectEditorOverlay.open(context, {
      kind: action.kind,
      mode: action.mode || "view",
      ref: target.ref,
      initialValue: value,
      temporary,
      testState: state,
    }).catch(error => {
      context.showNotice?.(error.message || context.t("详情读取失败"), true);
    });
    return true;
  }

  function rowActions(context, state, surface, item, refresh) {
    return flows(state, surface.key)
      .filter(flow => flow.kind !== "rename"
        && Number(flow.min_selected) === 1 && Number(flow.max_selected) === 1)
      .map(flow => ({
        label: context.t(flow.label), title: context.t(flow.label),
        className: flow.button_class || (flow.kind === "delete" ? "danger" : ""),
        icon: iconFor(flow.kind),
        onClick: () => runFlow(context, state, surface, flow, [item], refresh),
      }));
  }

  function iconFor(kind) {
    return {
      create: "plus",
      derive: "arrow.triangle.branch",
      edit: "square.and.pencil",
      delete: "trash",
      compose: "square.stack.3d.up",
      swap: "arrow.left.arrow.right",
    }[kind] || "square.and.pencil";
  }

  const renderer = Object.freeze({adapterFor, flows, initialize, render, surfaces});
  FTConfigurationGroupSurface.register("backtest", renderer);
  window.FTBacktestGroups = renderer;
})();
