(() => {
  function open(context, helpers) {
    const dialog = document.createElement("dialog");
    dialog.className = "product-category-create-dialog";
    const form = document.createElement("form");
    form.className = "dialog-card wide product-category-create-card";
    const title = document.createElement("h2");
    title.textContent = context.t("新增分类");
    const nameField = document.createElement("label");
    nameField.className = "test-object-field";
    const nameLabel = document.createElement("b");
    nameLabel.textContent = context.t("分类名称");
    const name = document.createElement("input");
    name.required = true;
    name.placeholder = context.t("例如：日夜盘、行业");
    nameField.append(nameLabel, name);
    const note = document.createElement("p");
    note.textContent = context.t(
      "标准产品路径不包含分类；保存时会自动转换可识别的分类路径",
    );

    const state = {
      activeRow: null,
      selectedPaths: [],
      pickerReady: false,
    };
    const rows = document.createElement("div");
    rows.className = "product-category-item-rows";
    const editor = document.createElement("section");
    editor.className = "product-category-create-editor";
    const editorTitle = document.createElement("h3");
    editorTitle.textContent = context.t("分类条目");
    const add = FTUI.actionButton(context.t("新增条目"), () => addRow(), {
      variant: "secondary",
    });
    editor.append(editorTitle, rows, add);

    const picker = document.createElement("aside");
    picker.className = "product-category-path-picker";
    const pickerHeading = document.createElement("h3");
    pickerHeading.textContent = context.t("选择产品路径");
    const pickerNote = document.createElement("p");
    pickerNote.textContent = context.t(
      "可选择各层级路径；展开到本级产品列表后，也可选择其中的每一行",
    );
    const pickerTarget = document.createElement("small");
    pickerTarget.className = "product-category-picker-target";
    const pickerSummary = document.createElement("small");
    pickerSummary.className = "product-category-picker-summary";
    const pickerStatus = document.createElement("small");
    pickerStatus.className = "product-category-form-error";
    const pickerTree = document.createElement("div");
    pickerTree.className = "product-category-picker-tree";
    picker.append(
      pickerHeading, pickerNote, pickerTarget, pickerSummary,
      pickerStatus, pickerTree,
    );
    const layout = document.createElement("div");
    layout.className = "product-category-create-layout";
    layout.append(editor, picker);

    const status = document.createElement("small");
    status.className = "product-category-form-error";
    const actions = document.createElement("div");
    actions.className = "dialog-actions";
    const cancel = FTUI.actionButton(context.t("取消"), () => dialog.close(), {
      variant: "secondary",
    });
    const save = FTUI.actionButton(context.t("保存"), null, {
      variant: "primary",
    });
    save.type = "submit";
    actions.append(cancel, save);
    form.append(title, nameField, note, layout, status, actions);

    const readPaths = row => [...row.querySelectorAll("textarea")]
      .flatMap(field => field.value.split(/\r?\n/))
      .map(value => value.trim()).filter(Boolean);
    const writePaths = (row, values) => {
      const field = row?.querySelector("textarea");
      if (field) field.value = FTProductTree.minimalPaths(values).join("\n");
    };
    const updatePicker = () => {
      const label = state.activeRow?.querySelector("input")?.value.trim();
      pickerTarget.textContent = label
        ? `${context.t("当前条目")}：${label}`
        : context.t("请先选择一个条目");
      pickerSummary.textContent = `${context.t("已选择")} ${state.selectedPaths.length} ${context.t("条产品路径")}`;
      if (state.pickerReady) {
        FTProductTree.syncSelectionControls(pickerTree, state.selectedPaths);
      }
    };
    const activateRow = row => {
      state.activeRow = row;
      state.selectedPaths = FTProductTree.minimalPaths(readPaths(row));
      rows.querySelectorAll(".active").forEach(item => item.classList.remove("active"));
      row.classList.add("active");
      updatePicker();
    };
    const syncRow = row => {
      if (row !== state.activeRow) return;
      state.selectedPaths = FTProductTree.minimalPaths(readPaths(row));
      updatePicker();
    };
    const removeRow = row => {
      if (rows.children.length <= 1) return;
      const next = row.nextElementSibling || row.previousElementSibling;
      row.remove();
      if (row === state.activeRow) activateRow(next);
    };
    const addRow = () => {
      const row = itemRow(context, {
        activate: activateRow,
        remove: removeRow,
        sync: syncRow,
      });
      rows.append(row);
      if (!state.activeRow) activateRow(row);
    };

    form.addEventListener("submit", async event => {
      event.preventDefault();
      const items = [...rows.children].map(row => ({
        label: row.querySelector("input")?.value || "",
        paths: readPaths(row),
      }));
      save.disabled = true;
      status.textContent = "";
      try {
        await context.api("/api/catalog/categories", {
          method: "POST", body: JSON.stringify({name: name.value, items}),
        });
        dialog.close();
        window.FTProductCategories.list(context, helpers);
      } catch (error) {
        status.textContent = error.message || context.t("产品分类保存失败");
      } finally { save.disabled = false; }
    });
    dialog.addEventListener("close", () => dialog.remove(), {once: true});
    dialog.append(form);
    document.body.append(dialog);
    dialog.showModal();
    name.focus();
    addRow();
    loadPicker(context, helpers, pickerTree, pickerStatus, state, {
      updatePicker,
      writePaths,
    });
    return dialog;
  }

  function itemRow(context, handlers) {
    const row = document.createElement("div");
    row.className = "product-category-item-row";
    const label = document.createElement("input");
    label.placeholder = context.t("条目标签");
    label.required = true;
    const pathEditor = document.createElement("div");
    pathEditor.className = "product-category-path-editor";
    const paths = document.createElement("textarea");
    paths.placeholder = context.t("每行一个产品路径");
    paths.required = true;
    paths.rows = 3;
    const choose = FTUI.actionButton(context.t("从产品树选择"), () => {
      handlers.activate(row);
    }, {variant: "secondary"});
    choose.type = "button";
    pathEditor.append(paths, choose);
    const controls = document.createElement("div");
    controls.className = "product-category-item-controls";
    const remove = FTUI.actionButton(context.t("移除"), () => {
      handlers.remove(row);
    }, {variant: "secondary"});
    remove.type = "button";
    controls.append(remove);
    label.addEventListener("focus", () => handlers.activate(row));
    paths.addEventListener("focus", () => handlers.activate(row));
    paths.addEventListener("input", () => handlers.sync(row));
    row.append(label, pathEditor, controls);
    return row;
  }

  async function loadPicker(context, helpers, mount, status, state, actions) {
    mount.replaceChildren(FTUI.loading(context.t("正在读取产品树…")));
    try {
      const value = await helpers.loadProductTree(context, "server");
      const options = {
        showCategoryFilter: false,
        selectable: true,
        leafOnly: true,
        selectedPaths: state.selectedPaths,
        source: value.source,
        contractTreePath: value.contractTreePath,
        onSelectionChange: selected => {
          state.selectedPaths = FTProductTree.minimalPaths(selected);
          actions.writePaths(state.activeRow, state.selectedPaths);
          actions.updatePicker();
        },
      };
      await FTProductTree.render(context, mount, value.tree, options);
      state.pickerReady = true;
      actions.updatePicker();
    } catch (error) {
      status.textContent = error.message || context.t("产品树读取失败");
      mount.replaceChildren();
    }
  }

  window.FTProductCategoryCreate = Object.freeze({open});
})();
