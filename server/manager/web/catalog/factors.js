(() => {
  const catalog = () => window.FTFactorCatalog;

  function factorMatches(item, targetRef) {
    const target = String(targetRef || "");
    return item?.ref === target || item?.factor_ref === target
      || item?.alias === target || item?.factor_alias === target;
  }

  function cachedRows(cache, resource) {
    const scoped = Object.values(cache.familyScopes || {}).flatMap(scope => (
      Array.isArray(scope?.[resource]) ? scope[resource] : []
    ));
    return [...(cache[resource] || []), ...scoped];
  }

  function familyForFactor(families, factor) {
    return families.find(item => (
      (item.factor_family_alias || item.factor_family_name)
        === factor.factor_family_alias
      && item.family_formula_fingerprint === factor.family_formula_fingerprint
      && (item.factor_owner_ref || item.owner_ref || item.owner_username)
        === (factor.factor_owner_ref || factor.owner_username)
    ));
  }

  function openReactEditor(context, section, targetRef, mode) {
    const query = new URLSearchParams({page: "factors", section, mode});
    if (targetRef) query.set("object_ref", targetRef);
    const owner = new URLSearchParams(globalThis.location.search).get("owner_username");
    if (owner) query.set("owner_username", owner);
    globalThis.location.assign(`/app?${query}`);
  }

  async function factorDetail(context, targetRef, mode = "view", options = {}) {
    if (mode === "create" || mode === "edit") return openReactEditor(context, "factors", targetRef, mode);
    context.activeNav("factors");
    // A factor created inline in the test editor already carries its complete
    // view model.  Do not make a catalog round-trip just to render that
    // temporary factor's read-only overlay.
    const inline = mode === "view"
      && (context.testObjectTemporary || context.testObjectSnapshot)
      && context.testObjectInitialValue;
    const historyQuery = new URLSearchParams(window.location.search);
    const historySet = mode === "view" && historyQuery.get("history_set");
    if (historySet) {
      const query = new URLSearchParams({target_ref: historySet, factor_ref: targetRef,
        owner_username: historyQuery.get("set_owner") || ""});
      const payload = await context.api(`/api/factor-library/factor-sets/history-factor?${query}`);
      if (!catalog().isCurrent(context)) return;
      return window.FTFactorDetails.factorDetail(context,
        {factors: [payload.factor], families: []}, targetRef, mode, catalog().nativeRequest, options);
    }
    let data;
    const canonicalFactorRef = /^factor:v2:[A-Za-z0-9_-]{43}$/.test(String(targetRef || ""));
    if (inline) {
      data = {factors: [context.testObjectInitialValue], families: []};
    } else if (mode === "view" && canonicalFactorRef) {
      const query = new URLSearchParams({factor_ref: String(targetRef)});
      const location = globalThis.location || window.location;
      const owner = new URLSearchParams(location?.search || "").get("owner_username") || "";
      if (owner) query.set("owner_username", owner);
      // Factor refs are immutable and indexed in the local account mirror.
      // Fetch only this row; preserve a matching family already cached by a
      // catalog screen without causing that catalog to load on cold details.
      const cached = catalog().peek(context);
      const cachedFactors = cachedRows(cached, "factors");
      const cachedFamilies = cachedRows(cached, "families");
      const cachedFactor = owner
        ? cachedFactors.find(item => factorMatches(item, targetRef)
          && String(item.owner_username || "") === owner)
        : null;
      const cachedFamily = cachedFactor
        && familyForFactor(cachedFamilies, cachedFactor);
      if (cachedFactor && cachedFamily) {
        data = {factors: [cachedFactor], families: [cachedFamily]};
      } else {
        try {
          const payload = await context.api(
            `/api/factor-library/factors/detail?${query}`,
          );
          if (!payload?.factor) {
            throw new Error(context.t("因子不存在或当前端口无法解析该引用"));
          }
          catalog().upsertFactor(payload.factor);
          if (payload.family) catalog().upsertFamily(payload.family);
          const family = payload.family
            || familyForFactor(cachedFamilies, payload.factor);
          data = {factors: [payload.factor], families: family ? [family] : []};
        } catch (error) {
          if (error?.status === 404) {
            throw new Error(context.t("因子不存在、已删除或尚未同步到当前服务器"));
          }
          throw error;
        }
      }
    } else {
      data = await catalog().load(context, {library: true});
      if (mode === "view" && targetRef
          && !data.factors.some(item => factorMatches(item, targetRef))) {
        data = await catalog().load(context, {refresh: true, library: true});
      }
    }
    if (!catalog().isCurrent(context)) return;
    return window.FTFactorDetails.factorDetail(
      context, data, targetRef, mode, catalog().nativeRequest, options,
    );
  }

  async function familyDetail(context, targetRef, mode = "view", options = {}) {
    if (mode === "create" || mode === "edit") return openReactEditor(context, "families", targetRef, mode);
    context.activeNav("factors");
    // A factor family created inline in the test editor already carries its
    // complete view model; render it read-only without a catalog round-trip.
    const inline = mode === "view"
      && (context.testObjectTemporary || context.testObjectSnapshot)
      && context.testObjectInitialValue;
    let data = inline
      ? {families: [context.testObjectInitialValue]}
      : await catalog().load(context, mode === "view"
        ? {families: true}
        : {library: true});
    if (!inline && mode === "view" && targetRef && !data.families.some(item =>
      item.family_ref === targetRef || item.factor_family_alias === targetRef
    )) {
      data = await catalog().load(context, {refresh: true, library: true});
    }
    if (!catalog().isCurrent(context)) return;
    return window.FTFactorDetails.familyDetail(
      context, data, targetRef, mode, options,
    );
  }

  function setDetail(_context, targetRef, mode = "view") {
    const query = new URLSearchParams({page: "factors", section: "sets"});
    if (targetRef) query.set("object_ref", targetRef);
    if (["create", "edit"].includes(mode)) query.set("mode", mode);
    window.location.assign(`/app?${query}`);
  }

  window.FTFactors = Object.freeze({factorDetail, familyDetail, setDetail});
})();
