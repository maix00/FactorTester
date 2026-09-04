// object-mode-actions.js — shared header actions for object-page authoring
// modes (view / edit / create).
//
// Every catalog object detail page mounts the same mode actions in the header
// toolbar through this component instead of appending buttons itself:
//   view   → a single "编辑/修改" entry (editHref) that swaps the current tab
//            to the edit mode of the same object — same pathname + ?mode=edit
//            keeps the detail tab identity, so this is an in-place swap;
//   edit   → 取消 (back to the same tab's read-only viewHref) + 保存;
//   create → 取消 (leave the placeholder tab) + 提交/保存.
// Pages only provide callbacks/labels; ordering, the same-tab navigation and
// the route-session guard (an async render must not append header actions
// after its route session ended) live here once.
(() => {
  function mount(context, options = {}) {
    if (!context.toolbar) return null;
    const mode = ["view", "edit", "create"].includes(options.mode)
      ? options.mode : "view";
    const actions = [];
    const button = (label, help, handler, variant) => {
      const item = FTUI.actionButton(context.t(label), handler, {variant});
      item.title = context.t(help || label);
      actions.push(item);
    };

    if (mode === "view") {
      if (options.onEdit && options.editHref && !context.testObjectViewOnly) {
        button(
          options.editLabel || "编辑",
          options.editHelp || "编辑",
          () => context.navigate(options.editHref),
        );
      }
    } else {
      if (options.cancel !== false && mode === "edit" && !context.testObjectTemporary) {
        // Same-tab authoring: cancel returns to the read-only view of the
        // same object inside this tab.
        button(
          options.cancelLabel || "取消编辑",
          options.cancelHelp || "取消编辑",
          () => context.navigate(options.viewHref || stripMode(options.editHref || "")),
          "secondary",
        );
      } else if (options.onCancel && (mode === "create" || context.testObjectTemporary)) {
        button(
          options.cancelLabel || "取消",
          options.cancelHelp || "取消",
          () => options.onCancel(),
          "secondary",
        );
      }
      if (options.onSave) {
        button(
          context.testObjectOverlay === true
            ? (options.overlaySaveLabel || "保存")
            : (options.saveLabel || (mode === "create" ? "提交" : "保存")),
          options.saveHelp || "保存",
          () => options.onSave(actions),
          "primary",
        );
      }
    }

    // The header/toolbar is shared across the tab rail.  An editor whose async
    // render completes after this route session ended must not append its
    // actions to the next page's header (stale buttons visible until refresh).
    if (context.isRouteCurrent?.() !== false) {
      for (const item of actions) context.toolbar.append(item);
    }
    return actions;
  }

  function stripMode(href) {
    return String(href || "").replace(/[?&]mode=(?:view|edit|create)/, "");
  }

  window.FTObjectModeActions = Object.freeze({mount, stripMode});
})();
