(() => {
  const catalog = () => window.FTFactorCatalog;

  function factorMatches(item, targetRef) {
    const target = String(targetRef || "");
    return item?.ref === target || item?.factor_ref === target
      || item?.alias === target || item?.factor_alias === target;
  }

  async function ensureEditor() {
    if (window.FTFactorEditor?.render || !window.FTStaticLoader?.loadGroups) return;
    await window.FTStaticLoader.loadGroups(["factor-catalog-editor"]);
  }

  async function factorDetail(context, targetRef, mode = "view", options = {}) {
    context.activeNav("factors");
    // A factor created inline in the test editor already carries its complete
    // view model.  Do not make a catalog round-trip just to render that
    // temporary factor's read-only overlay.
    const inline = mode === "view"
      && (context.testObjectTemporary || context.testObjectSnapshot)
      && context.testObjectInitialValue;
    let data = inline
      ? {factors: [context.testObjectInitialValue], families: []}
      : await catalog().load(context, {library: true});
    if (!inline && mode === "view" && targetRef
        && !data.factors.some(item => factorMatches(item, targetRef))) {
      data = await catalog().load(context, {refresh: true, library: true});
    }
    if (!catalog().isCurrent(context)) return;
    if (mode === "create" || mode === "edit") await ensureEditor();
    return window.FTFactorDetails.factorDetail(
      context, data, targetRef, mode, catalog().nativeRequest, options,
    );
  }

  async function familyDetail(context, targetRef, mode = "view", options = {}) {
    context.activeNav("factors");
    let data = await catalog().load(context, {library: true});
    if (mode === "view" && targetRef && !data.families.some(item =>
      item.family_ref === targetRef || item.factor_family_alias === targetRef
    )) {
      data = await catalog().load(context, {refresh: true, library: true});
    }
    if (!catalog().isCurrent(context)) return;
    if (mode === "create" || mode === "edit") await ensureEditor();
    return window.FTFactorDetails.familyDetail(
      context, data, targetRef, mode, options,
    );
  }

  async function setDetail(context, targetRef, mode = "view", options = {}) {
    context.activeNav("factors");
    const inline = context.testObjectTemporary && context.testObjectInitialValue;
    let data = inline
      ? {sets: [context.testObjectInitialValue], factors: []}
      : await catalog().load(context, {
        sets: true, library: mode === "create" || mode === "edit",
      });
    if (!catalog().isCurrent(context)) return;
    if (mode === "create" || mode === "edit") {
      await ensureEditor();
      let initialValue = options.initialValue || context.testObjectInitialValue || null;
      if (mode === "edit" && !initialValue) {
        initialValue = await editableSet(context, data, targetRef);
      }
      return FTFactorSetEditor.render(
        context, data, targetRef, mode, {...options, initialValue},
      );
    }
    return window.FTFactorDetails.setDetail(
      context, data, targetRef, catalog().nativeRequest,
    );
  }

  async function editableSet(context, data, targetRef) {
    const selected = data.sets.find(item => (
      item.target_ref === targetRef || item.set_ref === targetRef
    ));
    if (!selected?.can_edit) {
      throw new Error(context.t("当前因子集合为只读，不能编辑"));
    }
    const related = [];
    let offset = 0;
    for (let page = 0; page < 11; page += 1) {
      const payload = await context.api(
        `/api/factor-library/factor-sets/detail?target_ref=${encodeURIComponent(targetRef)}`
        + `&offset=${offset}&limit=100`,
      );
      const value = payload.factor_set || payload;
      related.push(...(value.related_references || []));
      if (!value.has_more) return {...selected, ...value, related_references: related};
      offset = Number(value.next_offset || related.length);
    }
    throw new Error(context.t("因子集合成员超过允许上限"));
  }

  window.FTFactors = Object.freeze({factorDetail, familyDetail, setDetail});
})();
