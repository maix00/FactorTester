(() => {
  let cache = null;

  function current(context) {
    return context.isRouteCurrent?.() !== false;
  }

  async function load(context, refresh = false) {
    if (cache && !refresh) return cache;
    const [libraryResult, setsResult, groupsResult, localSetsResult] =
      await Promise.allSettled([
        context.api("/api/catalog/factors"),
        context.api("/api/catalog/factor-sets"),
        context.api("/api/catalog/product-groups"),
        nativeRequest("catalog").catch(() => ({items: []})),
      ]);
    if (libraryResult.status !== "fulfilled") throw libraryResult.reason;
    const library = libraryResult.value || {};
    const sets = setsResult.status === "fulfilled" ? setsResult.value : {};
    const groups = groupsResult.status === "fulfilled" ? groupsResult.value : {};
    const localSets = localSetsResult.status === "fulfilled"
      ? localSetsResult.value : {items: []};
    cache = {
      factors: Array.isArray(library.factors) ? library.factors : [],
      families: Array.isArray(library.families) ? library.families : [],
      familyScopes: library.family_scopes || library.family_tabs || {},
      principal: String(library.principal || ""),
      visitor: Boolean(library.visitor),
      sets: FTFactorModel.mergeFactorSets(sets.items, localSets.items),
      groups: Array.isArray(groups.groups) ? groups.groups : [],
    };
    return cache;
  }

  async function list(context, page = "families", requestedScope = "public") {
    context.activeNav("factors");
    context.setHeading(context.t("因子库"), "FactorTester");
    context.toolbar.append(FTFactorList.headerTabs(context, page));
    context.content.replaceChildren(FTUI.loading(context.t("正在读取因子库…")));
    const data = await load(context);
    if (!current(context)) return;
    const root = document.createElement("div");
    root.className = "library-page";
    const familyScope = FTFactorList.normalizeFamilyScope(
      requestedScope, data.visitor,
    );
    if (page === "families") {
      root.append(FTFactorList.familyScopeTabs(context, familyScope, data.visitor));
    }
    let group = null;
    if (page !== "families") {
      group = FTFactorGroupFilter.create(
        context, data.groups, "*", () => render(),
      );
      root.append(group.element);
    }
    const results = document.createElement("div");
    results.className = "library-results";
    root.append(results);
    context.content.replaceChildren(root);

    const search = document.createElement("input");
    search.className = "toolbar-search";
    search.placeholder = FTFactorList.searchPlaceholder(context, page);
    context.toolbar.append(
      search,
      context.button("↻", async () => {
        await load(context, true);
        if (!current(context)) return;
        list(context, page, familyScope);
      }, context.t("刷新")),
    );
    const render = () => FTFactorList.render(context, data, results, {
      page,
      scope: familyScope,
      query: search.value.trim().toLowerCase(),
      groupRef: group?.value ?? "*",
    });
    search.addEventListener("input", render);
    render();
  }

  async function factorDetail(context, targetRef) {
    context.activeNav("factors");
    const data = await load(context);
    if (!current(context)) return;
    return FTFactorDetails.factorDetail(context, data, targetRef, nativeRequest);
  }

  async function familyDetail(context, targetRef) {
    context.activeNav("factors");
    const data = await load(context);
    if (!current(context)) return;
    return FTFactorDetails.familyDetail(context, data, targetRef);
  }

  async function setDetail(context, targetRef) {
    context.activeNav("factors");
    const data = await load(context);
    if (!current(context)) return;
    return FTFactorDetails.setDetail(context, data, targetRef, nativeRequest);
  }

  async function nativeRequest(action, payload = {}) {
    const handler = window.webkit?.messageHandlers?.factorTesterLocalFactorSets;
    if (!handler?.postMessage) {
      if (action === "catalog") return {items: []};
      throw new Error("local factor catalog is unavailable");
    }
    const value = await handler.postMessage({action, ...payload});
    return value && typeof value === "object" ? value : {};
  }

  window.FTFactors = {factorDetail, familyDetail, list, setDetail};
})();
