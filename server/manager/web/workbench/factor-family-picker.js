(() => {
  function entries(options = {}) {
    const publicItems = (options.publicFamilies || []).map(item => normalize(
      item, "public", item.owner_ref || item.owner_alias || "",
    ));
    const localItems = (options.localFamilies || []).map(item => normalize(
      item, "local", options.ownerRef || item.owner_ref || "",
    ));
    const transientItems = (options.transientFamilies || []).map(item => ({
      ...item,
      key: item.key || `transient:${item.sourceID || item.family}`,
      sourceKind: "transient",
      family: item.family || item.sourceID || "",
      title: item.title || item.family || item.sourceID || "",
      description: item.description || "",
    }));
    return [...transientItems, ...publicItems, ...localItems]
      .filter(item => item.family);
  }

  function normalize(value, sourceKind, ownerRef) {
    const family = value.factor_family_alias || value.family_alias
      || value.family || value.name || "";
    const familyRef = value.family_ref || value.factor_family_ref || "";
    const formulaFingerprint = String(value.family_formula_fingerprint || "");
    const sourceIdentity = familyRef
      || [ownerRef, family, formulaFingerprint].join(":");
    return {
      ...value,
      key: `${sourceKind}:${sourceIdentity}`,
      sourceKind,
      family,
      familyRef,
      ownerRef,
      familyFormulaFingerprint: formulaFingerprint,
      title: family,
      description: value.chinese_name || value.title_zh || value.desc
        || value.description || "",
    };
  }

  function filter(items, query) {
    const needle = String(query || "").trim().toLocaleLowerCase();
    if (!needle) return [...(items || [])];
    return (items || []).filter(item => [
      item.family, item.title, item.description, item.ownerRef,
      item.owner_alias, item.profile_id, item.familyRef,
    ].some(value => String(value || "").toLocaleLowerCase().includes(needle)));
  }

  function familyFactors(family, factors) {
    const refs = new Set(family?.factor_refs || []);
    return (factors || []).filter(item => refs.has(item.factor_ref));
  }

  // The workbench uses FTMultiSelectFilter for rendering.  Keep this module
  // as a data-only catalog seam so formula identity normalization is shared.
  window.FTFactorFamilyPicker = Object.freeze({entries, familyFactors, filter});
})();
