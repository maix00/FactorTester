// object-mode-actions.js — shared header actions for object-page authoring
// modes (view / edit / create).
//
// Every catalog object detail page mounts the same mode actions in the header
// toolbar through this component instead of appending buttons itself.  The
// actions are icon buttons (pencil → edit, checkmark → save/submit, xmark →
// cancel) so no action text needs translation or layout space; the localized
// label is carried as the tooltip/aria-label.
//   view   → 编辑 (editHref) that swaps the current tab to the edit mode of
//            the same object — same pathname + ?mode=edit keeps the detail
//            tab identity, so this is an in-place swap;
//   edit   → 取消 (back to the same tab's read-only viewHref) + 保存;
//   create → 取消 (leave the placeholder tab) + 提交/保存.
// Pages only provide callbacks/labels; ordering, the same-tab navigation and
// the route-session guard (an async render must not append header actions
// after its route session ended) live here once.
(() => {
  // Same icon system as the catalog tables (factor list rows already use
  // square.and.pencil for 编辑 / plus for 新增 / trash for 删除): edit keeps
  // square.and.pencil, save/submit uses checkmark.circle, cancel uses xmark.
  const ICONS = {edit: "square.and.pencil", save: "checkmark.circle", cancel: "xmark"};

  function mount(context, options = {}) {
    if (!context.toolbar) return null;
    const mode = ["view", "edit", "create"].includes(options.mode)
      ? options.mode : "view";
    const actions = [];
    const button = (symbol, label, help, handler, className) => {
      const item = window.FTUI?.iconButton?.(
        context, symbol, label, handler, {className: className || ""},
      );
      if (!item) return;
      if (help && item.title) item.title = context.t(help);
      actions.push(item);
    };

    if (mode === "view") {
      if (options.onEdit && !context.testObjectViewOnly) {
        // The edit URL keeps the current tab's pathname (detail tab ids derive
        // from the pathname), so the swap happens inside the same tab.  The
        // page may override it, but deriving from the location is what
        // guarantees an in-place mode change for frozen/alias view URLs.
        const href = options.editHref
          || window.FTPageMode?.hrefForMode?.("edit") || "";
        if (href) {
          button(
            ICONS.edit,
            options.editLabel || "编辑",
            options.editHelp,
            () => context.navigate(href),
          );
        }
      }
    } else {
      const editingInline = mode === "edit" && context.testObjectTemporary;
      if (options.cancel !== false) {
        const cancelViaHref = mode === "edit" && !editingInline
          && Boolean(options.viewHref || options.editHref);
        if (cancelViaHref) {
          // Same-tab authoring: cancel returns to the read-only view of the
          // same object inside this tab.
          button(
            ICONS.cancel,
            options.cancelLabel || "取消编辑",
            options.cancelHelp,
            () => context.navigate(
              options.viewHref || stripMode(options.editHref || ""),
            ),
            "secondary",
          );
        } else if (options.onCancel) {
          button(
            ICONS.cancel,
            options.cancelLabel || (mode === "edit" ? "取消编辑" : "取消"),
            options.cancelHelp,
            () => options.onCancel(),
            "secondary",
          );
        }
      }
      if (options.onSave) {
        button(
          ICONS.save,
          context.testObjectOverlay === true
            ? (options.overlaySaveLabel || "保存")
            : (options.saveLabel || (mode === "create" ? "提交" : "保存")),
          options.saveHelp,
          () => options.onSave(actions),
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

  window.FTObjectModeActions = Object.freeze({mount, stripMode, ICONS});
})();
