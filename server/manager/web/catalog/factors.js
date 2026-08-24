(() => {
  let cache = null;
  let libraryPromise = null;
  let setsPromise = null;
  let groupsPromise = null;

  function current(context) {
    return context.isRouteCurrent?.() !== false;
  }

  function emptyCache() {
    return {
      factors: [], families: [], familyScopes: {}, principal: "", visitor: false,
      sets: [], setScopes: {}, groups: [],
      setsLoaded: false, groupsLoaded: false,
    };
  }

  function applyLibrary(library) {
    const value = library || {};
    cache = {
      ...(cache || emptyCache()),
      factors: Array.isArray(value.factors) ? value.factors : [],
      families: Array.isArray(value.families) ? value.families : [],
      familyScopes: value.family_scopes || value.family_tabs || {},
      principal: String(value.principal || ""),
      visitor: Boolean(value.visitor),
    };
    return cache;
  }

  async function loadLibrary(context, refresh = false) {
    if (refresh) {
      cache = null;
      libraryPromise = null;
      setsPromise = null;
      groupsPromise = null;
    }
    if (cache && cache.libraryLoaded) return cache;
    if (!libraryPromise) {
      libraryPromise = context.api("/api/catalog/factors")
        .then(value => {
          const result = applyLibrary(value);
          result.libraryLoaded = true;
          return result;
        })
        .catch(error => {
          libraryPromise = null;
          throw error;
        });
    }
    return libraryPromise;
  }

  async function loadSets(context) {
    const data = await loadLibrary(context);
    if (data.setsLoaded) return data;
    if (!setsPromise) {
      setsPromise = Promise.allSettled([
        context.api("/api/catalog/factor-sets"),
        nativeRequest("catalog").catch(() => ({items: []})),
      ]).then(([setsResult, localSetsResult]) => {
        const sets = setsResult.status === "fulfilled" ? setsResult.value : {};
        const localSets = localSetsResult.status === "fulfilled"
          ? localSetsResult.value : {items: []};
        data.sets = FTFactorModel.mergeFactorSets(sets.items, localSets.items);
        data.setScopes = sets.item_scopes || {};
        data.setsLoaded = true;
        return data;
      }).catch(error => {
        setsPromise = null;
        throw error;
      });
    }
    return setsPromise;
  }

  async function loadGroups(context) {
    const data = await loadLibrary(context);
    if (data.groupsLoaded) return data;
    if (!groupsPromise) {
      groupsPromise = context.api("/api/catalog/product-groups")
        .then(value => {
          data.groups = Array.isArray(value?.groups) ? value.groups : [];
          data.groupsLoaded = true;
          return data;
        })
        .catch(error => {
          groupsPromise = null;
          throw error;
        });
    }
    return groupsPromise;
  }

  async function load(context, options = {}) {
    const refresh = options === true || options.refresh === true;
    const includeSets = options === true || options.sets === true;
    const includeGroups = options === true || options.groups === true;
    let data = await loadLibrary(context, refresh);
    if (includeSets) data = await loadSets(context);
    if (includeGroups) data = await loadGroups(context);
    return data;
  }

  async function list(context, page = "families", requestedScope = "public") {
    context.activeNav("factors");
    context.setHeading(context.t("因子库"), "FactorTester");
    context.toolbar.append(FTFactorList.headerTabs(context, page));
    context.content.replaceChildren(FTUI.loading(context.t("正在读取因子库…")));
    let data = await load(context, {sets: page === "sets"});
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
    let groupLoad = null;
    const group = FTFactorGroupFilter.create(
      context, data.groups, ["*"], () => resetAndRender(), {
        onOpen: () => {
          if (data.groupsLoaded || groupLoad) return groupLoad;
          groupLoad = load(context, {groups: true}).then(next => {
            data = next;
            group.setItems(data.groups);
            if (current(context)) render();
          }).catch(error => {
            groupLoad = null;
            context.showNotice?.(error.message || context.t("产品组读取失败"), true);
          });
          return groupLoad;
        },
      },
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
        await load(context, {refresh: true, sets: true, groups: true});
        if (!current(context)) return;
        list(context, page, familyScope);
      }, context.t("刷新")),
    );
    const canCreate = Boolean(context.session) && (
      page === "factors" && familyScope === "mine"
      || page === "families" && (
        familyScope === "mine"
        || familyScope === "public" && context.session.role === "super_admin"
      )
    );
    if (canCreate) {
      const label = page === "factors"
        ? context.t("新增因子") : context.t("新增因子家族");
      const publicMode = page === "families" && familyScope === "public"
        ? "&visibility=public" : "";
      const path = page === "factors"
        ? "/factors/factor/new?mode=create"
        : `/factors/family/new?mode=create${publicMode}`;
      context.toolbar.append(context.button(label, () => context.navigate(path),
        context.t("在独立标签页新建")));
    }
    let tablePage = 1;
    const render = () => FTFactorList.render(context, data, results, {
      page,
      scope: familyScope,
      query: search.value.trim().toLowerCase(),
      groupRefs: group.values,
      ownerUsernames: owner?.values ?? ["*"],
      tablePage,
      onPageChange: value => { tablePage = value; render(); },
      canModify: Boolean(context.session) && (
        page === "factors" && familyScope === "mine"
        || page === "families" && (
          familyScope === "mine"
          || familyScope === "public" && context.session.role === "super_admin"
        )
      ),
      onDelete: item => removeItem(context, page, familyScope, item),
    });
    function resetAndRender() { tablePage = 1; render(); }
    search.addEventListener("input", resetAndRender);
    render();
  }

  async function removeItem(context, page, scope, item) {
    const familyAlias = String(
      item?.factor_family_alias || item?.factor_family_name || "",
    ).trim();
    const label = String(
      page === "families" ? modelFamilyLabel(item) : item?.factor_alias || "",
    ).trim();
    if (!familyAlias || !window.confirm(
      context.t("确认删除“%@”？").replace("%@", label || familyAlias),
    )) return;
    const endpoint = page === "families"
      ? scope === "public"
        ? `/custom-factors/api/delete-public/${encodeURIComponent(familyAlias)}`
        : `/custom-factors/api/delete/${encodeURIComponent(familyAlias)}`
      : `/custom-factors/api/factor-library-configs/${encodeURIComponent(familyAlias)}`
        + `?factor_alias=${encodeURIComponent(item.factor_alias || "")}`
        + `&scope_key=${encodeURIComponent(item.scope_key || item.product_group || "default")}`;
    try {
      await context.api(endpoint, {
        method: page === "families" ? "POST" : "DELETE",
        ...(page === "families" ? {} : {body: JSON.stringify({})}),
      });
      context.showNotice?.(context.t("已删除"));
      await load(context, {refresh: true, sets: page === "sets", groups: true});
      if (current(context)) list(context, page, scope);
    } catch (error) {
      context.showNotice?.(error.message || context.t("删除失败"), true);
    }
  }

  function modelFamilyLabel(item) {
    return item?.factor_family_name || item?.factor_family_alias
      || item?.family_ref || "";
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
    let data = inline
      ? {factors: [context.testObjectInitialValue], families: []}
      : await load(context);
    if (!inline && mode === "view" && targetRef && !data.factors.some(item =>
      item.factor_ref === targetRef || item.factor_alias === targetRef
    )) {
      data = await load(context, {refresh: true});
    }
    if (!current(context)) return;
    return FTFactorDetails.factorDetail(context, data, targetRef, mode, nativeRequest);
  }

  async function familyDetail(context, targetRef, mode = "view", options = {}) {
    context.activeNav("factors");
    let data = await load(context);
    if (mode === "view" && targetRef && !data.families.some(item =>
      item.family_ref === targetRef || item.factor_family_alias === targetRef
    )) {
      data = await load(context, {refresh: true});
    }
    if (!current(context)) return;
    return FTFactorDetails.familyDetail(context, data, targetRef, mode, options);
  }

  async function setDetail(context, targetRef) {
    context.activeNav("factors");
    const inline = context.testObjectTemporary && context.testObjectInitialValue;
    const data = inline
      ? {sets: [context.testObjectInitialValue], factors: []}
      : await load(context, {sets: true});
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
