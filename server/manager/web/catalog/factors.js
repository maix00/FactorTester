(() => {
  const catalog = () => window.FTFactorCatalog;

  async function ensureEditor() {
    if (window.FTFactorEditor?.render || !window.FTStaticLoader?.loadGroups) return;
    await window.FTStaticLoader.loadGroups(["factor-catalog-editor"]);
  }

  async function factorDetail(context, targetRef, mode = "view") {
    context.activeNav("factors");
    // A factor created inline in the test editor already carries its complete
    // view model.  Do not make a catalog round-trip just to render that
    // temporary factor's read-only overlay.
    const inline = mode === "view"
      && context.testObjectTemporary
      && context.testObjectInitialValue;
    const data = inline
      ? {factors: [context.testObjectInitialValue], families: []}
      : await catalog().load(context, {library: true});
    if (!catalog().isCurrent(context)) return;
    if (mode === "create" || mode === "edit") await ensureEditor();
    return FTFactorDetails.factorDetail(
      context, data, targetRef, mode, catalog().nativeRequest,
    );
  }

  async function familyDetail(context, targetRef) {
    context.activeNav("factors");
    const data = await catalog().load(context, {library: true});
    if (!catalog().isCurrent(context)) return;
    return FTFactorDetails.familyDetail(context, data, targetRef);
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
