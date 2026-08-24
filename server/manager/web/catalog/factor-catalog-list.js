(() => {
  const catalog = () => window.FTFactorCatalog;

  async function list(context, page = "families", requestedScope = "public") {
    context.activeNav("factors");
    context.setHeading(context.t("因子库"), "FactorTester");
    context.toolbar.append(window.FTFactorList.headerTabs(context, page));
    context.content.replaceChildren(FTUI.loading(context.t("正在读取因子库…")));
    let data = await catalog().load(context, {
      library: page !== "sets", sets: page === "sets",
    });
    if (!catalog().isCurrent(context)) return;
    const root = document.createElement("div");
    root.className = "library-page";
    const familyScope = window.FTFactorList.normalizeFamilyScope(
      requestedScope, data.visitor,
    );
    if (page === "families") {
      root.append(window.FTFactorList.familyScopeTabs(
        context, familyScope, data.visitor,
      ));
    } else if (!data.visitor) {
      root.append(window.FTFactorList.subjectScopeTabs(
        context, page, familyScope,
      ));
    }
    const controls = document.createElement("div");
    controls.className = "factor-catalog-controls";
    const search = document.createElement("input");
    search.type = "search";
    search.className = "toolbar-search factor-catalog-search";
    search.placeholder = window.FTFactorList.searchPlaceholder(
      context, page, familyScope,
    );
    search.setAttribute("aria-label", search.placeholder);
    controls.append(searchControl(context, search));
    let groupLoad = null;
    const group = FTFactorGroupFilter.create(
      context, data.groups, ["*"], () => resetAndRender(), {
        onOpen: () => {
          if (data.groupsLoaded || groupLoad) return groupLoad;
          groupLoad = catalog().load(context, {
            groups: true, library: page !== "sets",
          }).then(next => {
            data = next;
            group.setItems(data.groups);
            if (catalog().isCurrent(context)) render();
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
        await catalog().load(context, {
          refresh: true,
          library: page !== "sets",
          sets: true,
          groups: true,
        });
        if (!catalog().isCurrent(context)) return;
        list(context, page, familyScope);
      }, context.t("刷新")),
    );
    let tablePage = 1;
    const render = () => window.FTFactorList.render(context, data, results, {
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
      : (data.familyScopes?.subordinates?.[
        page === "families" ? "families" : "factors"
      ] || []);
    const owners = new Map();
    values.forEach(item => {
      const username = String(item?.owner_username || "").trim();
      if (!username) return;
      owners.set(username, String(item?.owner_alias || username));
    });
    return FTMultiSelectFilter.create(context, {
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
  }

  window.FTFactorCatalogList = Object.freeze({list});
})();
