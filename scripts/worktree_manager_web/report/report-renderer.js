(() => {
  const {renderBridgeGroup, componentView} = FTReportComponents;
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
    mount.__ftLazyCleanup?.();
    mount.replaceChildren();
    const lazyObservers = new Set();
    mount.__ftLazyCleanup = () => {
      lazyObservers.forEach(observer => observer.disconnect());
      lazyObservers.clear();
    };
    const roots = tree(report.components || []).filter(node => node.component.kind === "chapter");
    const bindings = report.bindings || [];
    const referenceMeta = {};
    const bindingByID = {};
    bindings.forEach(binding => {
      if (binding.target_ref) referenceMeta[binding.target_ref] = binding;
      if (binding.binding_id) bindingByID[binding.binding_id] = binding;
    });
    context = {...context, referenceMeta, bindingByID, lazyObservers};
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
