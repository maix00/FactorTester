(() => {
  const structural = new Set(["chapter", "section", "subsection", "special"]);
  const internalLabels = new Set(["正文", "表格", "列表", "代码", "代码块", "JSON", "json", "图片", "公式"]);

  function isCollapsible(component) {
    return component.kind === "special" || (
      ["section", "subsection", "table"].includes(component.kind)
      && ["current_obligations", "obligation_requirement_coverage"].includes(
        component.display_kind || "",
      )
    );
  }

  function usesSectionBridge(component) {
    return structural.has(component.kind) || isCollapsible(component);
  }

  function isInternalLabel(title) {
    return internalLabels.has(String(title || "").trim());
  }

  function renderCell(cell, context) {
    if (cell == null) return document.createDocumentFragment();
    if (typeof cell === "string" || typeof cell === "number" || typeof cell === "boolean") {
      return FTRichText.blocks(String(cell), context);
    }
    if (cell && typeof cell === "object") {
      const target = cell.target || cell.href || cell.url || cell.reference;
      const label = cell.label || cell.title || cell.text || cell.filename;
      if (target && label) {
        const fragment = document.createDocumentFragment();
        FTRichText.appendLink(fragment, String(label), String(target), context);
        return fragment;
      }
    }
    const pre = document.createElement("pre");
    pre.className = "json-code";
    pre.textContent = JSON.stringify(cell, null, 2);
    return pre;
  }

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
        cell.append(renderCell(item, context));
      }
    }
    shell.append(element);
    return shell;
  }

  function estimatedHeight(component) {
    const content = component.content;
    if (component.kind === "image") return 160;
    if (component.kind === "math" || component.display_kind === "display_math") return 48;
    if (component.kind === "code" || component.kind === "json") return 96;
    if (component.kind === "table") {
      const rows = Array.isArray(content) ? content : content?.rows || [];
      return Math.min(560, Math.max(56, 40 + rows.length * 32));
    }
    if (component.kind === "list") {
      const rows = content?.items || content?.rows || content;
      return Math.min(420, Math.max(32, 24 + (Array.isArray(rows) ? rows.length * 26 : 26)));
    }
    const text = `${component.title || ""}\n${component.body || ""}`;
    return Math.min(240, Math.max(28, Math.ceil(text.length / 110) * 24));
  }

  function renderLeafInto(body, component, context) {
    body.replaceChildren();
    if (component.body) body.append(FTRichText.blocks(component.body, context));
    const content = component.content;
    const assetRef = typeof content === "object" && content
      ? content.asset_id || content.asset_ref : null;
    if ((component.kind === "image" || assetRef) && assetRef) {
      const image = document.createElement("img");
      image.className = "report-image";
      image.alt = component.title || "";
      image.loading = "lazy";
      image.src = context.reportAssetPath?.(assetRef) || "";
      body.append(image);
    } else if (component.kind === "table") body.append(table(content, context));
    else if (component.kind === "list" && Array.isArray(content?.items || content?.rows || content)) {
      const list = document.createElement("ul");
      (content.items || content.rows || content).forEach(item => {
        const row = document.createElement("li");
        if (Number(item?.depth) > 0) row.style.marginLeft = `${Math.min(Number(item.depth), 8) * 18}px`;
        const target = item && typeof item === "object"
          ? item.target || item.href || item.url || item.reference : null;
        const label = item && typeof item === "object"
          ? item.label || item.title || item.text || item.filename : null;
        if (target && label) FTRichText.appendLink(row, String(label), String(target), context);
        else row.append(FTRichText.inline(String(item?.text ?? item ?? ""), context));
        list.append(row);
      });
      body.append(list);
    } else if (component.kind === "code" || component.kind === "json") {
      const pre = document.createElement("pre");
      pre.className = component.kind === "json" ? "json-code" : "";
      pre.textContent = typeof content === "string" ? content : JSON.stringify(content, null, 2);
      body.append(pre);
    } else if (component.kind === "math" || component.display_kind === "display_math") {
      const math = document.createElement("div");
      math.className = "display-math";
      const latex = typeof content === "object" ? content.latex || content.formula : content;
      katex.render(String(latex || component.body || ""), math, {displayMode: true, throwOnError: false});
      body.append(math);
    } else if (!component.body && content != null && component.kind !== "image") {
      const pre = document.createElement("pre");
      pre.className = "json-code";
      pre.textContent = typeof content === "string" ? content : JSON.stringify(content, null, 2);
      body.append(pre);
    }
  }

  function leaf(component, context) {
    const body = document.createElement("div");
    body.className = "component-body";
    renderLeafInto(body, component, context);
    return body;
  }

  function lazyLeaf(component, context) {
    const body = document.createElement("div");
    body.className = "component-body component-body-lazy";
    body.dataset.lazyState = "pending";
    body.style.minHeight = `${estimatedHeight(component)}px`;
    const mount = () => {
      if (body.dataset.lazyState === "ready") return;
      body.dataset.lazyState = "ready";
      body.style.removeProperty("min-height");
      renderLeafInto(body, component, context);
    };
    if (context.lazyRendering === false || typeof IntersectionObserver !== "function") {
      mount();
      return body;
    }
    const observer = new IntersectionObserver(entries => {
      if (!entries.some(entry => entry.isIntersecting)) return;
      observer.disconnect();
      context.lazyObservers?.delete(observer);
      mount();
    }, {rootMargin: context.lazyRootMargin || "600px 0px"});
    context.lazyObservers?.add(observer);
    observer.observe(body);
    return body;
  }

  function estimatedChildrenHeight(children) {
    if (!children.length) return 0;
    const total = children.reduce((height, child) => {
      const nested = estimatedChildrenHeight(child.children || []);
      return height + Math.max(30, estimatedHeight(child.component) + nested);
    }, 0);
    return Math.min(1200, Math.max(30, total));
  }

  function lazyChildren(children, context, depth) {
    const host = document.createElement("div");
    host.className = "component-children component-children-lazy";
    host.dataset.lazyState = "pending";
    host.style.minHeight = `${estimatedChildrenHeight(children)}px`;
    let mounted = false;
    let observer = null;
    const mount = () => {
      if (mounted) return;
      mounted = true;
      host.dataset.lazyState = "ready";
      host.style.removeProperty("min-height");
      if (observer) {
        observer.disconnect();
        context.lazyObservers?.delete(observer);
        observer = null;
      }
      host.replaceChildren(renderBridgeGroup(children, context, depth));
    };
    if (context.lazyRendering === false || typeof IntersectionObserver !== "function") {
      mount();
      return host;
    }
    observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) mount();
    }, {rootMargin: context.lazyRootMargin || "600px 0px"});
    context.lazyObservers?.add(observer);
    observer.observe(host);
    return host;
  }

  function renderBridgeGroup(children, context, depth = 0) {
    const host = document.createElement("div");
    host.className = "section-bridge";
    if (children.some(child => usesSectionBridge(child.component))) host.classList.add("contains-section-bridge");
    children.forEach(child => host.append(componentView(child.component, child.children, context, depth, true)));
    return host;
  }

  function componentView(component, children, context, depth = 0, bridgeEntry = false) {
    const wrapper = document.createElement("section");
    wrapper.className = `component depth-${Math.min(depth, 8)} ${component.kind} ${component.display_kind || ""}${bridgeEntry ? " bridge-entry" : ""}`;
    const hasDisclosure = usesSectionBridge(component) || children.length > 0;
    if (!hasDisclosure) {
      if (component.title && !isInternalLabel(component.title)) {
        const heading = document.createElement("h3");
        heading.className = "component-body-title";
        heading.append(FTRichText.inline(component.title, context));
        wrapper.append(heading);
      }
      wrapper.append(lazyLeaf(component, context));
      return wrapper;
    }
    const details = document.createElement("details");
    details.dataset.componentKind = component.kind || "";
    details.dataset.displayKind = component.display_kind || "";
    details.open = !isCollapsible(component);
    const summary = document.createElement("summary");
    const marker = document.createElement("span");
    marker.className = "section-marker";
    marker.textContent = "";
    const displayKind = component.display_kind || component.kind;
    const icon = FTIcons.node(FTIcons.section(component.kind, displayKind), `section-icon section-icon-${displayKind}`);
    summary.append(marker, icon);
    summary.append(FTRichText.inline(component.title || context.t("未命名小节"), context));
    summary.querySelectorAll("a").forEach(link => link.addEventListener("click", event => event.stopPropagation()));
    details.append(summary);
    let rendered = false;
    const renderChildren = () => {
      if (rendered) return;
      rendered = true;
      if (component.body || component.content != null) details.append(lazyLeaf(component, context));
      if (children.length) details.append(lazyChildren(children, context, depth + 1));
    };
    if (details.open) renderChildren();
    details.addEventListener("toggle", () => { if (details.open) renderChildren(); });
    wrapper.append(details);
    return wrapper;
  }

  window.FTReportComponents = Object.freeze({
    isCollapsible, usesSectionBridge, isInternalLabel, renderCell, table, leaf,
    renderBridgeGroup, componentView,
  });
})();
