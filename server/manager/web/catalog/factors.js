(() => {
  const catalog = () => window.FTFactorCatalog;

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
      && context.testObjectTemporary
      && context.testObjectInitialValue;
    let data = inline
      ? {factors: [context.testObjectInitialValue], families: []}
      : await catalog().load(context, {library: true});
    if (!inline && mode === "view" && targetRef && !data.factors.some(item =>
      item.factor_ref === targetRef || item.factor_alias === targetRef
    )) {
      data = await catalog().load(context, {refresh: true, library: true});
    }
    if (!catalog().isCurrent(context)) return;
    if (mode === "create" || mode === "edit") await ensureEditor();
    return FTFactorDetails.factorDetail(
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
    return FTFactorDetails.familyDetail(
      context, data, targetRef, mode, options,
    );
  }

  async function setDetail(context, targetRef) {
    context.activeNav("factors");
    const inline = context.testObjectTemporary && context.testObjectInitialValue;
    const data = inline
      ? {sets: [context.testObjectInitialValue], factors: []}
      : await catalog().load(context, {sets: true});
    if (!catalog().isCurrent(context)) return;
    return FTFactorDetails.setDetail(
      context, data, targetRef, catalog().nativeRequest,
    );
  }

  window.FTFactors = Object.freeze({factorDetail, familyDetail, setDetail});
})();
