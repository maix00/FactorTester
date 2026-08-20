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
      setScopes: sets.item_scopes || {},
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
    } else if (!data.visitor) {
      root.append(FTFactorList.subjectScopeTabs(context, page, familyScope));
    }
    const controls = document.createElement("div");
    controls.className = "factor-catalog-controls";
    const search = document.createElement("input");
    search.type = "search";
    search.className = "toolbar-search factor-catalog-search";
    search.placeholder = FTFactorList.searchPlaceholder(context, page, familyScope);
    search.setAttribute("aria-label", search.placeholder);
    controls.append(searchControl(context, search));
    const group = FTFactorGroupFilter.create(
      context, data.groups, ["*"], () => resetAndRender(),
    );
    controls.append(group.element);
    const owner = familyScope === "subordinates"
      ? subordinateFilter(context, data, page, () => resetAndRender()) : null;
    if (owner) controls.append(owner.element);
    root.append(controls);
    const results = document.createElement("div");
    results.className = "library-results";
    root.append(results);
    context.content.replaceChildren(root);

    context.toolbar.append(
      context.button("↻", async () => {
        await load(context, true);
        if (!current(context)) return;
        list(context, page, familyScope);
      }, context.t("刷新")),
    );
    let tablePage = 1;
    const render = () => FTFactorList.render(context, data, results, {
      page,
      scope: familyScope,
      query: search.value.trim().toLowerCase(),
      groupRefs: group.values,
      ownerUsernames: owner?.values ?? ["*"],
      tablePage,
      onPageChange: value => { tablePage = value; render(); },
    });
    function resetAndRender() { tablePage = 1; render(); }
    search.addEventListener("input", resetAndRender);
    render();
  }

  function searchControl(context, search) {
    const section = document.createElement("section");
    section.className = "ft-multi-select-filter factor-catalog-search-control";
    const heading = document.createElement("div");
    heading.className = "ft-multi-select-heading";
    const title = document.createElement("h2");
    title.textContent = context.t("搜索");
    heading.append(title);
    section.append(heading, search);
    return section;
  }

  function subordinateFilter(context, data, page, onChange) {
    const values = page === "sets"
      ? (data.setScopes?.subordinates || [])
      : (data.familyScopes?.subordinates?.[page === "families" ? "families" : "factors"] || []);
    const owners = new Map();
    values.forEach(item => {
      const username = String(item?.owner_username || "").trim();
      if (!username) return;
      owners.set(username, String(item?.owner_alias || username));
    });
    const filter = FTMultiSelectFilter.create(context, {
      title: context.t("按下级用户筛选"),
      className: "factor-subordinate-filter",
      menuClass: "factor-subordinate-filter-menu",
      searchPlaceholder: context.t("搜索下级用户"),
      items: [
        {value: "*", label: context.t("全部下级用户"), exclusive: true},
        ...[...owners].map(([value, label]) => ({value, label, description: value})),
      ],
      selected: ["*"],
      onChange,
    });
    return filter;
  }

  async function factorDetail(context, targetRef, mode = "view") {
    context.activeNav("factors");
    // A factor created inline in the test editor already carries its complete
    // view model.  Do not make a catalog round-trip (or fail on an unavailable
    // catalog service) just to render that temporary factor's read-only
    // overlay.  Normal catalog factors keep the existing lazy catalog path.
    const inline = mode === "view"
      && context.testObjectTemporary
      && context.testObjectInitialValue;
    const data = inline
      ? {factors: [context.testObjectInitialValue], families: []}
      : await load(context);
    if (!current(context)) return;
    return FTFactorDetails.factorDetail(context, data, targetRef, mode, nativeRequest);
  }

  async function familyDetail(context, targetRef) {
    context.activeNav("factors");
    const data = await load(context);
    if (!current(context)) return;
    return FTFactorDetails.familyDetail(context, data, targetRef);
  }

  async function setDetail(context, targetRef) {
    context.activeNav("factors");
    const inline = context.testObjectTemporary && context.testObjectInitialValue;
    const data = inline
      ? {sets: [context.testObjectInitialValue], factors: []}
      : await load(context);
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
