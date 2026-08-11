(() => {
  const implementedFlows = new Set([
    "add_group", "create_derived", "create_ls", "clone", "edit", "delete",
  ]);

  function initialize(state) {
    if (state.kind === "backtest") FTBacktestGroupModel.initialize(state);
  }

  function render(context, state, refresh) {
    initialize(state);
    const root = document.createElement("details");
    root.className = "backtest-groups";
    root.open = state.backtestGroupsOpen !== false;
    root.addEventListener("toggle", () => { state.backtestGroupsOpen = root.open; });
    const heading = document.createElement("summary");
    heading.className = "backtest-group-summary";
    const headingCopy = document.createElement("span");
    const title = document.createElement("b");
    title.textContent = context.t("分组组合设置");
    const note = document.createElement("small");
    note.textContent = context.t("多个分组和 Long-Short 组合会冻结在同一次回测任务中");
    headingCopy.append(title, note);
    const count = document.createElement("span");
    count.className = "backtest-group-count";
    count.textContent = `${state.analysis.groups.length} ${context.t("个分组")}`;
    heading.append(headingCopy, count);
    const shell = document.createElement("div");
    shell.className = "backtest-group-shell";
    const bar = document.createElement("div");
    bar.className = "backtest-group-tab-bar";
    const tabs = document.createElement("div");
    tabs.className = "backtest-group-tabs";
    const activeTab = state.backtestGroupTab || "groups";
    [
      ["groups", context.t("分组列表")],
      ["long-short", context.t("Long-Short 组合")],
    ].forEach(([key, label]) => {
      const button = context.button(label, () => {
        state.backtestGroupTab = key;
        refresh();
      });
      button.classList.toggle("active", activeTab === key);
      tabs.append(button);
    });
    const toolbar = document.createElement("div");
    toolbar.className = "backtest-group-toolbar";
    const selected = FTBacktestGroupModel.selected(state);
    for (const flow of flows(state)) {
      const button = context.button(context.t(flow.label), () => runFlow(
        context, state, flow.key, selected, refresh,
      ));
      button.disabled = !enabled(flow, selected.length);
      if (flow.button_class) button.classList.add(flow.button_class);
      toolbar.append(button);
    }
    bar.append(tabs, toolbar);
    const panel = document.createElement("div");
    panel.className = "backtest-group-panel";
    panel.append(activeTab === "long-short"
      ? longShortList(context, state, refresh)
      : groupList(context, state, refresh));
    shell.append(bar, panel);
    if (state.backtestGroupEditor) {
      shell.append(FTBacktestGroupForm.render(
        context, state, state.backtestGroupEditor,
        () => { state.backtestGroupEditor = null; refresh(); },
      ));
    }
    root.append(heading, shell);
    return root;
  }

  function groupList(context, state, refresh) {
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
      selection.type = "checkbox";
      selection.checked = state.selectedBacktestGroupIDs.includes(group.id);
      selection.addEventListener("change", () => {
        FTBacktestGroupModel.toggle(state, group.id, selection.checked);
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

  function longShortList(context, state, refresh) {
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
      const copy = document.createElement("span");
      const name = document.createElement("b"); name.textContent = item.name || item.shortAlias;
      const legs = document.createElement("small");
      legs.textContent = `${labelFor(state, item.longGroupId)} / ${labelFor(state, item.shortGroupId)}`;
      copy.append(name, legs);
      const remove = context.button(context.t("删除"), () => {
        FTBacktestGroupModel.removeLongShort(state, item.id); refresh();
      });
      row.append(copy, remove); list.append(row);
    }
    section.append(list);
    return section;
  }

  function runFlow(context, state, key, selected, refresh) {
    if (key === "delete") {
      if (!confirm(context.t("确定删除选中的分组及其派生内容"))) return;
      FTBacktestGroupModel.removeSelected(state); refresh(); return;
    }
    if (key === "add_group") state.backtestGroupEditor = {mode: "base"};
    if (key === "create_derived") {
      state.backtestGroupEditor = {mode: "derived", parentID: selected[0]?.id};
    }
    if (key === "clone") {
      state.backtestGroupEditor = {mode: "clone", parentID: selected[0]?.id};
    }
    if (key === "edit") {
      state.backtestGroupEditor = {mode: "edit", groupID: selected[0]?.id};
    }
    if (key === "create_ls") {
      state.backtestGroupEditor = {mode: "ls", groupIDs: selected.map(group => group.id)};
    }
    refresh();
  }

  function flows(state) {
    return (state.manifest.flows || []).filter(flow => (
      flow.surface === "groups" && implementedFlows.has(flow.key)
    )).sort((left, right) => Number(left.order || 0) - Number(right.order || 0));
  }

  function enabled(flow, count) {
    if (flow.min_selected != null && count < Number(flow.min_selected)) return false;
    if (flow.max_selected != null && count > Number(flow.max_selected)) return false;
    return true;
  }

  function labelFor(state, id) {
    return FTBacktestGroupModel.groupLabel(FTBacktestGroupModel.find(state, id)) || id;
  }

  window.FTBacktestGroups = Object.freeze({initialize, render});
})();
