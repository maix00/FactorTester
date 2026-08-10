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

  async function render(context, mount, value, options = {}) {
    const all = roots(value).filter(Boolean);
    const definitions = Array.isArray(options.categoryDefinitions)
      ? options.categoryDefinitions : [];
    const combinations = Array.isArray(options.savedCombinations)
      ? options.savedCombinations : [];
    const available = [...definitions, ...combinations].filter(
      (item, index, allItems) => item?.id && (
        allItems.findIndex(candidate => candidate?.id === item.id) === index
      ),
    );
    const selected = options.selectedCategory || "";
    const categories = document.createElement("section");
    categories.className = "product-category-filter";
    const heading = document.createElement("div");
    heading.className = "section-heading";
    heading.innerHTML = `<div><h2>${context.t("产品分类")}</h2><p>${context.t("自动使用当前全部可用数据源；选择一个分类，或当场创建乘积分类")}</p></div>`;
    const save = FTUI.actionButton(context.t("应用分类"), null, {
      variant: "primary",
    });
    categories.append(heading);

    const choices = document.createElement("div");
    choices.className = "product-category-choices";
    const appendChoice = (item, checked = false) => {
      const label = document.createElement("label");
      label.className = "check-row";
      const input = document.createElement("input");
      input.type = "radio"; input.name = "product-category";
      input.value = item.id; input.checked = checked;
      label.append(input, document.createTextNode(item.title_zh || item.alias || item.id));
      choices.append(label);
      return input;
    };
    appendChoice({id: "", title_zh: context.t("不使用分类")}, !selected);
    available.forEach(item => appendChoice(item, selected === item.id));
    categories.append(choices);

    const create = FTUI.actionButton(context.t("创建乘积分类"), null, {
      variant: "secondary",
    });
    const actions = document.createElement("div");
    actions.className = "product-category-actions";
    actions.append(create, save);
    categories.append(actions);

    create.addEventListener("click", async () => {
      const selectedCategories = await FTProductCategoryOverlay.choose(
        context, available,
      );
      if (!selectedCategories) return;
      try {
        const definition = FTProductCategoryModel.multiply(
          available, selectedCategories,
        );
        const next = combinations.some(item => item.id === definition.id)
          ? combinations.slice() : [...combinations, definition];
        await options.onSave?.(definition.id, next);
      } catch (error) {
        context.showNotice?.(context.t(error.message), true);
      }
    });

    const tree = document.createElement("div");
    tree.className = "product-tree";
    save.addEventListener("click", async () => {
      const nextID = categories.querySelector(
        "input[name=product-category]:checked",
      )?.value || "";
      save.disabled = true;
      try {
        await options.onSave?.(nextID, combinations.slice());
      } catch (error) {
        context.showNotice?.(error.message || context.t("产品树读取失败"), true);
      } finally { save.disabled = false; }
    });
    mount.replaceChildren(categories, tree);
    drawNodes(context, tree, all, options.contractTreePath);
  }

  function drawNodes(context, mount, nodes, contractTreePath) {
    mount.replaceChildren();
    if (!nodes.length) {
      mount.append(FTUI.empty(
        context.t("没有可显示的产品节点"),
        context.t("当前可用数据源没有提供产品"),
      ));
      return;
    }
    nodes.forEach(node => appendNode(context, mount, node, 0, contractTreePath));
  }

  function appendNode(context, mount, node, depth, contractTreePath) {
    const hasChildren = node.folder || node.lazy || Array.isArray(node.children);
    const title = String(node.title || node.name || node.key || "");
    if (!hasChildren) {
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
    details.open = FTProductCategoryModel.treeNodeInitiallyOpen(node, depth);
    const summary = document.createElement("summary"); summary.textContent = title;
    details.append(summary);
    const children = document.createElement("div");
    children.className = "product-tree-children"; details.append(children);
    const renderChildren = values => {
      children.replaceChildren();
      (Array.isArray(values) ? values : []).forEach(item =>
        appendNode(context, children, item, depth + 1, contractTreePath));
      details.dataset.loaded = "true";
    };
    if (Array.isArray(node.children)) renderChildren(node.children);
    details.addEventListener("toggle", async () => {
      if (!details.open || details.dataset.loaded === "true" || !node.lazy) return;
      details.dataset.loaded = "loading";
      children.replaceChildren(FTUI.loading(context.t("正在读取产品节点…")));
      try {
        const payload = await context.api(contractTreePath(node.key || ""));
        renderChildren(payload.nodes || payload);
      } catch (error) {
        details.dataset.loaded = "error";
        children.replaceChildren(FTUI.empty(context.t("产品节点读取失败"), error.message || context.t("请稍后重试")));
      }
    });
    mount.append(details);
  }

  window.FTProductTree = {render};
})();
