(() => {
  const structural = new Set(["chapter", "section", "subsection", "special"]);

  function table(value, context) {
    const shell = document.createElement("div");
    shell.className = "table-shell";
    const element = document.createElement("table");
    const rows = Array.isArray(value) ? value : value?.rows || [];
    const columns = value?.columns || value?.headers || (
      rows[0] && typeof rows[0] === "object" ? Object.keys(rows[0]) : []
    );
    if (columns.length) {
      const head = element.createTHead().insertRow();
      for (const column of columns) {
        const cell = document.createElement("th");
        cell.append(FTRichText.inline(String(column?.title || column?.label || column), context));
        head.append(cell);
      }
    }
    const body = element.createTBody();
    for (const row of rows) {
      const tr = body.insertRow();
      const values = Array.isArray(row)
        ? row
        : Array.isArray(row?.cells)
          ? row.cells
          : columns.map(column => row?.[column?.key || column]);
      for (const item of values) {
        const cell = tr.insertCell();
        cell.append(FTRichText.blocks(String(item ?? ""), context));
      }
    }
    shell.append(element);
    return shell;
  }

  function leaf(component, context) {
    const body = document.createElement("div");
    body.className = "component-body";
    if (component.body) body.append(FTRichText.blocks(component.body, context));
    const content = component.content;
    if (component.kind === "image" && content?.asset_id) {
      const image = document.createElement("img");
      image.className = "report-image";
      image.alt = component.title || "";
      image.loading = "lazy";
      image.src = context.reportAssetPath?.(content.asset_id) || "";
      body.append(image);
    } else if (component.kind === "table") body.append(table(content, context));
    else if (component.kind === "list" && Array.isArray(content?.rows || content)) {
      const list = document.createElement("ul");
      (content.rows || content).forEach(item => {
        const row = document.createElement("li");
        row.append(FTRichText.inline(String(item?.text ?? item ?? ""), context));
        list.append(row);
      });
      body.append(list);
    } else if (component.kind === "code" || component.kind === "json") {
      const pre = document.createElement("pre");
      pre.textContent = typeof content === "string" ? content : JSON.stringify(content, null, 2);
      body.append(pre);
    } else if (component.kind === "math") {
      const math = document.createElement("div");
      math.className = "display-math";
      const latex = typeof content === "object" ? content.latex : content;
      katex.render(String(latex || component.body || ""), math, {displayMode: true, throwOnError: false});
      body.append(math);
    } else if (!component.body && content != null && component.kind !== "image") {
      const pre = document.createElement("pre");
      pre.textContent = typeof content === "string" ? content : JSON.stringify(content, null, 2);
      body.append(pre);
    }
    return body;
  }

  function componentView(component, children, context, depth = 0) {
    const wrapper = document.createElement("section");
    wrapper.className = `component depth-${Math.min(depth, 8)} ${component.kind} ${component.display_kind || ""}`;
    const hasDisclosure = structural.has(component.kind) || children.length > 0;
    if (!hasDisclosure) {
      if (component.title) {
        const heading = document.createElement("h3");
        heading.append(FTRichText.inline(component.title, context));
        wrapper.append(heading);
      }
      wrapper.append(leaf(component, context));
      return wrapper;
    }
    const details = document.createElement("details");
    details.open = component.kind !== "special";
    const summary = document.createElement("summary");
    const marker = document.createElement("span");
    marker.className = "section-marker";
    marker.textContent = component.kind === "special" ? "!" : "•";
    const icon = document.createElement("span");
    icon.className = `section-icon section-icon-${component.display_kind || component.kind}`;
    icon.textContent = component.kind === "special" ? "!" : "▤";
    summary.append(marker, icon);
    summary.append(FTRichText.inline(component.title || context.t("未命名小节"), context));
    details.append(summary);
    let rendered = false;
    const renderChildren = () => {
      if (rendered) return;
      rendered = true;
      if (component.body || component.content != null) details.append(leaf(component, context));
      const childHost = document.createElement("div");
      childHost.className = "component-children";
      children.forEach(child => childHost.append(componentView(child.component, child.children, context, depth + 1)));
      if (children.length) details.append(childHost);
    };
    if (details.open) renderChildren();
    details.addEventListener("toggle", () => { if (details.open) renderChildren(); });
    wrapper.append(details);
    return wrapper;
  }

  function tree(components) {
    const nodes = new Map(components.map(component => [component.component_id, {component, children: []}]));
    const roots = [];
    for (const node of nodes.values()) {
      const parent = nodes.get(node.component.parent_id);
      (parent ? parent.children : roots).push(node);
    }
    return roots;
  }

  function render(report, mount, context = {}) {
    mount.replaceChildren();
    const roots = tree(report.components || []).filter(node => node.component.kind === "chapter");
    const bindings = report.bindings || [];
    const referenceMeta = {};
    bindings.forEach(binding => {
      if (binding.target_ref) referenceMeta[binding.target_ref] = binding;
    });
    context = {...context, referenceMeta};
    const rail = context.chapterRail;
    let selected = Math.max(roots.length - 1, 0);
    if (rail) {
      rail.replaceChildren(...roots.map((node, index) => {
        const item = document.createElement("button");
        item.type = "button";
        item.className = "chapter-rail-item";
        item.dataset.index = String(index);
        item.setAttribute("aria-current", index === selected ? "true" : "false");
        item.innerHTML = `<span class="chapter-rail-marker" aria-hidden="true"><span class="chapter-rail-marker-fill"></span></span><span class="chapter-rail-title"></span>`;
        item.querySelector(".chapter-rail-title").append(FTRichText.inline(node.component.title || `${context.t?.("章节") || "章节"} ${index + 1}`, context));
        item.title = node.component.title || "";
        item.addEventListener("click", () => { selected = index; draw(); item.scrollIntoView({block: "nearest"}); });
        return item;
      }));
    }
    let draw = () => {
      mount.replaceChildren();
      const node = roots[selected];
      if (!node) {
        mount.replaceChildren(FTUI.empty(context.t("本章节暂无内容"), ""));
        return;
      }
      const article = document.createElement("article");
      article.className = "chapter";
      const heading = document.createElement("h2");
      heading.className = "chapter-title";
      heading.textContent = node.component.title || `${context.t?.("章节") || "章节"} ${selected + 1}`;
      article.append(heading);
      node.children.forEach(child => article.append(componentView(child.component, child.children, context, 0)));
      if (!node.children.length) article.append(FTUI.empty(context.t("本章节暂无内容"), ""));
      mount.append(article);
    };
    const refreshRail = () => rail?.querySelectorAll(".chapter-rail-item").forEach((item, index) => {
      item.classList.toggle("active", index === selected);
      item.setAttribute("aria-current", index === selected ? "true" : "false");
      const distance = Math.abs(index - selected);
      item.classList.toggle("nearby", distance === 1);
      item.classList.toggle("far", distance > 1);
      const fill = item.querySelector(".chapter-rail-marker-fill");
      if (fill) fill.style.transform = `scaleX(${index === selected ? 1 : distance === 1 ? .7 : distance === 2 ? .4 : .23})`;
    });
    const originalDraw = draw;
    draw = () => { originalDraw(); refreshRail(); };
    draw();
    requestAnimationFrame(() => window.scrollTo({top: document.body.scrollHeight}));
  }

  window.FTReportRenderer = {render};
})();
