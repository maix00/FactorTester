(() => {
  // Shared shell for manifest-declared configuration-group surfaces. Domain
  // modules own item meaning, models, forms and serializers; this module owns
  // only surface discovery, selection-gated flows, editor mounting and list UI.
  const renderers = new Map();

  function register(kind, renderer) {
    const key = String(kind || "").trim();
    if (!key || !renderer?.render) {
      throw new Error("configuration-group renderer requires a kind and render function");
    }
    if (renderers.has(key)) {
      throw new Error(`configuration-group renderer already registered: ${key}`);
    }
    renderers.set(key, renderer);
    return renderer;
  }

  function renderer(kind) {
    return renderers.get(String(kind || "").trim()) || null;
  }

  function render(options = {}) {
    const {
      context, state, refresh = () => {}, adapters = {}, initialize,
      title = "配置组设置", description = "", count = "",
      activeKey = "configurationGroupSurfaceKey",
      openKey = "configurationGroupsOpen",
      editorKey = "configurationGroupEditor",
      renderEditor, onEditorOpened,
    } = options;
    initialize?.(state);
    const available = surfaces(state);
    if (!available.length) {
      return FTUI.empty(
        context.t(options.emptyTitle || "暂无配置组设置"),
        context.t(options.emptyDescription || "后端没有为该测试注册配置组 surface"),
      );
    }
    const collapsed = state[activeKey] === null;
    const active = collapsed
      ? null
      : (available.find(item => item.key === state[activeKey]) || available[0]);
    if (active) state[activeKey] = active.key;
    const items = available.map(surface => ({
      key: surface.key,
      label: context.t(surface.label || surface.key),
      description: surface.help_text ? context.t(surface.help_text) : "",
      panelClass: options.panelClass || "configuration-group-panel",
      render: () => adapterFor(adapters, surface).render(
        context, state, surface, refresh,
      ),
    }));
    const list = FTTabListChip.create({
      className: options.className || "configuration-groups",
      summaryClass: options.summaryClass || "configuration-group-summary",
      countClass: options.countClass || "configuration-group-count",
      summaryCopyClass: options.summaryCopyClass || "configuration-group-summary-copy",
      shellClass: options.shellClass || "configuration-group-shell",
      barClass: options.barClass || "backend-settings-tab-bar configuration-group-tab-bar",
      hostClass: options.hostClass || "backend-settings-host configuration-group-host",
      title: context.t(title),
      description: context.t(description),
      count,
      open: state[openKey] !== false,
      onToggle: open => { state[openKey] = open; },
      items,
      activeKey: collapsed ? null : active?.key,
      actionsFor: surfaceKey => {
        const surface = available.find(item => item.key === surfaceKey)
          || active || available[0];
        if (!surface) return [];
        const adapter = adapterFor(adapters, surface);
        const selected = adapter.selected(state);
        return flows(state, surface.key).filter(flow => flow.kind !== "rename").map(flow => ({
          label: context.t(flow.label),
          buttonClass: flow.button_class,
          disabled: !enabled(flow, selected.length),
          onClick: () => runFlow({
            context, state, surface, flow, selected, adapter,
            editorKey, refresh, onEditorOpened,
          }),
        }));
      },
      onActivate: key => {
        state[activeKey] = key;
        refresh();
      },
    });
    if (state[editorKey] && renderEditor) {
      const form = renderEditor(
        context, state, state[editorKey],
        () => { state[editorKey] = null; refresh(); },
      );
      if (form) list.shell.append(form);
    }
    return list.root;
  }

  function runFlow(options) {
    const {
      context, state, surface, flow, selected, adapter,
      editorKey, refresh, onEditorOpened,
    } = options;
    if (flow.kind === "delete") {
      if (!confirm(context.t(`确定删除选中的${surface.item_label || "项目"}`))) return;
      const removed = adapter.removeSelected(state) || [];
      const editingID = state[editorKey]?.groupID;
      if (editingID && removed.some(item => (
        item?.config_group_id === editingID || item?.group_id === editingID
      ))) state[editorKey] = null;
      refresh();
      return;
    }
    const action = adapter.actions?.[flow.kind];
    if (!action) throw new Error(`内容适配器不支持操作: ${flow.kind}`);
    const result = action(state, selected, flow);
    if (flow.kind === "swap" || options.sideEffectOnly === true) {
      refresh();
      return;
    }
    if (result !== undefined && result !== null) state[editorKey] = result;
    refresh();
    if (state[editorKey]) onEditorOpened?.({state, surface, flow, selected, refresh});
  }

  function surfaces(state) {
    return (state?.manifest?.surfaces || []).filter(surface => (
      surface.kind === "list" && surface.mount === "group-settings"
    )).sort((left, right) => Number(left.order || 0) - Number(right.order || 0));
  }

  function flows(state, surfaceKey) {
    return (state?.manifest?.flows || []).filter(flow => (
      flow.surface === surfaceKey
    )).sort((left, right) => Number(left.order || 0) - Number(right.order || 0));
  }

  function adapterFor(adapters, surface) {
    const name = String(surface?.content_adapter || "settings");
    const adapter = adapters[name];
    if (!adapter) throw new Error(`未实现的配置组内容适配器: ${name}`);
    return adapter;
  }

  function enabled(flow, count) {
    if (flow.min_selected != null && count < Number(flow.min_selected)) return false;
    if (flow.max_selected != null && count > Number(flow.max_selected)) return false;
    return true;
  }

  window.FTConfigurationGroupSurface = Object.freeze({
    enabled, flows, register, render, renderer, runFlow, surfaces,
  });
})();
