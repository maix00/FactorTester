(() => {
  function localAvailable() {
    return window.FTAppRuntime?.hasLocalCatalog?.() === true;
  }

  function endpoints(source) {
    if (source === "local") {
      return {
        categories: "/api/client/product_categories",
        sources: "/api/client/product_sources",
        tree: "/api/client/product_tree",
        contracts: "/api/client/contract_tree",
      };
    }
    return {
      categories: "/api/catalog/categories",
      sources: "/api/catalog/sources",
      tree: "/api/catalog/tree",
      contracts: "/api/catalog/contract-tree",
    };
  }

  function storageValue(key, fallback) {
    try {
      const value = JSON.parse(localStorage.getItem(key) || "null");
      return value == null ? fallback : value;
    } catch (_) { return fallback; }
  }

  function sourceField(context, state, rerender) {
    const field = document.createElement("label");
    field.className = "test-object-field";
    const label = document.createElement("b");
    label.textContent = context.t("产品目录");
    const select = document.createElement("select");
    const choices = localAvailable()
      ? [["local", "本地产品目录"], ["server", "服务器产品目录"]]
      : [["server", "服务器产品目录"]];
    choices.forEach(([value, title]) => {
      const option = document.createElement("option");
      option.value = value; option.textContent = context.t(title); select.append(option);
    });
    select.value = state.source;
    select.addEventListener("change", () => {
      state.source = select.value;
      state.categoryID = "";
      state.selectedPaths = [];
      rerender();
    });
    field.append(label, select);
    return field;
  }

  function queryPath(base, categoryID, sourceIDs, path = "") {
    const query = new URLSearchParams({checkbox: "1"});
    if (categoryID) query.set("category", categoryID);
    if (path) query.set("path", path);
    (sourceIDs || []).forEach(value => query.append("data_source", value));
    return `${base}?${query}`;
  }

  async function catalog(context, state) {
    const paths = endpoints(state.source);
    const [categoryPayload, sourcePayload] = await Promise.all([
      context.api(paths.categories), context.api(paths.sources),
    ]);
    const categories = Array.isArray(categoryPayload.categories)
      ? categoryPayload.categories : [];
    const sources = Array.isArray(sourcePayload.sources) ? sourcePayload.sources : [];
    const sourceIDs = FTProductCategoryModel.availableSourceIDs(sources);
    const treePayload = await context.api(queryPath(
      paths.tree, state.categoryID, sourceIDs,
    ));
    return {
      categories, paths, sourceIDs,
      tree: treePayload.tree || treePayload,
    };
  }

  async function renderTree(context, state, mount, status, updateSummary) {
    mount.replaceChildren(FTUI.loading(context.t("正在读取产品目录…")));
    status.textContent = "";
    try {
      const value = await catalog(context, state);
      const combinationKey = `ft-product-category-definitions:${state.source}`;
      const combinations = storageValue(combinationKey, []);
      const options = {
        categoryDefinitions: value.categories,
        savedCombinations: Array.isArray(combinations) ? combinations : [],
        selectedCategory: state.categoryID,
        selectable: true,
        selectedPaths: state.selectedPaths,
        onSelectionChange: selected => {
          state.selectedPaths = FTProductTree.minimalPaths(selected);
          updateSummary();
        },
        contractTreePath: path => queryPath(
          value.paths.contracts, state.categoryID, value.sourceIDs, path,
        ),
        onSave: async (categoryID, nextCombinations) => {
          state.categoryID = categoryID || "";
          state.selectedPaths = [];
          localStorage.setItem(combinationKey, JSON.stringify(nextCombinations || []));
          localStorage.setItem(`ft-product-category:${state.source}`, state.categoryID);
          await renderTree(context, state, mount, status, updateSummary);
          updateSummary();
        },
      };
      await FTProductTree.render(context, mount, value.tree, options);
      updateSummary();
    } catch (error) {
      mount.replaceChildren(FTUI.empty(
        context.t("产品目录读取失败"), error.message || context.t("请稍后重试"),
      ));
    }
  }

  function open(context, options = {}) {
    const dialog = document.createElement("dialog");
    dialog.className = "test-product-group-dialog";
    const form = document.createElement("form");
    form.className = "test-product-group-creator";
    const heading = document.createElement("div"); heading.className = "section-heading";
    const copy = document.createElement("div");
    const title = document.createElement("h2"); title.textContent = context.t("新建产品组");
    const note = document.createElement("p");
    note.textContent = context.t("从产品树选择稳定路径；父路径会自动覆盖其子路径");
    copy.append(title, note); heading.append(copy);

    const state = {
      source: localAvailable() ? "local" : "server",
      categoryID: "", selectedPaths: [],
    };
    const fields = document.createElement("div"); fields.className = "test-product-group-fields";
    const nameField = document.createElement("label"); nameField.className = "test-object-field";
    const nameLabel = document.createElement("b"); nameLabel.textContent = context.t("产品组名称");
    const name = document.createElement("input"); name.required = true;
    name.placeholder = context.t("产品组名称"); nameField.append(nameLabel, name);
    const tree = document.createElement("div"); tree.className = "test-product-group-tree";
    const summary = document.createElement("small"); summary.className = "test-product-group-summary";
    const status = document.createElement("small"); status.className = "test-product-group-error";
    const updateSummary = () => {
      summary.textContent = `${context.t("已选择")} ${state.selectedPaths.length} ${context.t("条产品路径")}`;
    };
    const rerender = () => renderTree(context, state, tree, status, updateSummary);
    fields.append(nameField, sourceField(context, state, rerender));

    const actions = document.createElement("div"); actions.className = "test-product-group-actions";
    const cancel = FTUI.actionButton(context.t("取消"), () => dialog.close(), {
      variant: "secondary",
    });
    const save = FTUI.actionButton(context.t("创建并选中"), null, {
      variant: "primary",
    });
    save.type = "submit"; actions.append(cancel, save);
    form.append(heading, fields, summary, tree, status, actions);
    form.addEventListener("submit", async event => {
      event.preventDefault();
      state.selectedPaths = FTProductTree.minimalPaths(state.selectedPaths);
      if (!state.selectedPaths.length) {
        status.textContent = context.t("请从产品树选择至少一条产品路径");
        return;
      }
      save.disabled = true; status.textContent = "";
      try {
        const value = await context.api("/api/catalog/product-groups", {
          method: "POST",
          body: JSON.stringify({name: name.value.trim(), paths: state.selectedPaths}),
        });
        await options.onCreate?.(value.group);
        dialog.close();
      } catch (error) {
        status.textContent = error.message || context.t("产品组创建失败");
      } finally { save.disabled = false; }
    });
    dialog.addEventListener("close", () => dialog.remove(), {once: true});
    dialog.append(form); document.body.append(dialog); dialog.showModal();
    updateSummary(); rerender(); name.focus();
    return dialog;
  }

  window.FTProductGroupCreator = Object.freeze({catalog, endpoints, open, queryPath});
})();
