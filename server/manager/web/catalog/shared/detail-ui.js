(() => {
  function action(context, label, handler, variant = "secondary") {
    return FTUI.actionButton(context.t(label), handler, {variant});
  }

  function header(context, options = {}) {
    const {
      title, editing, creating, canEdit, onBack, onCancel, onSave,
      onEdit, onDelete, extra, backLabel = "返回",
    } = options;
    const root = document.createElement("div");
    root.className = "catalog-detail-header";
    root.append(action(context, backLabel, onBack));
    root.append(Object.assign(document.createElement("h2"), {
      textContent: title || "",
    }));
    let save = null;
    if (editing) {
      root.append(action(context, "取消", onCancel));
      save = action(context, "保存", onSave, "primary");
      save.type = "submit";
      root.append(save);
    } else if (canEdit) {
      root.append(action(context, "编辑", onEdit, "primary"));
      if (!creating && onDelete) root.append(action(context, "删除", onDelete));
    }
    if (extra) root.append(extra);
    return {root, save};
  }

  function field(context, labelText, value, options = {}) {
    const label = document.createElement("label");
    label.className = options.className || "test-object-field";
    label.append(Object.assign(document.createElement("b"), {
      textContent: context.t(labelText),
    }));
    const input = document.createElement(options.multiline ? "textarea" : "input");
    input.value = value || "";
    input.readOnly = options.readOnly === true;
    input.required = options.required === true;
    if (options.placeholder) input.placeholder = context.t(options.placeholder);
    if (options.multiline) input.rows = options.rows || 3;
    label.append(input);
    return {root: label, input};
  }

  function infoTable(context, rows, className = "catalog-detail-info") {
    const section = document.createElement("section");
    section.className = className;
    section.append(FTUI.table(
      [context.t("字段"), context.t("值")], rows,
    ).shell);
    return section;
  }

  function clearMount(mount) {
    if (!mount) return;
    mount.replaceChildren();
    delete mount.dataset.loaded;
  }

  window.FTCatalogDetailUI = Object.freeze({
    action, clearMount, field, header, infoTable,
  });
})();
