(() => {
  function current(context) {
    return context.isRouteCurrent?.() !== false;
  }

  function splitBindings(group) {
    const bindings = Array.isArray(group?.path_bindings)
      ? group.path_bindings : [];
    if (bindings.length) {
      return bindings.map(item => ({
        id: item.id === "negative" ? "negative" : "positive",
        label: item.id === "negative" ? "负路径" : "正路径",
        paths: Array.isArray(item.paths) ? item.paths.filter(Boolean) : [],
      }));
    }
    const paths = Array.isArray(group?.selection_paths)
      ? group.selection_paths : (Array.isArray(group?.paths) ? group.paths : []);
    return [
      {id: "positive", label: "正路径", paths: paths.filter(path => !String(path).startsWith("-"))},
      {id: "negative", label: "负路径", paths: paths
        .filter(path => String(path).startsWith("-"))
        .map(path => String(path).slice(1))},
    ];
  }

  function displayPath(path, categories) {
    const raw = String(path || "").trim();
    const negative = raw.startsWith("-");
    const value = negative ? raw.slice(1).trim() : raw;
    const parts = value.split("/");
    const marker = parts.indexOf("ProductCategory");
    if (marker < 1 || parts.length <= marker + 2) return raw;
    const category = (categories || []).find(item => String(item.id) === parts[marker + 1]);
    const label = category?.items?.find(item => String(item.label_id) === parts[marker + 2]);
    if (!category || !label) return raw;
    parts[marker + 1] = category.title_zh || category.alias || category.id;
    parts.splice(marker + 2, 1, label.label || label.title || label.label_id);
    const displayed = parts.join("/");
    return negative ? `-${displayed}` : displayed;
  }

  function displayPaths(paths, categories) {
    return (Array.isArray(paths) ? paths : [])
      .map(path => displayPath(path, categories));
  }

  function renderRow(context, helpers, options) {
    const {
      source, categoryIDs, categories, sourceDefinitions, binding,
      editable, onChange,
    } = options;
    const section = document.createElement("section");
    section.className = `product-group-path-row product-group-path-${binding.id}`;
    const header = document.createElement("div");
    header.className = "product-group-path-row-header";
    const title = document.createElement("h3");
    title.textContent = context.t(binding.label);
    const toggle = FTUI.actionButton(context.t("显示产品树"), null, {variant: "secondary"});
    toggle.type = "button";
    header.append(title, toggle);

    const input = document.createElement("textarea");
    input.className = "product-group-path-input";
    input.rows = 3;
    input.readOnly = !editable;
    input.placeholder = context.t("每行一个产品路径；也可以从下方产品树选择");
    input.value = displayPaths(binding.paths, categories).join("\n");

    const treeMount = document.createElement("div");
    treeMount.className = "product-group-path-tree";
    if (treeMount.dataset) treeMount.dataset.ftScrollState = "product-group-path-tree";
    treeMount.hidden = true;
    let treeLoaded = false;
    let disposed = false;
    let selectedPaths = input.value.split(/\r?\n/).map(item => item.trim()).filter(Boolean);

    function syncFromInput() {
      selectedPaths = input.value.split(/\r?\n/).map(item => item.trim()).filter(Boolean);
      if (treeMount.dataset.loaded === "true") {
        FTProductTree.syncSelectionControls(treeMount, selectedPaths);
      }
    }

    async function loadTree() {
      if (treeLoaded || disposed) return;
      treeLoaded = true;
      treeMount.hidden = false;
      treeMount.replaceChildren(FTUI.loading(context.t("正在读取产品树…")));
      try {
        if (disposed || !current(context)) return;
        await FTCatalogSelectionTree.render(context, treeMount, helpers, {
          source, categoryIDs, sourceDefinitions,
          selectedPaths,
          editable,
          selectable: true,
          leafOnly: true,
          isCurrent: () => current(context) && !disposed,
          onTreeLoaded: () => {},
          onSelectionChange: next => {
            selectedPaths = next;
            input.value = selectedPaths.join("\n");
            onChange?.();
          },
        });
        treeMount.dataset.loaded = "true";
      } catch (error) {
        if (!disposed && current(context)) {
          treeMount.replaceChildren(FTUI.empty(
            context.t("产品树读取失败"), error.message || "",
          ));
        }
      }
    }

    toggle.addEventListener("click", () => {
      if (treeMount.hidden) {
        toggle.textContent = context.t("收起产品树");
        void loadTree();
      } else {
        treeMount.hidden = true;
        toggle.textContent = context.t("显示产品树");
      }
    });
    input.addEventListener("input", () => {
      syncFromInput();
      onChange?.();
    });
    section.append(header, input, treeMount);
    return {
      section,
      paths: () => input.value.split(/\r?\n/).map(item => item.trim()).filter(Boolean),
      dispose: () => {
        disposed = true;
        treeMount.replaceChildren();
        treeMount.dataset.loaded = "false";
      },
    };
  }

  function render(context, helpers, options = {}) {
    const root = document.createElement("section");
    root.className = "product-group-path-editor";
    const rows = [];
    const bindings = splitBindings(options.group);
    const source = options.source || "server";
    const categories = options.categories || [];
    const categoryIDs = options.categoryIDs || [];
    const sourceDefinitions = options.sourceDefinitions || null;
    bindings.forEach(binding => {
      const row = renderRow(context, helpers, {
        ...options,
        source, categories, categoryIDs, sourceDefinitions, binding,
        onChange: options.onChange,
      });
      rows.push(row);
      root.append(row.section);
    });
    return {
      root,
      paths: () => rows.flatMap((row, index) => row.paths().map(path => (
        index === 1 ? `-${path.replace(/^-/, "")}` : path.replace(/^-/, "")
      ))),
      dispose: () => rows.forEach(row => row.dispose()),
    };
  }

  window.FTProductGroupPathEditor = Object.freeze({render});
})();
