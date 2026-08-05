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
      const values = Array.isArray(row) ? row : columns.map(column => row[column?.key || column]);
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
    if (component.kind === "table") body.append(table(content, context));
    else if (component.kind === "list" && Array.isArray(content)) {
      const list = document.createElement("ul");
      content.forEach(item => {
        const row = document.createElement("li");
        row.append(FTRichText.inline(String(item), context));
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
      katex.render(String(content || component.body || ""), math, {displayMode: true, throwOnError: false});
      body.append(math);
    } else if (!component.body && content != null && component.kind !== "image") {
      const pre = document.createElement("pre");
      pre.textContent = typeof content === "string" ? content : JSON.stringify(content, null, 2);
      body.append(pre);
    }
    return body;
  }

  function componentView(component, children, context) {
    const wrapper = document.createElement("section");
    wrapper.className = `component ${component.kind} ${component.display_kind || ""}`;
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
    summary.append(FTRichText.inline(component.title || context.t("未命名小节"), context));
    details.append(summary);
    let rendered = false;
    const renderChildren = () => {
      if (rendered) return;
      rendered = true;
      if (component.body || component.content != null) details.append(leaf(component, context));
      children.forEach(child => details.append(componentView(child.component, child.children, context)));
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
    const picker = context.chapterPicker;
    if (picker) {
      picker.replaceChildren(...roots.map((node, index) => {
        const option = document.createElement("option");
        option.value = String(index);
        option.textContent = node.component.title || `${context.t("章节")} ${index + 1}`;
        return option;
      }));
    }
    let selected = Math.max(roots.length - 1, 0);
    const draw = () => {
      mount.replaceChildren();
      const node = roots[selected];
      if (!node) {
        mount.replaceChildren(FTUI.empty(context.t("本章节暂无内容"), ""));
        return;
      }
      const article = document.createElement("article");
      article.className = "chapter";
      node.children.forEach(child => article.append(componentView(child.component, child.children, context)));
      if (!node.children.length) article.append(FTUI.empty(context.t("本章节暂无内容"), ""));
      mount.append(article);
    };
    if (picker) picker.onchange = () => { selected = Number(picker.value); draw(); };
    if (picker) picker.value = String(selected);
    draw();
    requestAnimationFrame(() => window.scrollTo({top: document.body.scrollHeight}));
  }

  window.FTReportRenderer = {render};
})();
