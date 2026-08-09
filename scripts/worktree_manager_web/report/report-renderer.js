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
      context.lazyDisposed = true;
      context.lazyCallbacks?.clear();
      lazyObservers.forEach(observer => observer.disconnect());
      lazyObservers.clear();
      context.lazyObserver = null;
      context.lazyCallbacks = null;
    };
    const chapterDescriptors = Array.isArray(report.chapters)
      ? report.chapters : [];
    const roots = chapterDescriptors.length
      ? chapterDescriptors.map(chapter => ({
        component: {
          component_id: chapter.component_id,
          kind: "chapter",
          parent_id: null,
          title: chapter.title || "",
          created_at: chapter.created_at,
          graph_version: chapter.graph_version,
          preview: chapter.preview || "",
        },
        children: [],
      }))
      : tree(report.components || []).filter(node => node.component.kind === "chapter");
    const bindContext = value => {
      const referenceMeta = {};
      const bindingByID = {};
      (value.bindings || []).forEach(binding => {
        if (binding.target_ref) referenceMeta[binding.target_ref] = binding;
        if (binding.binding_id) bindingByID[binding.binding_id] = binding;
      });
      context.referenceMeta = referenceMeta;
      context.bindingByID = bindingByID;
    };
    context = {...context, lazyObservers};
    bindContext(report);
    const chapterCache = new Map();
    let activeNode = null;
    let chapterLoadToken = 0;
    const rail = context.chapterRail;
    let selected = Math.max(roots.length - 1, 0);
    const railController = rail
      ? FTReportChapterRail.setup(rail, roots, context, {
        getSelected: () => selected,
        activate: index => activate(index),
      })
      : null;
    let draw = () => {
      mount.replaceChildren();
      const node = activeNode || roots[selected];
      if (!node) {
        mount.replaceChildren(FTUI.empty(context.t("本章节暂无内容"), ""));
        return;
      }
      if (chapterDescriptors.length && context.loadChapter && !activeNode) {
        mount.replaceChildren(FTUI.loading(context.t?.("正在读取章节…") || "正在读取章节…"));
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
    function activate(index, initial = false) {
      if (!Number.isInteger(index) || index < 0 || index >= roots.length) return;
      selected = index;
      activeNode = null;
      draw();
      if (!chapterDescriptors.length || !context.loadChapter) return;
      const chapterID = roots[index].component.component_id;
      const cached = chapterCache.get(chapterID);
      if (cached) {
        activeNode = cached.node;
        bindContext(cached.report);
        draw();
        return;
      }
      const token = ++chapterLoadToken;
      Promise.resolve(context.loadChapter(chapterID)).then(value => {
        if (token !== chapterLoadToken || selected !== index) return;
        const loaded = tree(value.components || [])
          .find(node => node.component.kind === "chapter");
        if (!loaded) throw new Error(context.t?.("章节内容为空") || "章节内容为空");
        chapterCache.set(chapterID, {report: value, node: loaded});
        bindContext(value);
        activeNode = loaded;
        draw();
        if (initial && index === roots.length - 1 && context.restoreScrollY == null) {
          requestAnimationFrame(() => window.scrollTo({top: document.body.scrollHeight}));
        }
      }).catch(error => {
        if (token !== chapterLoadToken || selected !== index) return;
        activeNode = {
          component: {kind: "chapter", title: roots[index].component.title},
          children: [],
          error,
        };
        draw();
        mount.append(FTUI.empty(context.t?.("章节读取失败") || "章节读取失败", error.message || ""));
      });
    }
    const originalDraw = draw;
    draw = () => { originalDraw(); railController?.refresh(); };
    draw();
    if (chapterDescriptors.length && context.loadChapter) activate(selected, true);
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
