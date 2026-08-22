(() => {
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
    const editor = state.icConfigurationGroupEditor;
    if (editor?.groupID && !FTICConfigurationGroupModel.find(state, editor.groupID)) {
      state.icConfigurationGroupEditor = null;
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
      showConfig: false,
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
        chips: summaryChips(context, group),
      })),
      onToggle: (item, checked) => {
        FTICConfigurationGroupModel.toggle(
          state, item.key, checked, surface.selection,
        );
        refresh();
      },
    });
  }

  function summaryChips(context, group) {
    const root = document.createElement("span");
    root.className = "test-setting-chip-row";
    for (const text of [
      `${context.t("因子")}: ${shortRef(group.factor_ref)}`,
      `${context.t("产品组")}: ${shortRef(group.product_scope_ref)}`,
      `Delay: ${group.entry_delay_bars}`,
    ]) {
      const chip = document.createElement("span");
      chip.className = "test-setting-chip";
      chip.textContent = text;
      root.append(chip);
    }
    return root;
  }

  function shortRef(value) {
    const text = String(value || "");
    return text.length > 36 ? `${text.slice(0, 33)}…` : text;
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

  const renderer = Object.freeze({initialize, render});
  FTConfigurationGroupSurface.register("ic", renderer);
  window.FTICConfigurationGroups = renderer;
})();
