(() => {
  function render(context, category, treeState, options) {
    const section = document.createElement("section");
    section.className = "product-category-path-definitions product-category-label-editor";
    section.append(Object.assign(document.createElement("h2"), {
      textContent: context.t("Label 与产品路径"),
    }));
    const rows = document.createElement("div");
    rows.className = "product-category-item-rows";
    const rowStates = new Set();
    const items = options.creating && !options.labels.length ? [{}] : options.labels;
    const disposeRow = rowState => {
      rowState.renderToken += 1;
      rowState.loading = false;
      rowState.mounted = false;
      rowState.treeMount?.replaceChildren();
      rowState.treeMount = null;
      rowState.sync = null;
      rowState.onTreeSelection = null;
      rowStates.delete(rowState);
    };
    const activateRow = (row, rowState) => {
      treeState.activeRow = row;
      rowState.selectedPaths = category
        ? qualifiedPaths(category, readPaths(row)) : readPaths(row);
      rows.querySelectorAll(".active").forEach(item => item.classList.remove("active"));
      row.classList.add("active");
      rowState.sync?.();
    };
    const syncRow = (row, rowState) => {
      if (row !== treeState.activeRow) return;
      rowState.selectedPaths = category
        ? qualifiedPaths(category, readPaths(row)) : readPaths(row);
      rowState.sync?.();
    };
    const addRow = item => {
      const rowState = {
        selectedPaths: [],
        sync: null,
        mounted: false,
        loading: false,
        renderToken: 0,
        treeMount: null,
        onTreeSelection: null,
      };
      rowStates.add(rowState);
      const row = labelRow(context, category, item, treeState, {
        labelEditable: options.labelsEditable,
        pathEditable: options.pathsEditable,
        removable: options.removable === true,
        activate: (target = row, targetState = rowState) => activateRow(target, targetState),
        sync: () => syncRow(row, rowState),
        rowState,
        dispose: () => disposeRow(rowState),
        openTree: mount => options.renderTree?.({
          mount, category, treeState: rowState, editable: options.pathsEditable,
        }),
      });
      row._factorTesterCategoryRowState = rowState;
      rows.append(row);
      if (!treeState.activeRow) activateRow(row, rowState);
    };
    items.forEach(addRow);
    if (options.labelsEditable && !category?.is_composite && !category?.source_managed) {
      const add = FTUI.actionButton(context.t("新增条目"), () => addRow({}), {
        variant: "secondary",
      });
      add.type = "button";
      section.append(rows, add);
    } else {
      section.append(rows);
    }
    return {
      section,
      items: () => [...rows.children].map(row => ({
        label: row.querySelector("[data-category-label]")?.value || "",
        paths: readPaths(row),
        ...(row.dataset.generated === "true" ? {label_generated: true} : {}),
      })),
      dispose: () => [...rowStates].forEach(disposeRow),
    };
  }

  function labelRow(context, category, item, treeState, options) {
    const row = document.createElement("div");
    row.className = "product-category-item-row product-category-label-form-row";
    const generated = item.label_generated === true || item.label === "Others";
    if (generated) {
      row.dataset.generated = "true";
      row.classList.add("product-category-generated-item");
    }
    const id = document.createElement("code");
    id.textContent = item.label_id || (category
      ? `${category.id}_${(category.items || []).indexOf(item) + 1}` : "—");
    const label = document.createElement("input");
    label.value = item.label || "";
    label.required = true;
    label.dataset.categoryLabel = "true";
    label.placeholder = context.t("条目标签");
    label.readOnly = options.labelEditable !== true || generated;
    const paths = document.createElement("textarea");
    paths.value = (item.paths || [])
      .filter(path => !String(path).trim().startsWith("-"))
      .map(path => categoryFreePath(category, path))
      .join("\n");
    paths.rows = 3;
    paths.required = true;
    paths.readOnly = options.pathEditable !== true || generated;
    paths.placeholder = context.t("每行一个具体产品路径");
    const pathEditor = document.createElement("div");
    pathEditor.className = "product-category-path-editor";
    const rowState = options.rowState;
    rowState.onTreeSelection = selected => {
      rowState.selectedPaths = selected;
      if (options.pathEditable !== true || generated) return;
      const values = category ? unqualifiedPaths(category, selected) : selected;
      paths.value = FTProductTree.minimalPaths(values).join("\n");
    };
    const toggle = FTUI.actionButton(context.t("显示产品树"), () => {
      options.activate();
      const open = inline.hidden;
      inline.hidden = !open;
      toggle.textContent = context.t(open ? "隐藏产品树" : "显示产品树");
      if (!open) {
        rowState.renderToken += 1;
        rowState.loading = false;
        rowState.mounted = false;
        rowState.treeMount?.replaceChildren();
        rowState.treeMount = null;
        return;
      }
      if (open && !rowState.mounted && !rowState.loading) {
        const renderToken = ++rowState.renderToken;
        rowState.loading = true;
        rowState.treeMount = treeMount;
        treeMount.replaceChildren(FTUI.loading(context.t("正在读取分类产品…")));
        Promise.resolve()
          .then(() => options.openTree?.(treeMount))
          .then(() => {
            if (renderToken !== rowState.renderToken || inline.hidden) {
              treeMount.replaceChildren();
              rowState.mounted = false;
              rowState.treeMount = null;
              return;
            }
            rowState.mounted = true;
          })
          .catch(error => {
            if (renderToken === rowState.renderToken && !inline.hidden) {
              treeMount.replaceChildren(FTUI.empty(
                context.t("产品解析失败"), error.message || context.t("请稍后重试"),
              ));
            }
          })
          .finally(() => {
            if (renderToken === rowState.renderToken) rowState.loading = false;
          });
      }
    }, {
      variant: "secondary",
    });
    toggle.type = "button";
    pathEditor.append(paths, toggle);
    const inline = document.createElement("div");
    inline.className = "product-category-inline-tree";
    inline.hidden = true;
    const treeMount = document.createElement("div");
    treeMount.className = "product-category-detail-tree";
    if (treeMount.dataset) treeMount.dataset.ftScrollState = "product-category-detail-tree";
    rowState.treeMount = treeMount;
    inline.append(treeMount);
    const controls = document.createElement("div");
    controls.className = "product-category-item-controls";
    const remove = FTUI.actionButton(context.t("移除"), () => {
      if (generated || !options.removable || row.parentElement.children.length <= 1) return;
      const next = row.nextElementSibling || row.previousElementSibling;
      options.dispose?.();
      row.remove();
      if (treeState.activeRow === row) {
        options.activate(next, next?._factorTesterCategoryRowState);
      }
    }, {variant: "secondary"});
    remove.type = "button";
    remove.disabled = !options.removable || generated;
    controls.append(remove);
    label.addEventListener("focus", options.activate);
    paths.addEventListener("focus", options.activate);
    paths.addEventListener("input", options.sync);
    row.addEventListener("click", event => {
      if (!pathEditor.contains(event.target) && !controls.contains(event.target)) {
        options.activate();
      }
    });
    row.append(id, label, pathEditor, controls, inline);
    return row;
  }

  function readPaths(row) {
    return [...row.querySelectorAll("textarea")]
      .flatMap(field => field.value.split(/\r?\n/))
      .map(value => value.trim())
      .filter(value => value && !value.startsWith("-"));
  }

  function validateLabels(context, items, creating) {
    if (!creating && !items) return "";
    if (!items?.length) return context.t("产品分类至少需要一个条目");
    const labels = new Set();
    for (const item of items) {
      const label = String(item.label || "").trim();
      if (!label || labels.has(label)) return context.t("Label 标题不能为空且不能重复");
      if (label === "Others" && !item.label_generated) {
        return context.t("Others 是系统保留 Label，不能手动创建");
      }
      if (!(item.paths || []).length) return context.t("每个 Label 至少需要一条产品路径");
      if ((item.paths || []).some(path => String(path).trim().startsWith("ProductCategory/"))) {
        return context.t("产品分类不能引用其他分类，请填写具体产品路径");
      }
      labels.add(label);
    }
    return "";
  }

  function qualifiedPaths(category, values) {
    return (values || [])
      .filter(path => !String(path).trim().startsWith("-"))
      .map(path => categoryFreePath(category, path));
  }

  function unqualifiedPaths(category, values) {
    return (values || []).map(value => categoryFreePath(category, value));
  }

  function categoryFreePath(category, value) {
    const path = String(value || "").trim().replace(/^\/+/, "");
    if (!category) return path;
    const prefix = `ProductCategory/${category.id}/`;
    return path.startsWith(prefix) ? path.slice(prefix.length) : path;
  }

  window.FTProductCategoryLabels = Object.freeze({
    render,
    validate: validateLabels,
  });
})();
