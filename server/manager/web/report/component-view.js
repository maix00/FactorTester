(() => {
  const structural = new Set(["chapter", "section", "subsection", "special"]);
  const internalLabels = new Set(["正文", "表格", "列表", "代码", "代码块", "JSON", "json", "图片", "公式"]);
  const MAX_ESTIMATE_DEPTH = 2;

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

  function hasPayload(component) {
    return Boolean(
      component?.content_available
      || component?.body
      || component?.content != null,
    );
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
    const rows = Array.isArray(value) ? value : value?.rows || [];
    const columns = value?.columns || value?.headers || (
      rows[0] && typeof rows[0] === "object" ? Object.keys(rows[0]) : []
    );
    return FTReportTables.render({
      columns,
      rows,
      context,
      renderHeader: column => FTRichText.inline(
        String(column?.title || column?.label || column), context,
      ),
      renderCell: item => renderCell(item, context),
      values: row => Array.isArray(row)
        ? row
        : Array.isArray(row?.cells)
          ? row.cells
          : columns.map(column => row?.[column?.key || column]),
    });
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

  function isJSONCode(component, content) {
    if (component.kind === "json" || typeof content !== "string") return true;
    const declared = [
      component.language, component.format, component.media_type,
      component.content_type, component.display_kind,
    ].filter(Boolean).join(" ").toLowerCase();
    if (declared.includes("json")) return true;
    const source = content.trim();
    if (!source || !["{", "["].includes(source[0])) return false;
    try {
      const parsed = JSON.parse(source);
      return parsed !== null && typeof parsed === "object";
    } catch (_) {
      return false;
    }
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
      if (context.loadReportAsset) {
        Promise.resolve(context.loadReportAsset(assetRef)).then(blob => {
          if (!blob || !image.isConnected) return;
          const url = URL.createObjectURL(blob);
          image.src = url;
          image.addEventListener("load", () => URL.revokeObjectURL(url), {once: true});
        }).catch(() => {
          image.alt = `${component.title || assetRef} (${context.t?.("读取失败") || "读取失败"})`;
        });
      } else {
        image.src = context.reportAssetPath?.(assetRef) || "";
      }
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
      pre.className = isJSONCode(component, content) ? "json-code" : "";
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
    const renderGeneration = Number(context.renderGeneration || 0);
    let dispose = null;
    const mount = () => {
      if (Number(context.renderGeneration || 0) !== renderGeneration) {
        dispose?.();
        dispose = null;
        return;
      }
      if (body.dataset.lazyState === "ready") return;
      dispose?.();
      dispose = null;
      const finish = value => {
        if (Number(context.renderGeneration || 0) !== renderGeneration
          || context.lazyDisposed) return;
        body.dataset.lazyState = "ready";
        body.style.removeProperty("min-height");
        renderLeafInto(body, value || component, context);
      };
      const canLoad = Boolean(
        context.loadComponent
        && context.chapterID
        && context.componentContentLazy?.() !== false,
      );
      if (!canLoad || !component.component_id) {
        finish(component);
        return;
      }
      body.dataset.lazyState = "loading";
      Promise.resolve(context.loadComponent(
        context.chapterID, component.component_id,
      )).then(finish).catch(error => {
        if (Number(context.renderGeneration || 0) !== renderGeneration
          || context.lazyDisposed) return;
        body.dataset.lazyState = "error";
        body.style.removeProperty("min-height");
        body.textContent = context.t?.("内容读取失败") || "内容读取失败";
        body.title = error?.message || "";
      });
    };
    dispose = window.FTReportLazyRuntime.observe(body, context, mount);
    if (!dispose) {
      mount();
      return body;
    }
    return body;
  }

  function estimatedComponentHeight(node, cache, depth = 0) {
    if (cache.has(node)) return cache.get(node);
    const value = Math.max(
      30,
      estimatedHeight(node.component) + estimatedChildrenHeight(node.children || [], cache, depth),
    );
    cache.set(node, value);
    return value;
  }

  function estimatedChildrenHeight(children, cache, depth = 0) {
    if (!children.length) return 0;
    // Placeholder sizing must not defeat structural lazy loading by walking
    // every descendant.  Deep descendants are represented by a bounded row
    // estimate and are parsed only after their bridge becomes visible.
    if (depth >= MAX_ESTIMATE_DEPTH) {
      return Math.min(1200, Math.max(30, children.length * 42));
    }
    const total = children.reduce((height, child) => {
      return height + estimatedComponentHeight(child, cache, depth + 1);
    }, 0);
    return Math.min(1200, Math.max(30, total));
  }

  function lazyChildren(children, context, depth) {
    const host = document.createElement("div");
    host.className = "component-children component-children-lazy";
    host.dataset.lazyState = "pending";
    const estimateCache = context.estimatedHeightCache
      || (context.estimatedHeightCache = new WeakMap());
    host.style.minHeight = `${estimatedChildrenHeight(children, estimateCache)}px`;
    const renderGeneration = Number(context.renderGeneration || 0);
    let mounted = false;
    let dispose = null;
    const mount = () => {
      if (Number(context.renderGeneration || 0) !== renderGeneration) {
        dispose?.();
        dispose = null;
        return;
      }
      if (mounted) return;
      mounted = true;
      host.dataset.lazyState = "ready";
      host.style.removeProperty("min-height");
      dispose?.();
      dispose = null;
      host.replaceChildren(renderBridgeGroup(children, context, depth));
    };
    dispose = window.FTReportLazyRuntime.observe(host, context, mount);
    if (!dispose) {
      mount();
      return host;
    }
    return host;
  }

  function renderBridgeGroup(children, context, depth = 0) {
    const host = document.createElement("div");
    host.className = "section-bridge";
    if (children.some(child => usesSectionBridge(child.component))) host.classList.add("contains-section-bridge");
    children.forEach(child => host.append(componentView(child.component, child.children, context, depth, true)));
    return host;
  }

  function hasVisibleTitle(component) {
    return Boolean(component.title && !isInternalLabel(component.title));
  }

  function scheduleDisclosureAnchor(summary, beforeTop) {
    if (!Number.isFinite(beforeTop) || !summary?.getBoundingClientRect) return;
    const defer = window.requestAnimationFrame || (callback => setTimeout(callback, 0));
    defer(() => {
      const afterTop = summary.getBoundingClientRect().top;
      const delta = afterTop - beforeTop;
      const current = Number(window.scrollY) || 0;
      const scrollingElement = document.scrollingElement || document.documentElement;
      const documentHeight = Number(scrollingElement?.scrollHeight);
      const viewportHeight = Number(window.innerHeight);
      const maximum = Number.isFinite(documentHeight) && Number.isFinite(viewportHeight)
        ? Math.max(0, documentHeight - viewportHeight)
        : Infinity;
      const target = Math.max(0, Math.min(maximum, current + delta));
      const correction = target - current;
      if (Math.abs(correction) < 1) return;
      if (typeof window.scrollTo === "function") {
        // Clamp after a bottom-of-document collapse as well as preserving the
        // summary anchor. Without this, scrollY can remain beyond the new
        // document height and the report appears blank until the next wheel
        // event corrects it.
        window.scrollTo({top: target, behavior: "auto"});
      } else if (typeof window.scrollBy === "function") {
        window.scrollBy({top: correction, behavior: "auto"});
      }
    });
  }

  function componentView(component, children, context, depth = 0, bridgeEntry = false) {
    const wrapper = document.createElement("section");
    // Legacy subsection is a section; only ancestry controls presentation depth.
    const sectionKind = component.kind === "subsection" ? "section" : component.kind;
    wrapper.className = `component depth-${Math.min(depth, 8)} ${sectionKind} ${component.display_kind || ""}${bridgeEntry ? " bridge-entry" : ""}`;
    // A titled content component is still a report subsection from the
    // reader's perspective, even when its payload is a single list, table,
    // or paragraph. Keep it in the same default-open disclosure path as
    // structural sections; internal renderer labels remain invisible.
    const hasDisclosure = usesSectionBridge(component)
      || children.length > 0
      || hasVisibleTitle(component);
    if (!hasDisclosure) {
      if (hasVisibleTitle(component)) {
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
    const disclosureKey = String(component.component_id || "").trim();
    if (disclosureKey) details.dataset.ftStateKey = `report-component:${disclosureKey}`;
    const savedDisclosure = disclosureKey
      ? context.disclosureState?.[disclosureKey]
      : undefined;
    details.open = typeof savedDisclosure === "boolean"
      ? savedDisclosure
      : !isCollapsible(component);
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
    let disclosureAnchorTop = null;
    const captureDisclosureAnchor = event => {
      if (event?.target?.closest?.("a")) return;
      disclosureAnchorTop = summary.getBoundingClientRect?.().top ?? null;
    };
    summary.addEventListener("pointerdown", captureDisclosureAnchor);
    summary.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") captureDisclosureAnchor(event);
    });
    let rendered = false;
    const renderChildren = () => {
      if (rendered) return;
      rendered = true;
      if (hasPayload(component)) details.append(lazyLeaf(component, context));
      if (children.length) details.append(lazyChildren(children, context, depth + 1));
    };
    if (details.open) renderChildren();
    details.addEventListener("toggle", () => {
      if (details.open) renderChildren();
      if (disclosureKey) context.setDisclosureState?.(disclosureKey, details.open);
      scheduleDisclosureAnchor(summary, disclosureAnchorTop);
      disclosureAnchorTop = null;
    });
    wrapper.append(details);
    return wrapper;
  }

  window.FTReportComponents = Object.freeze({
    isCollapsible, usesSectionBridge, isInternalLabel, hasVisibleTitle,
    scheduleDisclosureAnchor,
    renderCell, table, leaf,
    renderBridgeGroup, componentView,
  });
})();
