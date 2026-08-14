(() => {
  const adapters = Object.freeze({
    backtest_groups: Object.freeze({
      render: groupList,
      selected: state => FTBacktestGroupModel.selected(state),
      removeSelected: state => FTBacktestGroupModel.removeSelected(state),
      actions: Object.freeze({
        create: (_state, _selected) => ({mode: "base"}),
        derive: (_state, selected) => ({mode: "derived", parentID: selected[0]?.id}),
        clone: (_state, selected) => ({mode: "clone", parentID: selected[0]?.id}),
        edit: (_state, selected) => ({mode: "edit", groupID: selected[0]?.id}),
        compose: (_state, selected) => ({
          mode: "ls", groupIDs: selected.map(group => group.id),
        }),
      }),
    }),
    backtest_long_short: Object.freeze({
      render: longShortList,
      selected: state => FTBacktestGroupModel.selectedLongShort(state),
      removeSelected: state => FTBacktestGroupModel.removeSelectedLongShort(state),
      actions: Object.freeze({}),
    }),
  });

  function initialize(state) {
    if (state.kind === "backtest") FTBacktestGroupModel.initialize(state);
  }

  function render(context, state, refresh) {
    initialize(state);
    const available = surfaces(state);
    if (!available.length) {
      return FTUI.empty(
        context.t("暂无策略组设置"), context.t("后端没有为该测试注册策略组 surface"),
      );
    }
    const active = available.find(item => item.key === state.backtestGroupSurfaceKey)
      || available[0];
    state.backtestGroupSurfaceKey = active.key;
    const items = available.map(surface => ({
      key: surface.key,
      label: context.t(surface.label || surface.key),
      description: surface.help_text ? context.t(surface.help_text) : "",
      panelClass: "backtest-group-panel",
      render: () => adapterFor(surface).render(context, state, surface, refresh),
    }));
    const list = FTTabListChip.create({
      className: "backtest-groups",
      summaryClass: "backtest-group-summary",
      countClass: "backtest-group-count",
      summaryCopyClass: "backtest-group-summary-copy",
      shellClass: "backtest-group-shell",
      barClass: "backend-settings-tab-bar backtest-group-tab-bar",
      hostClass: "backend-settings-host backtest-group-host",
      title: context.t("策略组设置"),
      description: context.t("下方策略与组合会冻结在同一次回测任务中"),
      count: `${strategyCount(state)} ${context.t("项策略")}`,
      open: state.backtestGroupsOpen !== false,
      onToggle: open => { state.backtestGroupsOpen = open; },
      items,
      activeKey: active.key,
      actionsFor: surfaceKey => {
        const surface = available.find(item => item.key === surfaceKey) || active;
        const selected = adapterFor(surface).selected(state);
        return flows(state, surface.key).map(flow => ({
          label: context.t(flow.label),
          buttonClass: flow.button_class,
          disabled: !enabled(flow, selected.length),
          onClick: () => runFlow(context, state, surface, flow, selected, refresh),
        }));
      },
      onActivate: key => {
        state.backtestGroupSurfaceKey = key;
        refresh();
      },
    });
    if (state.backtestGroupEditor) {
      const form = FTBacktestGroupForm.render(
        context, state, state.backtestGroupEditor,
        () => { state.backtestGroupEditor = null; refresh(); },
      );
      list.shell.append(form);
    }
    return list.root;
  }

  function groupList(context, state, surface, refresh) {
    const values = FTBacktestGroupModel.rootsAndChildren(state);
    if (!values.length) {
      return FTUI.empty(context.t("暂无分组"), context.t("先建立一个分组，或在运行时使用当前选择生成默认第一组"));
    }
    const table = FTUI.table([
      "", context.t("分组"), context.t("类型"), context.t("因子"),
      context.t("分位"), context.t("产品组或筛选"), context.t("逐组覆盖"),
    ]);
    for (const {group, depth} of values) {
      const selection = document.createElement("input");
      selection.type = selectionType(surface);
      selection.checked = state.selectedBacktestGroupIDs.includes(group.id);
      selection.addEventListener("change", () => {
        FTBacktestGroupModel.toggle(
          state, group.id, selection.checked, surface.selection,
        );
        refresh();
      });
      const title = document.createElement("span");
      title.className = "backtest-group-name";
      title.style.setProperty("--group-depth", depth);
      const alias = document.createElement("b"); alias.textContent = FTBacktestGroupModel.groupLabel(group);
      const name = document.createElement("small"); name.textContent = group.name || group.id;
      title.append(alias, name);
      const mask = Object.entries(group.productMask || {}).filter(([, enabled]) => enabled)
        .map(([product]) => product);
      const product = group.parentId
        ? (mask.length ? mask.join("、") : context.t("继承父组"))
        : FTTestProducts.groupLabel(group.product_path_selection || {})
          || group.product_path_selection_id;
      const overrides = Object.keys(
        FTBacktestGroupModel.registeredOverrides(group, state.manifest),
      ).length;
      FTUI.appendRow(table.body, [
        selection, title, group.parentId ? context.t("派生组") : context.t("基础组"),
        group.factorAlias || context.t("继承父组"),
        group.parentId ? context.t("继承父组") : `${group.groupIndex}/${group.splitCount}`,
        product, String(overrides),
      ]);
    }
    return table.shell;
  }

  function longShortList(context, state, surface, refresh) {
    const values = state.analysis.ls_configs || [];
    if (!values.length) {
      return FTUI.empty(
        context.t("暂无 Long-Short 组合"),
        context.t("选择两个分组后使用“创建 Long-Short 组合”"),
      );
    }
    const section = document.createElement("div");
    section.className = "backtest-long-short";
    const list = document.createElement("div");
    for (const item of values) {
      const row = document.createElement("div");
      const selection = document.createElement("input");
      selection.type = selectionType(surface);
      selection.checked = state.selectedBacktestLongShortIDs.includes(item.id);
      selection.addEventListener("change", () => {
        FTBacktestGroupModel.toggleLongShort(
          state, item.id, selection.checked, surface.selection,
        );
        refresh();
      });
      const copy = document.createElement("span");
      const name = document.createElement("b"); name.textContent = item.name || item.shortAlias;
      const legs = document.createElement("small");
      legs.textContent = `${labelFor(state, item.longGroupId)} / ${labelFor(state, item.shortGroupId)}`;
      copy.append(name, legs);
      row.append(selection, copy); list.append(row);
    }
    section.append(list);
    return section;
  }

  function runFlow(context, state, surface, flow, selected, refresh) {
    const adapter = adapterFor(surface);
    if (flow.kind === "delete") {
      if (!confirm(context.t(`确定删除选中的${surface.item_label || "项目"}`))) return;
      adapter.removeSelected(state);
      refresh(); return;
    }
    const action = adapter.actions[flow.kind];
    if (!action) throw new Error(`内容适配器不支持操作: ${flow.kind}`);
    state.backtestGroupEditor = action(state, selected, flow);
    refresh();
  }

  function flows(state, surfaceKey) {
    return (state.manifest.flows || []).filter(flow => (
      flow.surface === surfaceKey
    )).sort((left, right) => Number(left.order || 0) - Number(right.order || 0));
  }

  function surfaces(state) {
    return (state.manifest.surfaces || []).filter(surface => (
      surface.kind === "list" && surface.mount === "group-settings"
    )).sort((left, right) => Number(left.order || 0) - Number(right.order || 0));
  }

  function adapterFor(surface) {
    const name = String(surface?.content_adapter || "settings");
    const adapter = adapters[name];
    if (!adapter) throw new Error(`未实现的策略组内容适配器: ${name}`);
    return adapter;
  }

  function strategyCount(state) {
    return Number(state.analysis.groups?.length || 0)
      + Number(state.analysis.ls_configs?.length || 0);
  }

  function selectionType(surface) {
    return surface.selection === "single" ? "radio" : "checkbox";
  }

  function enabled(flow, count) {
    if (flow.min_selected != null && count < Number(flow.min_selected)) return false;
    if (flow.max_selected != null && count > Number(flow.max_selected)) return false;
    return true;
  }

  function labelFor(state, id) {
    return FTBacktestGroupModel.groupLabel(FTBacktestGroupModel.find(state, id)) || id;
  }

  window.FTBacktestGroups = Object.freeze({adapterFor, flows, initialize, render, surfaces});
})();
