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

  function leaf(component, context) {
    const body = document.createElement("div");
    body.className = "component-body";
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
        row.append(FTRichText.inline(String(item?.text ?? item ?? ""), context));
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
      const latex = typeof content === "object"
        ? content.latex || content.formula : content;
      katex.render(String(latex || component.body || ""), math, {displayMode: true, throwOnError: false});
      body.append(math);
    } else if (!component.body && content != null && component.kind !== "image") {
      const pre = document.createElement("pre");
      pre.className = "json-code";
      pre.textContent = typeof content === "string" ? content : JSON.stringify(content, null, 2);
      body.append(pre);
    }
    return body;
  }

  function renderBridgeGroup(children, context, depth = 0) {
    const host = document.createElement("div");
    host.className = "section-bridge";
    if (children.some(child => usesSectionBridge(child.component))) {
      host.classList.add("contains-section-bridge");
    }
    children.forEach(child => {
      const entry = componentView(child.component, child.children, context, depth, true);
      host.append(entry);
    });
    return host;
  }

  function componentView(component, children, context, depth = 0, bridgeEntry = false) {
    const wrapper = document.createElement("section");
    wrapper.className = `component depth-${Math.min(depth, 8)} ${component.kind} ${component.display_kind || ""}${bridgeEntry ? " bridge-entry" : ""}`;
    const hasDisclosure = usesSectionBridge(component) || children.length > 0;
    if (!hasDisclosure) {
      if (component.title && !isInternalLabel(component.title)) {
        const heading = document.createElement("h3");
        heading.append(FTRichText.inline(component.title, context));
        wrapper.append(heading);
      }
      wrapper.append(leaf(component, context));
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
    const icon = FTIcons.node(
      FTIcons.section(component.kind, displayKind),
      `section-icon section-icon-${displayKind}`,
    );
    summary.append(marker, icon);
    summary.append(FTRichText.inline(component.title || context.t("未命名小节"), context));
    summary.querySelectorAll("a").forEach(link => link.addEventListener("click", event => event.stopPropagation()));
    details.append(summary);
    let rendered = false;
    const renderChildren = () => {
      if (rendered) return;
      rendered = true;
      if (component.body || component.content != null) details.append(leaf(component, context));
      if (children.length) details.append(renderBridgeGroup(children, context, depth + 1));
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
    const bindingByID = {};
    bindings.forEach(binding => {
      if (binding.target_ref) referenceMeta[binding.target_ref] = binding;
      if (binding.binding_id) bindingByID[binding.binding_id] = binding;
    });
    context = {...context, referenceMeta, bindingByID};
    const rail = context.chapterRail;
    const markerScale = distance => {
      const progress = distance === 0 ? 1 : distance === 1 ? .7 : distance === 2 ? .4 : distance === 3 ? .2 : 0;
      return .2308 + (.7692 * progress);
    };
    let selected = Math.max(roots.length - 1, 0);
    if (rail) {
      rail.hidden = roots.length === 0;
      rail.setAttribute("aria-label", context.t?.("章节导航") || "章节导航");
      const tooltip = document.createElement("div");
      tooltip.className = "chapter-rail-tooltip";
      tooltip.hidden = true;
      tooltip.setAttribute("role", "tooltip");
      tooltip.innerHTML = `<div class="chapter-rail-tooltip-title"></div><div class="chapter-rail-tooltip-preview"></div><div class="chapter-rail-tooltip-meta"></div>`;
      const titleNode = tooltip.querySelector(".chapter-rail-tooltip-title");
      const previewNode = tooltip.querySelector(".chapter-rail-tooltip-preview");
      const metaNode = tooltip.querySelector(".chapter-rail-tooltip-meta");
      let interactionIndex = selected;
      let tooltipTimer = null;
      let hideTimer = null;
      const updateMarkerTarget = target => {
        interactionIndex = Number.isInteger(target) ? target : selected;
        rail.querySelectorAll(".chapter-rail-item").forEach((markerItem, markerIndex) => {
          const distance = Math.abs(markerIndex - interactionIndex);
          const fill = markerItem.querySelector(".chapter-rail-marker-fill");
          markerItem.classList.toggle("active", markerIndex === selected);
          markerItem.classList.toggle("interaction-target", markerIndex === interactionIndex);
          markerItem.classList.toggle("nearby", distance === 1);
          markerItem.classList.toggle("far", distance > 1);
          if (fill) fill.style.transform = `scaleX(${markerScale(distance).toFixed(4)})`;
        });
      };
      const hideTooltip = () => {
        if (tooltipTimer) window.clearTimeout(tooltipTimer);
        if (hideTimer) window.clearTimeout(hideTimer);
        tooltip.classList.remove("visible");
        hideTimer = window.setTimeout(() => { tooltip.hidden = true; }, 160);
      };
      const showTooltip = (item, node, index) => {
        updateMarkerTarget(index);
        if (hideTimer) window.clearTimeout(hideTimer);
        if (tooltipTimer) window.clearTimeout(tooltipTimer);
        tooltipTimer = window.setTimeout(() => {
        titleNode.textContent = node.component.title || `${context.t?.("章节") || "章节"} ${index + 1}`;
        // Swift's timeline outline uses the first child title as the chapter
        // preview. Public projections do not need to duplicate that derived
        // field: derive it from the same tree and keep any explicit preview
        // supplied by a newer projection as the first choice. Do not fall
        // back to the chapter body: that makes the callout much larger than
        // the Swift preview and leaks arbitrary report content into it.
        const firstChildTitle = node.children?.[0]?.component?.title || "";
        const preview = node.component.preview || (
          firstChildTitle !== (node.component.title || "") ? firstChildTitle : ""
        );
        previewNode.textContent = String(preview).replace(/\s+/g, " ").trim().slice(0, 240);
        const rawDate = node.component.created_at;
        const timestamp = typeof rawDate === "number"
          ? rawDate > 1e12 ? rawDate : rawDate * 1000
          : null;
        const date = timestamp != null
          ? new Date(timestamp)
          : new Date(String(rawDate || ""));
        const dateText = Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
        const graphBinding = (node.component.binding_ids || [])
          .map(bindingID => bindingByID[bindingID])
          .filter(binding => binding?.kind === "graph_reference")
          .find(Boolean);
        const graphRef = graphBinding
          ? node.component.graph_version
            || graphBinding.data?.graph_version
            || graphBinding.data?.graph_ref
            || ""
          : "";
        const graphVersion = (() => {
          if (typeof graphRef === "number") return `v${graphRef}`;
          const value = String(graphRef).trim();
          if (!value) return "";
          const suffix = value.includes("@") ? value.slice(value.lastIndexOf("@") + 1) : value;
          return /^v?\d+$/.test(suffix) ? (suffix.startsWith("v") ? suffix : `v${suffix}`) : "";
        })();
        metaNode.textContent = [dateText, graphVersion].filter(Boolean).join(" · ");
        previewNode.hidden = !previewNode.textContent;
        metaNode.hidden = !metaNode.textContent;
        const itemBox = item.getBoundingClientRect();
        const panelWidth = Math.min(320, Math.max(0, window.innerWidth - 16));
        tooltip.style.left = `${Math.max(8, Math.min(itemBox.right + 4, window.innerWidth - panelWidth - 8))}px`;
        tooltip.style.top = `${Math.max(8, Math.min(itemBox.top + itemBox.height / 2 - 46, window.innerHeight - 126))}px`;
        tooltip.hidden = false;
        requestAnimationFrame(() => tooltip.classList.add("visible"));
        }, 80);
      };
      rail.replaceChildren(...roots.map((node, index) => {
        const item = document.createElement("button");
        item.type = "button";
        item.className = "chapter-rail-item";
        item.dataset.index = String(index);
        item.setAttribute("aria-current", index === selected ? "true" : "false");
        item.setAttribute("aria-label", `${context.t?.("跳转到章节") || "跳转到章节"} ${node.component.title || index + 1}`);
        item.innerHTML = `<span class="chapter-rail-marker" aria-hidden="true"><span class="chapter-rail-marker-fill"></span></span>`;
        item.addEventListener("pointerenter", () => showTooltip(item, node, index));
        item.addEventListener("pointerleave", () => { updateMarkerTarget(selected); hideTooltip(); });
        item.addEventListener("focus", () => showTooltip(item, node, index));
        item.addEventListener("blur", () => { updateMarkerTarget(selected); hideTooltip(); });
        item.addEventListener("click", () => {
          selected = index;
          draw();
          item.scrollIntoView({block: "center", behavior: "smooth"});
        });
        return item;
      }));
      // Keep the tooltip outside the scrollable rail. This is the same sibling
      // overlay used by SwiftUI; otherwise overflow-y would clip it at the rail edge.
      document.querySelectorAll(".chapter-rail-tooltip").forEach(item => item.remove());
      document.body.append(tooltip);
      const itemAt = index => rail.querySelector(`[data-index="${index}"]`);
      let scrubbing = false;
      const nearestIndex = clientY => {
        const items = [...rail.querySelectorAll(".chapter-rail-item")];
        return items.reduce((best, item) => {
          const distance = Math.abs(item.getBoundingClientRect().top + item.offsetHeight / 2 - clientY);
          return distance < best.distance ? {distance, index: Number(item.dataset.index)} : best;
        }, {distance: Infinity, index: selected}).index;
      };
      rail.addEventListener("pointerdown", event => {
        if (event.button !== 0 || event.target.closest(".chapter-rail-tooltip")) return;
        scrubbing = true;
        rail.setPointerCapture?.(event.pointerId);
        const index = nearestIndex(event.clientY);
        if (Number.isInteger(index)) {
          selected = index;
          updateMarkerTarget(index);
          showTooltip(itemAt(index), roots[index], index);
          draw();
        }
      });
      rail.addEventListener("pointermove", event => {
        if (!scrubbing) return;
        const index = nearestIndex(event.clientY);
        if (Number.isInteger(index) && index !== selected) {
          selected = index;
          updateMarkerTarget(index);
          showTooltip(itemAt(index), roots[index], index);
          draw();
        }
      });
      const stopScrubbing = event => {
        if (!scrubbing) return;
        scrubbing = false;
        updateMarkerTarget(selected);
        if (!event.target.closest?.(".chapter-rail-item")) hideTooltip();
        rail.releasePointerCapture?.(event.pointerId);
      };
      rail.addEventListener("pointerup", stopScrubbing);
      rail.addEventListener("pointercancel", stopScrubbing);
      const updateOverflow = () => {
        if (!rail.isConnected) {
          window.removeEventListener("resize", updateOverflow);
          return;
        }
        const maximumHeight = Math.min(window.innerHeight * .7, 640);
        rail.classList.toggle("overflow", roots.length * 14 > maximumHeight);
      };
      updateOverflow();
      window.addEventListener("resize", updateOverflow, {passive: true});
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
      const headingRow = document.createElement("div");
      headingRow.className = "chapter-heading-row";
      const heading = document.createElement("h2");
      heading.className = "chapter-title";
      heading.textContent = node.component.title || `${context.t?.("章节") || "章节"} ${selected + 1}`;
      const disclosure = document.createElement("button");
      disclosure.type = "button";
      disclosure.className = "chapter-disclosure-reset";
      disclosure.textContent = "↕";
      disclosure.title = context.t?.("展开或收起章节") || "展开或收起章节";
      disclosure.setAttribute("aria-label", disclosure.title);
      disclosure.addEventListener("click", event => {
        event.preventDefault();
        event.stopPropagation();
        // A chapter control only owns the chapter's direct children.  Do not
        // walk nested details: opening a chapter must not eagerly expand its
        // descendants or change a special subsection's lazy state.
        const bridge = [...article.children].find(item =>
          item.classList.contains("section-bridge"),
        );
        const firstLevel = bridge
          ? [...bridge.children]
            .map(entry => [...entry.children].find(child => child.tagName === "DETAILS"))
            .filter(Boolean)
          : [];
        const ordinary = firstLevel.filter(item =>
          item.dataset.componentKind !== "special"
          && !["current_obligations", "obligation_requirement_coverage"].includes(
            item.dataset.displayKind,
          ),
        );
        const shouldExpand = ordinary.some(item => !item.open);
        if (shouldExpand) {
          ordinary.forEach(item => { item.open = true; });
          // A manually opened special subsection remains lazy and collapsed
          // when returning to the chapter's default expanded view.
          firstLevel
            .filter(item => !ordinary.includes(item))
            .forEach(item => { item.open = false; });
        } else {
          firstLevel.forEach(item => { item.open = false; });
        }
        disclosure.textContent = shouldExpand ? "⌃" : "⌄";
        disclosure.setAttribute("aria-label", shouldExpand
          ? (context.t?.("收起章节") || "收起章节")
          : (context.t?.("展开章节") || "展开章节"));
      });
      headingRow.append(heading, disclosure);
      article.append(headingRow);
      if (node.children.length) article.append(renderBridgeGroup(node.children, context, 0));
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
      if (fill) fill.style.transform = `scaleX(${markerScale(distance).toFixed(4)})`;
    });
    const originalDraw = draw;
    draw = () => { originalDraw(); refreshRail(); };
    draw();
    if (rail && selected >= 0 && context.restoreScrollY == null) {
      requestAnimationFrame(() => {
        rail.querySelector(`[data-index="${selected}"]`)?.scrollIntoView({block: "center"});
      });
    }
    if (!context.suppressAutoScroll) {
      requestAnimationFrame(() => window.scrollTo({top: document.body.scrollHeight}));
    }
  }

  window.FTReportRenderer = {render};
})();
