(() => {
  function factorFamilyAlias(value) {
    return String(
      value?.factor_family_alias || value?.family_alias
      || value?.identity?.family_alias || value?.factor_family_name || "",
    ).trim();
  }

  function factorFamilyFingerprint(value) {
    return String(
      value?.family_formula_fingerprint
      || value?.identity?.family_formula_fingerprint || "",
    ).trim();
  }

  function factorFamilyRef(value) {
    return String(
      value?.family_ref || value?.identity?.family_ref || "",
    ).trim();
  }

  function factorFamilyForFactor(data, factor) {
    const alias = factorFamilyAlias(factor);
    const ref = factorFamilyRef(factor);
    const fingerprint = factorFamilyFingerprint(factor);
    const owner = String(
      factor?.owner_username || factor?.owner_ref || factor?.factor_owner_ref || "",
    ).trim();
    const candidates = (data?.families || []).filter(item => (
      Boolean(alias && factorFamilyAlias(item) === alias)
    ));
    return candidates.sort((left, right) => {
      const score = item => (
        (ref && factorFamilyRef(item) === ref ? 100 : 0)
        + (fingerprint && factorFamilyFingerprint(item) === fingerprint ? 30 : 0)
        + (owner && [item.owner_username, item.owner_ref, item.factor_owner_ref]
          .map(value => String(value || "").trim()).includes(owner) ? 10 : 0)
        + (String(item.factor_kind || item.source || "")
          === String(factor.factor_kind || factor.source || "") ? 2 : 0)
      );
      return score(right) - score(left);
    })[0] || null;
  }

  function enrichFactorWithFamily(factor, family) {
    if (!family) return factor;
    const shared = window.FTFactorDetailShared;
    const familyRows = shared.parameterRows(family);
    const factorRows = shared.parameterRows(factor, {family});
    const factorByAlias = new Map(factorRows.map(row => [row.alias, row]));
    const definitions = familyRows.length
      ? familyRows.map(row => {
        const selected = factorByAlias.get(row.alias);
        return {
          ...row,
          value: selected?.value ?? row.value,
          nested_factor: selected?.nested_factor || row.nested_factor || null,
        };
      })
      : factorRows;
    const merged = {...family, ...factor};
    if (!merged.factor_family_alias) {
      merged.factor_family_alias = factorFamilyAlias(family);
    }
    if (!merged.math_expr) {
      merged.math_expr = family.math_expr || family.formula || family.latex || "";
    }
    if (definitions.length) merged.parameter_definitions = definitions;
    if (familyRows.length) merged.family_parameter_definitions = familyRows;
    return merged;
  }

  function enrichFactorForDisplay(data, factor, seen = new Set()) {
    const identity = String(
      factor?.ref || factor?.factor_ref || factor?.alias || factor?.factor_alias || "",
    );
    if (identity && seen.has(identity)) return factor;
    const nextSeen = new Set(seen);
    if (identity) nextSeen.add(identity);
    const merged = enrichFactorWithFamily(factor, factorFamilyForFactor(data, factor));
    const shared = window.FTFactorDetailShared;
    const rows = shared.parameterRows(merged);
    const nestedRows = rows.map(row => row.nested_factor
      ? {
        ...row,
        nested_factor: enrichFactorForDisplay(data, row.nested_factor, nextSeen),
      }
      : row);
    return nestedRows.some((row, index) => row !== rows[index])
      ? {...merged, parameter_definitions: nestedRows}
      : merged;
  }

  window.FTFactorDisplayEnrichment = Object.freeze({
    factorFamilyAlias,
    factorFamilyFingerprint,
    factorFamilyRef,
    factorFamilyForFactor,
    enrichFactorWithFamily,
    enrichFactorForDisplay,
  });
})();
