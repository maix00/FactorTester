(() => {
  let cache = null;
  let generation = 0;
  let accessKey = "";
  let familiesPromise = null;
  let factorsPromise = null;
  let setsPromise = null;
  let groupsPromise = null;

  function emptyCache() {
    return {
      factors: [], families: [], familyScopes: {}, principal: "", visitor: false,
      sets: [], setScopes: {}, groups: [],
      familiesLoaded: false, factorsLoaded: false, libraryLoaded: false,
      setsLoaded: false, groupsLoaded: false,
      pendingFactors: [], pendingFamilies: [],
    };
  }

  function ensureCache() {
    if (!cache) cache = emptyCache();
    return cache;
  }

  function reset() {
    generation += 1;
    cache = null;
    familiesPromise = null;
    factorsPromise = null;
    setsPromise = null;
    groupsPromise = null;
  }

  function mergeScopeResource(current, incoming, property) {
    const result = {};
    const existing = current || {};
    const update = incoming || {};
    for (const key of new Set([...Object.keys(existing), ...Object.keys(update)])) {
      const before = existing[key] || {};
      const next = update[key] || {};
      result[key] = {
        ...before,
        ...next,
        families: property === "families" && Array.isArray(next.families)
          ? next.families
          : Array.isArray(before.families) ? before.families : [],
        factors: property === "factors" && Array.isArray(next.factors)
          ? next.factors
          : Array.isArray(before.factors) ? before.factors : [],
      };
    }
    return result;
  }

  function applyMetadata(data, value) {
    if (value && value.principal !== undefined) {
      data.principal = String(value.principal || "");
    }
    if (value && value.visitor !== undefined) {
      data.visitor = Boolean(value.visitor);
    }
  }

  function applyFamilies(value) {
    const response = value || {};
    const data = ensureCache();
    const scopes = response.family_scopes || response.family_tabs || {};
    // Mutate the shared cache object. Other projections may be loading at the
    // same time and must merge into this object rather than a detached copy.
    data.families = mergeFamilies(
      Array.isArray(response.families) ? response.families : [],
      data.families,
      data.pendingFamilies,
    );
    data.pendingFamilies = [];
    data.familyScopes = mergeScopeResource(data.familyScopes, scopes, "families");
    applyMetadata(data, response);
    data.familiesLoaded = true;
    data.libraryLoaded = data.familiesLoaded && data.factorsLoaded;
    return data;
  }

  function applyFactors(value) {
    const response = value || {};
    const data = ensureCache();
    const scopes = response.family_scopes || response.family_tabs || {};
    data.factors = mergeFactors(
      Array.isArray(response.factors) ? response.factors : [],
      data.factors,
      data.pendingFactors,
    );
    data.pendingFactors = [];
    data.familyScopes = mergeScopeResource(data.familyScopes, scopes, "factors");
    applyMetadata(data, response);
    data.factorsLoaded = true;
    data.libraryLoaded = data.familiesLoaded && data.factorsLoaded;
    return data;
  }

  function factorKey(value) {
    return String(
      value?.ref || value?.factor_ref || value?.alias || value?.factor_alias || "",
    ).trim();
  }

  function mergeFactors(...lists) {
    const byKey = new Map();
    for (const list of lists) {
      for (const item of Array.isArray(list) ? list : []) {
        const key = factorKey(item);
        if (!key) continue;
        byKey.set(key, {...(byKey.get(key) || {}), ...item});
      }
    }
    return [...byKey.values()];
  }

  function familyKey(value) {
    return String(value?.family_ref || [
      value?.factor_family_alias || value?.factor_family_name || "",
      value?.family_formula_fingerprint || "",
      value?.factor_owner_ref || value?.owner_ref || value?.owner_username || "",
    ].join("\u0000")).trim();
  }

  function mergeFamilies(...lists) {
    const byKey = new Map();
    for (const list of lists) {
      for (const item of Array.isArray(list) ? list : []) {
        const key = familyKey(item);
        if (!key) continue;
        byKey.set(key, {...(byKey.get(key) || {}), ...item});
      }
    }
    return [...byKey.values()];
  }

  function upsertFactor(value) {
    const data = ensureCache();
    const factor = value?.factor || value;
    if (!factorKey(factor)) return data;
    data.factors = mergeFactors(data.factors, [factor]);
    if (!data.factorsLoaded) data.pendingFactors = mergeFactors(
      data.pendingFactors, [factor],
    );
    return data;
  }

  function upsertFamily(value) {
    const data = ensureCache();
    const family = value?.family || value;
    if (!familyKey(family)) return data;
    data.families = mergeFamilies(data.families, [family]);
    if (!data.familiesLoaded) {
      data.pendingFamilies = mergeFamilies(data.pendingFamilies, [family]);
    }
    return data;
  }

  async function loadFamilies(context, refresh = false) {
    const data = ensureCache();
    if (data.familiesLoaded) return data;
    if (!familiesPromise) {
      const suffix = refresh ? "?refresh=1" : "";
      const started = generation;
      familiesPromise = context.api(`/api/factor-library/families${suffix}`)
        .then(value => {
          if (started !== generation) throw new Error("因子目录已刷新，请重试");
          return applyFamilies(value);
        })
        .catch(error => {
          if (started === generation) familiesPromise = null;
          throw error;
        });
    }
    return familiesPromise;
  }

  async function loadFactors(context, refresh = false) {
    const data = ensureCache();
    if (data.factorsLoaded) return data;
    if (!factorsPromise) {
      const suffix = refresh ? "?refresh=1" : "";
      const started = generation;
      factorsPromise = context.api(`/api/factor-library/factors${suffix}`)
        .then(value => {
          if (started !== generation) throw new Error("因子目录已刷新，请重试");
          return applyFactors(value);
        })
        .catch(error => {
          if (started === generation) factorsPromise = null;
          throw error;
        });
    }
    return factorsPromise;
  }

  async function loadSets(context) {
    const data = ensureCache();
    if (data.setsLoaded) return data;
    if (!setsPromise) {
      const started = generation;
      setsPromise = context.api("/api/factor-library/factor-sets").then(sets => {
        if (started !== generation) throw new Error("因子目录已刷新，请重试");
        data.sets = Array.isArray(sets?.items) ? sets.items : [];
        data.setScopes = sets.item_scopes || {};
        data.setsLoaded = true;
        return data;
      }).catch(error => {
        if (started === generation) setsPromise = null;
        throw error;
      });
    }
    return setsPromise;
  }

  async function loadGroups(context) {
    const data = ensureCache();
    if (data.groupsLoaded) return data;
    if (!groupsPromise) {
      const started = generation;
      groupsPromise = context.api("/api/product-library/product-groups")
        .then(value => {
          if (started !== generation) throw new Error("因子目录已刷新，请重试");
          data.groups = Array.isArray(value?.groups) ? value.groups : [];
          data.groupsLoaded = true;
          return data;
        })
        .catch(error => {
          if (started === generation) groupsPromise = null;
          throw error;
        });
    }
    return groupsPromise;
  }

  function accessKeyFor(context) {
    const origin = globalThis.location?.origin || "";
    const username = context.session?.username || "";
    const role = context.session?.role || "";
    return `${origin}:${username}:${role}`;
  }

  function prepareAccess(context, refresh = false) {
    const key = accessKeyFor(context);
    if (refresh || key !== accessKey) {
      reset();
      accessKey = key;
    }
  }

  function peek(context) {
    prepareAccess(context);
    return ensureCache();
  }

  async function load(context, options = {}) {
    const refresh = options === true || options.refresh === true;
    const includeLibrary = options === true || options.library === true;
    const includeFamilies = includeLibrary || options.families === true;
    const includeFactors = includeLibrary || options.factors === true;
    const includeSets = options === true || options.sets === true;
    const includeGroups = options === true || options.groups === true;
    if (refresh && context.session && options.sync !== false) {
      await context.api("/api/catalog/refresh", {method: "POST"});
    }
    prepareAccess(context, refresh);
    await Promise.all([
      ...(includeFamilies ? [loadFamilies(context, refresh)] : []),
      ...(includeFactors ? [loadFactors(context, refresh)] : []),
      ...(includeSets ? [loadSets(context)] : []),
      ...(includeGroups ? [loadGroups(context)] : []),
    ]);
    return ensureCache();
  }

  function isCurrent(context) {
    return context.isRouteCurrent?.() !== false;
  }

  window.FTFactorCatalog = Object.freeze({
    load, peek, isCurrent, upsertFactor, upsertFamily,
  });
})();
