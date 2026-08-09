(() => {
  function sourceOf() {
    return new URLSearchParams(location.search).get("source") === "local"
      ? "local" : "server";
  }

  function catalogPath(path, source = sourceOf()) {
    const [pathname, rawQuery = ""] = String(path).split("?", 2);
    const query = new URLSearchParams(rawQuery);
    if (source === "local") query.set("source", "local");
    new URLSearchParams(location.search).getAll("data_source").forEach(value => {
      query.append("data_source", value);
    });
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

  function categoryID(dimensions, selected) {
    if (selected) return selected;
    const ids = [...dimensions];
    if (ids.length === 2 && ids.includes("day_night") && ids.includes("sector")) {
      return "day_night_x_sector";
    }
    return ids[0] || "";
  }

  async function render(context, mount, value, options = {}) {
    const all = roots(value).filter(Boolean);
    const definitions = Array.isArray(options.categoryDefinitions)
      ? options.categoryDefinitions : [];
    const base = definitions.filter(item => item.composable && !item.is_composite);
    const combinations = Array.isArray(options.savedCombinations)
      ? options.savedCombinations : [];
    const selected = options.selectedCategory || "";
    const sourceDefinitions = Array.isArray(options.dataSourceDefinitions)
      ? options.dataSourceDefinitions : [];
    const selectedSources = new Set(Array.isArray(options.selectedDataSources)
      ? options.selectedDataSources : []);
    const categories = document.createElement("section");
    categories.className = "product-category-filter";
    const heading = document.createElement("div");
    heading.className = "section-heading";
    heading.innerHTML = `<div><h2>${context.t("数据源与产品分类")}</h2><p>${context.t("数据源决定可用产品；Category 为空时展示完整路径，复合 Category 由你当场创建")}</p></div>`;
    const save = document.createElement("button");
    save.className = "primary"; save.type = "button";
    save.textContent = context.t("保存并刷新产品树");
    heading.append(save); categories.append(heading);

    const sourceChoices = document.createElement("div");
    sourceChoices.className = "product-source-choices";
    const sourceInputs = new Map();
    sourceDefinitions.forEach(item => {
      const label = document.createElement("label");
      label.className = "check-row product-source-choice";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.dataset.source = item.id;
      input.checked = selectedSources.has(item.id);
      const count = Number(item.availability?.product_count || 0);
      input.disabled = count <= 0;
      sourceInputs.set(item.id, input);
      label.append(
        input,
        document.createTextNode(`${item.source_name || item.bundle_name || item.id} · ${count}`),
      );
      sourceChoices.append(label);
    });
    if (sourceChoices.childElementCount) {
      const caption = document.createElement("span");
      caption.className = "product-category-caption";
      caption.textContent = context.t("数据源");
      categories.append(caption, sourceChoices);
    }

    const choices = document.createElement("div");
    choices.className = "product-category-choices";
    const inputs = new Map();
    base.forEach(item => {
      const label = document.createElement("label");
      label.className = "check-row";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = selected === item.id || (selected === "day_night_x_sector"
        && ["day_night", "sector"].includes(item.id));
      input.dataset.category = item.id;
      inputs.set(item.id, input);
      input.addEventListener("change", () => {
        categories.querySelectorAll("input[name=saved-product-category]").forEach(radio => {
          radio.checked = false;
        });
      });
      label.append(input, document.createTextNode(item.title_zh || item.alias || item.id));
      choices.append(label);
    });
    categories.append(choices);

    if (combinations.length) {
      const saved = document.createElement("div");
      saved.className = "product-category-saved";
      const label = document.createElement("span");
      label.className = "product-category-caption";
      label.textContent = context.t("已添加的复合分类");
      saved.append(label);
      combinations.forEach(item => {
        const row = document.createElement("label");
        row.className = "check-row saved-category-row";
        const input = document.createElement("input");
        input.type = "radio"; input.name = "saved-product-category";
        input.value = item.id; input.checked = selected === item.id;
        row.append(input, document.createTextNode(item.title_zh || item.alias || item.id));
        saved.append(row);
      });
      categories.append(saved);
    }

    const tree = document.createElement("div");
    tree.className = "product-tree";
    save.addEventListener("click", async () => {
      const selectedDimensions = [...inputs.entries()]
        .filter(([, input]) => input.checked).map(([id]) => id);
      const nextSources = [...sourceInputs.entries()]
        .filter(([, input]) => input.checked).map(([id]) => id);
      const selectedRadio = categories.querySelector("input[name=saved-product-category]:checked")?.value;
      const nextID = categoryID(selectedDimensions, selectedRadio);
      if (sourceInputs.size && !nextSources.length) {
        context.showNotice?.(context.t("请至少选择一个当前可用的数据源"), true);
        return;
      }
      if (selectedDimensions.length > 2) {
        context.showNotice?.(context.t("目前最多组合两个分类维度"), true);
        return;
      }
      let nextCombinations = combinations.slice();
      if (selectedDimensions.length === 2) {
        const canonical = ["day_night", "sector"].filter(id => selectedDimensions.includes(id));
        const definition = {
          id: "day_night_x_sector", alias: "日夜盘×行业",
          title_zh: "日夜盘×行业", dimensions: canonical,
          composable: false, is_composite: true,
        };
        if (!nextCombinations.some(item => item.id === definition.id)) nextCombinations.push(definition);
      }
      save.disabled = true;
      try {
        await options.onSave?.(nextID, nextCombinations, nextSources);
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
      mount.append(FTUI.empty(context.t("没有可显示的产品节点"), context.t("请先选择并保存一个分类维度")));
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
    details.className = "product-tree-node"; details.open = depth === 0;
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
