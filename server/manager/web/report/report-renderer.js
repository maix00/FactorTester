(() => {
  const {renderBridgeGroup, componentView} = FTReportComponents;
  const {componentTree, chapterRoots} = FTReportTree;
  const DEFAULT_CHAPTER_CACHE_LIMIT = 3;

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
    const roots = chapterRoots(report);
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
    const chapterCacheLimit = Math.max(
      1,
      Number(context.chapterCacheLimit) || DEFAULT_CHAPTER_CACHE_LIMIT,
    );
    const chapterCache = FTReportChapterCache.create(chapterCacheLimit);
    let activeNode = null;
    let railController = null;
    let initialReadyNotified = false;
    const notifyInitialReady = () => {
      if (initialReadyNotified) return;
      initialReadyNotified = true;
      context.onInitialChapterReady?.();
    };
    let chapterLoadToken = 0;
    let chapterAbortController = null;
    const abortChapterLoad = () => {
      chapterAbortController?.abort();
      chapterAbortController = null;
    };
    const supportsAbortController = typeof AbortController === "function";
    const abortableLoad = (chapterID, token) => {
      const controller = supportsAbortController ? new AbortController() : null;
      chapterAbortController = controller;
      return Promise.resolve(context.loadChapter(
        chapterID,
        controller ? {signal: controller.signal} : {},
      )).finally(() => {
        if (token === chapterLoadToken && chapterAbortController === controller) {
          chapterAbortController = null;
        }
      });
    };
    const isAborted = error => Boolean(
      chapterAbortController?.signal?.aborted
      || error?.name === "AbortError"
    );
    const originalCleanup = mount.__ftLazyCleanup;
    mount.__ftLazyCleanup = () => {
      abortChapterLoad();
      chapterCache.clear();
      railController?.cleanup?.();
      originalCleanup?.();
    };
    const rail = context.chapterRail;
    const restoredChapterIndex = roots.findIndex(node =>
      node.component.component_id === context.selectedChapterID,
    );
    let selected = restoredChapterIndex >= 0
      ? restoredChapterIndex
      : Math.max(roots.length - 1, 0);
    railController = rail
      ? FTReportChapterRail.setup(rail, roots, context, {
        getSelected: () => selected,
        activate: index => activate(index),
      })
      : null;
    let draw = () => {
      // Invalidate observers and idle table chunks belonging to the chapter
      // that is about to leave the mount. Detached nodes must not continue
      // doing work after a chapter switch.
      FTReportLazyRuntime.reset(context);
      context.renderGeneration = Number(context.renderGeneration || 0) + 1;
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
      context.chapterID = node.component.component_id;
      const headingRow = document.createElement("div");
      headingRow.className = "chapter-heading-row";
      const heading = document.createElement("h2");
      heading.className = "chapter-title";
      heading.textContent = node.component.title || `${context.t?.("章节") || "章节"} ${selected + 1}`;
      const disclosure = document.createElement("button");
      disclosure.type = "button";
      disclosure.className = "chapter-disclosure-reset";
      disclosure.setAttribute("aria-expanded", "false");
      disclosure.title = context.t?.("展开或收起章节") || "展开或收起章节";
      disclosure.setAttribute("aria-label", disclosure.title);
      const ownedDetails = () => {
        const bridge = [...article.children].find(item =>
          item.classList?.contains?.("section-bridge")
          || String(item.className || "").split(/\s+/).includes("section-bridge"),
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
        return {firstLevel, ordinary};
      };
      const refreshDisclosure = () => {
        const {ordinary} = ownedDetails();
        disclosure.setAttribute("aria-expanded", String(
          ordinary.length > 0 && ordinary.every(item => item.open),
        ));
      };
      disclosure.addEventListener("click", event => {
        event.preventDefault();
        event.stopPropagation();
        // A chapter control only owns the chapter's direct children.  Do not
        // walk nested details: opening a chapter must not eagerly expand its
        // descendants or change a special subsection's lazy state.
        const {firstLevel, ordinary} = ownedDetails();
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
        disclosure.setAttribute("aria-expanded", String(shouldExpand));
        disclosure.setAttribute("aria-label", shouldExpand
          ? (context.t?.("收起章节") || "收起章节")
          : (context.t?.("展开章节") || "展开章节"));
      });
      headingRow.append(heading, disclosure);
      article.append(headingRow);
      if (node.children.length) article.append(renderBridgeGroup(node.children, context, 0));
      if (!node.children.length) article.append(FTUI.empty(context.t("本章节暂无内容"), ""));
      article.addEventListener("toggle", refreshDisclosure, true);
      refreshDisclosure();
      mount.append(article);
    };
    function activate(index, initial = false) {
      if (!Number.isInteger(index) || index < 0 || index >= roots.length) return;
      abortChapterLoad();
      selected = index;
      context.setSelectedChapter?.(roots[index]?.component?.component_id || "");
      activeNode = null;
      draw();
      if (!chapterDescriptors.length || !context.loadChapter) return;
      const chapterID = roots[index].component.component_id;
      const cached = chapterCache.get(chapterID);
      if (cached) {
        context.setChapterMetadata?.(cached.report);
        activeNode = cached.node;
        bindContext(cached.report);
        draw();
        if (initial) notifyInitialReady();
        return;
      }
      const token = ++chapterLoadToken;
      abortableLoad(chapterID, token).then(value => {
        if (token !== chapterLoadToken || selected !== index) return;
        const loaded = componentTree(value.components || [])
          .find(node => node.component.kind === "chapter");
        if (!loaded) throw new Error(context.t?.("章节内容为空") || "章节内容为空");
        chapterCache.set(chapterID, {report: value, node: loaded});
        bindContext(value);
        activeNode = loaded;
        draw();
        if (initial) notifyInitialReady();
        if (
          initial
          && index === roots.length - 1
          && context.restoreScrollY == null
          && !context.suppressAutoScroll
        ) {
          requestAnimationFrame(() => window.scrollTo({top: document.body.scrollHeight}));
        }
      }).catch(error => {
        if (isAborted(error)) return;
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
    else notifyInitialReady();
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
