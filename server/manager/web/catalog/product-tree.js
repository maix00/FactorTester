(() => {
  function sourceOf() {
    return new URLSearchParams(location.search).get("source") === "local"
      ? "local" : "server";
  }

  function catalogPath(path, source = sourceOf()) {
    const [pathname, rawQuery = ""] = String(path).split("?", 2);
    const query = new URLSearchParams(rawQuery);
    if (source === "local") query.set("source", "local");
    const encoded = query.toString();
    return encoded ? `${pathname}?${encoded}` : pathname;
  }

  function treeValue(value) {
    return Array.isArray(value) ? value : (Array.isArray(value?.tree) ? value.tree : []);
  }

  function roots(value) {
    const items = treeValue(value);
    const shell = items.find(item => item && item.key === "Product");
    return shell && Array.isArray(shell.children) ? shell.children : items;
  }

  function minimalPaths(values) {
    const ordered = [...new Set((values || []).map(value => (
      String(value || "").trim()
    )).filter(Boolean))].sort((left, right) => (
      left.length - right.length || left.localeCompare(right)
    ));
    return ordered.filter(value => !ordered.some(parent => (
      parent !== value && value.startsWith(`${parent}/`)
    )));
  }

  function updateSelection(values, path, checked) {
    const target = String(path || "").trim();
    if (!target) return minimalPaths(values);
    const next = new Set(minimalPaths(values));
    if (!checked) {
      next.delete(target);
      return [...next];
    }
    if ([...next].some(parent => target.startsWith(`${parent}/`))) {
      return [...next];
    }
    [...next].filter(child => child.startsWith(`${target}/`))
      .forEach(child => next.delete(child));
    next.add(target);
    return minimalPaths([...next]);
  }

  function syncSelectionControls(container, values) {
    const selected = new Set(minimalPaths(values));
    container?.querySelectorAll("input[data-product-path]").forEach(input => {
      input.checked = selected.has(input.dataset.productPath);
    });
  }

  function nodeTitle(context, node) {
    const title = String(node.title || node.name || node.key || "");
    return title === "Product Lists"
      ? context.t("本级产品列表") : title;
  }

  function categorySelectionValues(value, available = []) {
    const known = new Set(available.map(item => String(item?.id || "").trim()));
    const values = Array.isArray(value) ? value : [String(value || "")];
    const result = [];
    values.forEach(item => String(item || "").split(",").forEach(raw => {
      const categoryID = raw.trim();
      if (!categoryID) return;
      // Migrate the old UI's unregistered base-category composition.  A
      // registered composite ID remains one selectable category.
      const legacyParts = categoryID.split("_x_");
      if (!known.has(categoryID) && legacyParts.length > 1
        && legacyParts.every(part => known.has(part))) {
        legacyParts.forEach(part => {
          if (!result.includes(part)) result.push(part);
        });
        return;
      }
      if (!result.includes(categoryID)) result.push(categoryID);
    }));
    return result;
  }

  function categorySelectionID(values, available) {
    const selected = new Set(values);
    return available.filter(item => selected.has(item.id))
      .map(item => item.id).join(",");
  }

  function categoryLabel(context, item) {
    return String(item?.title_zh || item?.alias || item?.id || context.t("分类"));
  }

  function categoryCountLabel(context, count) {
    return context.t("已选分类数", "已选%lld个")
      .replace(/%lld/g, String(count));
  }

  async function render(context, mount, value, options = {}) {
    const all = roots(value).filter(Boolean);
    const definitions = Array.isArray(options.categoryDefinitions)
      ? options.categoryDefinitions : [];
    const available = definitions.filter(
      (item, index, allItems) => item?.id && (
        allItems.findIndex(candidate => candidate?.id === item.id) === index
      ),
    );
    const availableIDs = new Set(available.map(item => item.id));
    const selectedCategories = new Set(
      categorySelectionValues(options.selectedCategory, available)
        .filter(categoryID => availableIDs.has(categoryID)),
    );
    const categories = document.createElement("section");
    categories.className = "product-category-filter";
    const toolbar = document.createElement("div");
    toolbar.className = "product-category-toolbar";
    const heading = document.createElement("h2");
    heading.textContent = context.t("产品分类");
    toolbar.append(heading);
    const controls = document.createElement("div");
    controls.className = "product-category-controls";
    const dropdown = document.createElement("details");
    dropdown.className = "product-category-dropdown";
    const summary = document.createElement("summary");
    summary.setAttribute("aria-label", context.t("产品分类"));
    const summaryLabel = document.createElement("span");
    summaryLabel.className = "product-category-summary";
    summary.append(summaryLabel);
    const selectionNote = document.createElement("div");
    selectionNote.className = "product-category-selection-note";
    selectionNote.setAttribute("aria-live", "polite");
    const menu = document.createElement("div");
    menu.className = "product-category-menu";
    menu.setAttribute("role", "group");
    menu.setAttribute("aria-label", context.t("产品分类"));
    const choiceInputs = [];
    const noCategory = document.createElement("label");
    noCategory.className = "product-category-option product-category-option-none";
    const noCategoryInput = document.createElement("input");
    noCategoryInput.type = "checkbox";
    noCategoryInput.dataset.productCategory = "";
    noCategoryInput.checked = selectedCategories.size === 0;
    const noCategoryText = document.createElement("span");
    noCategoryText.textContent = context.t("不使用分类");
    noCategory.append(noCategoryInput, noCategoryText);
    menu.append(noCategory);
    available.forEach(item => {
      const choice = document.createElement("label");
      choice.className = "product-category-option";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.dataset.productCategory = item.id;
      input.checked = selectedCategories.has(item.id);
      const text = document.createElement("span");
      text.textContent = categoryLabel(context, item);
      choice.append(input, text);
      menu.append(choice);
      choiceInputs.push(input);
    });
    const actions = document.createElement("div");
    actions.className = "product-category-menu-actions";
    const apply = FTUI.actionButton(context.t("应用分类"), async () => {
      const nextID = categorySelectionID([...selectedCategories], available);
      apply.disabled = true;
      try {
        await options.onSave?.(nextID);
        dropdown.open = false;
      } catch (error) {
        context.showNotice?.(error.message || context.t("产品树读取失败"), true);
      } finally { apply.disabled = false; }
    }, {variant: "primary"});
    apply.classList.add("product-category-apply");
    actions.append(apply);
    menu.append(actions);
    const updateSummary = () => {
      const labels = available.filter(item => selectedCategories.has(item.id))
        .map(item => categoryLabel(context, item));
      const labelText = labels.length ? labels.join("、") : context.t("不使用分类");
      summaryLabel.textContent = labels.length
        ? categoryCountLabel(context, labels.length) : labelText;
      selectionNote.textContent = labelText;
      summary.title = labelText;
      noCategoryInput.checked = labels.length === 0;
      choiceInputs.forEach(input => {
        input.checked = selectedCategories.has(input.dataset.productCategory);
      });
    };
    noCategoryInput.addEventListener("change", () => {
      if (noCategoryInput.checked) selectedCategories.clear();
      updateSummary();
    });
    choiceInputs.forEach(input => input.addEventListener("change", () => {
      if (input.checked) selectedCategories.add(input.dataset.productCategory);
      else selectedCategories.delete(input.dataset.productCategory);
      updateSummary();
    }));
    updateSummary();
    dropdown.append(summary, menu);
    controls.append(dropdown, selectionNote);
    toolbar.append(controls);
    categories.append(toolbar);

    const tree = document.createElement("div");
    tree.className = "product-tree";
    if (options.categoryMount && options.categoryMount !== mount) {
      options.categoryMount.replaceChildren(categories);
      mount.replaceChildren(tree);
    } else {
      mount.replaceChildren(categories, tree);
    }
    drawNodes(context, tree, all, options);
  }

  function drawNodes(context, mount, nodes, options = {}) {
    mount.replaceChildren();
    if (!nodes.length) {
      mount.append(FTUI.empty(
        context.t("没有可显示的产品节点"),
        context.t("当前可用数据源没有提供产品"),
      ));
      return;
    }
    nodes.forEach(node => appendNode(context, mount, node, 0, options));
  }

  function selectionControl(node, options) {
    if (!options.selectable || node.checkbox === false) return null;
    const input = document.createElement("input");
    input.type = "checkbox";
    input.dataset.productPath = node.key;
    input.checked = minimalPaths(options.selectedPaths).includes(node.key);
    input.addEventListener("click", event => event.stopPropagation());
    input.addEventListener("change", event => {
      event.stopPropagation();
      options.selectedPaths = updateSelection(
        options.selectedPaths, node.key, input.checked,
      );
      syncSelectionControls(input.closest(".product-tree"), options.selectedPaths);
      options.onSelectionChange?.([...options.selectedPaths]);
    });
    return input;
  }

  function appendNode(context, mount, node, depth, options) {
    const hasChildren = node.folder || node.lazy || Array.isArray(node.children);
    const title = nodeTitle(context, node);
    if (!hasChildren) {
      const selection = selectionControl(node, options);
      if (selection) {
        const row = document.createElement("label");
        row.className = "product-tree-selection";
        const text = document.createElement("span");
        text.textContent = title; text.title = node.desc || title;
        row.append(selection, text); mount.append(row); return;
      }
      const link = document.createElement("button");
      link.type = "button"; link.className = "product-tree-leaf";
      link.textContent = title; link.title = node.desc || title;
      link.addEventListener("click", () => {
        const kind = node.product_type === "contract" ? "contract" : "product";
        const target = node.product_name || node.contract_uid || node.key || title;
        context.navigate(catalogPath(`/products/${kind}/${encodeURIComponent(target)}`));
      });
      mount.append(link); return;
    }
    const details = document.createElement("details");
    details.className = "product-tree-node";
    details.dataset.depth = String(depth);
    details.style.setProperty("--tree-depth", String(depth));
    details.open = FTProductCategoryModel.treeNodeInitiallyOpen(node, depth);
    const summary = document.createElement("summary");
    const selection = selectionControl(node, options);
    if (selection) summary.append(selection);
    summary.append(document.createTextNode(title));
    details.append(summary);
    const children = document.createElement("div");
    children.className = "product-tree-children"; details.append(children);
    const renderChildren = values => {
      children.replaceChildren();
      (Array.isArray(values) ? values : []).forEach(item =>
        appendNode(context, children, item, depth + 1, options));
      details.dataset.loaded = "true";
    };
    if (Array.isArray(node.children)) renderChildren(node.children);
    details.addEventListener("toggle", async () => {
      if (!details.open || details.dataset.loaded === "true" || !node.lazy) return;
      details.dataset.loaded = "loading";
      // Product Lists nodes and classifier nodes that directly own objects
      // are both lazy catalog leaves.  The latter is common in the futures
      // tree and must not fall back to rendering hundreds of buttons.
      details.dataset.loaded = "true";
      window.FTProductListTable.render(context, children, node, options);
      return;
    });
    mount.append(details);
  }

  window.FTProductTree = {
    categorySelectionID, categorySelectionValues, minimalPaths, render,
    syncSelectionControls, updateSelection,
  };
})();
