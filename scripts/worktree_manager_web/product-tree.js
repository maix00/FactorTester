(() => {
  function sourceOf() {
    return new URLSearchParams(location.search).get("source") === "local"
      ? "local" : "server";
  }

  function catalogPath(path) {
    return sourceOf() === "local" ? `${path}?source=local` : path;
  }

  function roots(value) {
    const items = Array.isArray(value) ? value : [value];
    const shell = items.find(item => item && item.key === "Product");
    return shell && Array.isArray(shell.children) ? shell.children : items;
  }

  function render(context, mount, value, options = {}) {
    const all = roots(value).filter(Boolean);
    const categoryKeys = new Set(options.selectedCategories || all.map(item => item.key));
    const categories = document.createElement("section");
    categories.className = "product-category-filter";
    const heading = document.createElement("div");
    heading.className = "section-heading";
    heading.innerHTML = `<div><h2>${context.t("产品类别")}</h2><p>${context.t("选择类别后保存，产品树会重新渲染")}</p></div>`;
    const save = document.createElement("button");
    save.className = "primary";
    save.type = "button";
    save.textContent = context.t("保存");
    heading.append(save);
    categories.append(heading);
    const choices = document.createElement("div");
    choices.className = "product-category-choices";
    const inputs = new Map();
    all.forEach(node => {
      const label = document.createElement("label");
      label.className = "check-row";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = categoryKeys.has(node.key);
      input.dataset.category = node.key;
      inputs.set(node.key, input);
      label.append(input, document.createTextNode(node.title || node.key));
      choices.append(label);
    });
    categories.append(choices);
    const tree = document.createElement("div");
    tree.className = "product-tree";
    save.addEventListener("click", () => {
      const selected = [...inputs.entries()].filter(([, input]) => input.checked)
        .map(([key]) => key);
      const next = selected.length ? selected : all.map(item => item.key);
      options.onSave?.(next);
      drawNodes(context, tree, all.filter(item => next.includes(item.key)));
    });
    mount.replaceChildren(categories, tree);
    drawNodes(context, tree, all.filter(item => categoryKeys.has(item.key)));
  }

  function drawNodes(context, mount, nodes) {
    mount.replaceChildren();
    if (!nodes.length) {
      mount.append(FTUI.empty(context.t("没有选择产品类别"), context.t("至少选择一个类别后保存")));
      return;
    }
    nodes.forEach(node => appendNode(context, mount, node, 0));
  }

  function appendNode(context, mount, node, depth) {
    const hasChildren = node.folder || node.lazy || Array.isArray(node.children);
    const title = String(node.title || node.name || node.key || "");
    if (!hasChildren) {
      const link = document.createElement("button");
      link.type = "button";
      link.className = "product-tree-leaf";
      link.textContent = title;
      link.title = node.desc || title;
      link.addEventListener("click", () => {
        const kind = node.product_type === "contract" ? "contract" : "product";
        const target = node.product_name || node.contract_uid || node.key || title;
        context.navigate(catalogPath(`/products/${kind}/${encodeURIComponent(target)}`));
      });
      mount.append(link);
      return;
    }
    const details = document.createElement("details");
    details.className = "product-tree-node";
    details.open = depth === 0;
    const summary = document.createElement("summary");
    summary.textContent = title;
    details.append(summary);
    const children = document.createElement("div");
    children.className = "product-tree-children";
    details.append(children);
    const renderChildren = values => {
      children.replaceChildren();
      (Array.isArray(values) ? values : []).forEach(item =>
        appendNode(context, children, item, depth + 1)
      );
      details.dataset.loaded = "true";
    };
    if (Array.isArray(node.children)) renderChildren(node.children);
    details.addEventListener("toggle", async () => {
      if (!details.open || details.dataset.loaded === "true" || !node.lazy) return;
      details.dataset.loaded = "loading";
      children.replaceChildren(FTUI.loading(context.t("正在读取产品节点…")));
      try {
        const payload = await context.api(context.servicePath(
          `/api/contract_tree?path=${encodeURIComponent(node.key || "")}`
        ));
        renderChildren(payload);
      } catch (error) {
        details.dataset.loaded = "error";
        children.replaceChildren(FTUI.empty(context.t("产品节点读取失败"), error.message || ""));
      }
    });
    mount.append(details);
  }

  window.FTProductTree = {render};
})();
