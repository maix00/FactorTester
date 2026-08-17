(() => {
  function render(context, helpers, options = {}) {
    const source = helpers.sourceOf();
    const category = options.category || null;
    const mode = options.mode || (category ? "edit" : "create");
    const sourceCategory = options.sourceCategory === true;
    const root = document.createElement("section");
    root.className = "product-category-editor-page detail-stack";
    const header = document.createElement("div");
    header.className = "product-category-editor-header";
    const back = FTUI.actionButton(context.t("返回产品分类"), () => {
      context.navigate(helpers.pathFor("/products/categories", source));
    }, {variant: "secondary"});
    const title = document.createElement("h2");
    title.textContent = mode === "edit"
      ? context.t("编辑产品分类") : context.t("新增分类");
    header.append(back, title);
    root.append(header);

    const form = document.createElement("form");
    form.className = "product-category-editor-form";
    const identity = document.createElement("div");
    identity.className = "product-category-identity-fields";
    const idField = document.createElement("label");
    idField.className = "test-object-field";
    const idLabel = document.createElement("b");
    idLabel.textContent = context.t("分类 ID");
    const id = document.createElement("input");
    id.required = Boolean(category);
    id.value = category?.id || "";
    id.placeholder = context.t("由服务器生成");
    id.readOnly = true;
    idField.append(idLabel, id);
    const nameField = document.createElement("label");
    nameField.className = "test-object-field";
    const nameLabel = document.createElement("b");
    nameLabel.textContent = context.t("分类名称");
    const name = document.createElement("input");
    name.required = true;
    name.value = category?.title_zh || category?.alias || "";
    name.placeholder = context.t("例如：日夜盘、行业");
    nameField.append(nameLabel, name);
    if (category) identity.append(idField);
    identity.append(nameField);
    const note = document.createElement("p");
    note.textContent = sourceCategory
      ? context.t("数据源产品分类的路径由数据源提供，超级管理员只能修改展示标题")
      : context.t(
        "标准产品路径不包含分类；保存时会自动转换可识别的分类路径",
      );

    const state = {activeRow: null, selectedPaths: [], pickerReady: false};
    const rows = document.createElement("div");
    rows.className = "product-category-item-rows";
    const editor = document.createElement("section");
    editor.className = "product-category-create-editor";
    const editorTitle = document.createElement("h3");
    editorTitle.textContent = context.t("分类条目");
    const add = FTUI.actionButton(context.t("新增条目"), () => addRow(), {
      variant: "secondary",
    });
    if (sourceCategory) {
      editor.append(editorTitle, Object.assign(document.createElement("p"), {
        textContent: context.t("数据源分类条目不可在此编辑"),
      }));
    } else {
      editor.append(editorTitle, rows, add);
    }

    const picker = document.createElement("aside");
    picker.className = "product-category-path-picker";
    const pickerHeading = document.createElement("h3");
    pickerHeading.textContent = context.t("选择产品路径");
    const pickerNote = document.createElement("p");
    pickerNote.textContent = context.t(
      "选中某个条目后，右侧产品树会同步显示该条目已选择的路径",
    );
    const pickerTarget = document.createElement("small");
    pickerTarget.className = "product-category-picker-target";
    const pickerSummary = document.createElement("small");
    pickerSummary.className = "product-category-picker-summary";
    const pickerStatus = document.createElement("small");
    pickerStatus.className = "product-category-form-error";
    const pickerTree = document.createElement("div");
    pickerTree.className = "product-category-picker-tree";
    picker.append(pickerHeading, pickerNote, pickerTarget, pickerSummary,
      pickerStatus, pickerTree);
    const layout = document.createElement("div");
    layout.className = "product-category-create-layout";
    layout.append(editor, picker);

    const status = document.createElement("small");
    status.className = "product-category-form-error";
    const actions = document.createElement("div");
    actions.className = "dialog-actions";
    const save = FTUI.actionButton(context.t("保存"), null, {variant: "primary"});
    save.type = "submit";
    actions.append(save);
    form.append(identity, note, layout, status, actions);
    root.append(form);

    const readPaths = row => [...row.querySelectorAll("textarea")]
      .flatMap(field => field.value.split(/\r?\n/))
      .map(value => value.trim()).filter(Boolean);
    const writePaths = (row, values) => {
      if (row?.dataset.generated === "true") return;
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
      if (row.dataset.generated === "true") return;
      if (rows.children.length <= 1) return;
      const next = row.nextElementSibling || row.previousElementSibling;
      row.remove();
      if (row === state.activeRow) activateRow(next);
    };
    const addRow = initial => {
      const row = itemRow(context, {
        activate: activateRow, remove: removeRow, sync: syncRow,
      }, initial);
      rows.append(row);
      if (!state.activeRow) activateRow(row);
    };

    form.addEventListener("submit", async event => {
      event.preventDefault();
      const items = [...rows.children].map(row => ({
        label: row.querySelector("input")?.value || "",
        paths: readPaths(row),
        ...(row.dataset.generated === "true" ? {label_generated: true} : {}),
      }));
      save.disabled = true;
      status.textContent = "";
      const endpoint = category
        ? `/api/catalog/categories/${encodeURIComponent(category.id)}`
        : "/api/catalog/categories";
      try {
        const value = await context.api(endpoint, {
          method: category ? "PUT" : "POST",
          body: JSON.stringify({
            name: name.value,
            ...(sourceCategory ? {} : {items}),
          }),
        });
        const saved = value.category || category || {};
        if (category) {
          context.navigate(helpers.pathFor(
            `/products/categories/${encodeURIComponent(saved.id)}`, source,
          ));
        } else {
          context.closeTab?.(context.tabID);
          context.navigate(helpers.pathFor("/products/categories", source));
        }
      } catch (error) {
        status.textContent = error.message || context.t("产品分类保存失败");
      } finally { save.disabled = false; }
    });
    const initialItems = Array.isArray(category?.items) ? category.items : [];
    if (initialItems.length) initialItems.forEach(addRow);
    else addRow();
    loadPicker(context, helpers, pickerTree, pickerStatus, state, {
      updatePicker, writePaths, source, sourceCategory,
    });
    context.content.replaceChildren(root);
    name.focus();
    return root;
  }

  function itemRow(context, handlers, initial = {}) {
    const row = document.createElement("div");
    row.className = "product-category-item-row";
    const generated = initial.label_generated === true
      || initial.label === "Others";
    if (generated) {
      row.dataset.generated = "true";
      row.classList.add("product-category-generated-item");
    }
    const label = document.createElement("input");
    label.placeholder = context.t("条目标签"); label.required = true;
    label.value = initial.label || "";
    const pathEditor = document.createElement("div");
    pathEditor.className = "product-category-path-editor";
    const paths = document.createElement("textarea");
    paths.placeholder = context.t("每行一个产品路径"); paths.required = true;
    paths.rows = 3; paths.value = (initial.paths || []).join("\n");
    const choose = FTUI.actionButton(context.t("从产品树选择"), () => {
      handlers.activate(row);
    }, {variant: "secondary"});
    choose.type = "button"; pathEditor.append(paths, choose);
    const controls = document.createElement("div");
    controls.className = "product-category-item-controls";
    const remove = FTUI.actionButton(context.t("移除"), () => handlers.remove(row), {
      variant: "secondary",
    });
    remove.type = "button"; controls.append(remove);
    if (generated) {
      label.readOnly = true;
      paths.readOnly = true;
      choose.disabled = true;
      remove.disabled = true;
      row.title = context.t("Others 标签由系统自动生成，不能修改");
    }
    label.addEventListener("focus", () => handlers.activate(row));
    paths.addEventListener("focus", () => handlers.activate(row));
    paths.addEventListener("input", () => handlers.sync(row));
    row.append(label, pathEditor, controls);
    return row;
  }

  async function loadPicker(context, helpers, mount, status, state, actions) {
    mount.replaceChildren(FTUI.loading(context.t("正在读取产品树…")));
    try {
      const value = await helpers.loadProductTree(context, actions.source);
      await FTProductTree.render(context, mount, value.tree, {
        showCategoryFilter: false,
        selectable: actions.sourceCategory !== true,
        leafOnly: true,
        selectedPaths: state.selectedPaths, source: value.source,
        contractTreePath: value.contractTreePath,
        onSelectionChange: selected => {
          state.selectedPaths = FTProductTree.minimalPaths(selected);
          actions.writePaths(state.activeRow, state.selectedPaths);
          actions.updatePicker();
        },
      });
      state.pickerReady = true; actions.updatePicker();
    } catch (error) {
      status.textContent = error.message || context.t("产品树读取失败");
      mount.replaceChildren();
    }
  }

  window.FTProductCategoryCreate = Object.freeze({open: render, render});
})();
