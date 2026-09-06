(() => {
  let cache = null;
  let generation = 0;
  let accessKey = "";
  let libraryPromise = null;
  let setsPromise = null;
  let groupsPromise = null;

  function emptyCache() {
    return {
      factors: [], families: [], familyScopes: {}, principal: "", visitor: false,
      sets: [], setScopes: {}, groups: [],
      libraryLoaded: false, setsLoaded: false, groupsLoaded: false,
      pendingFactors: [],
    };
  }

  function ensureCache() {
    if (!cache) cache = emptyCache();
    return cache;
  }

  function reset() {
    generation += 1;
    cache = null;
    libraryPromise = null;
    setsPromise = null;
    groupsPromise = null;
  }

  function applyLibrary(library) {
    const value = library || {};
    const data = ensureCache();
    const factors = mergeFactors(
      Array.isArray(value.factors) ? value.factors : [],
      data.pendingFactors,
    );
    data.pendingFactors = [];
    // Mutate the shared cache object instead of replacing it.  List pages can
    // request the library and the set/group catalogs concurrently during a
    // route transition; replacing the object would let one in-flight loader
    // write into a detached cache and lose its result.
    Object.assign(data, {
      factors,
      families: Array.isArray(value.families) ? value.families : [],
      familyScopes: value.family_scopes || value.family_tabs || {},
      principal: String(value.principal || ""),
      visitor: Boolean(value.visitor),
      libraryLoaded: true,
    });
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

  function upsertFactor(value) {
    const data = ensureCache();
    const factor = value?.factor || value;
    if (!factorKey(factor)) return data;
    data.factors = mergeFactors(data.factors, [factor]);
    if (!data.libraryLoaded) data.pendingFactors = mergeFactors(
      data.pendingFactors, [factor],
    );
    return data;
  }

  function mergeLibraryResources(familyResource, factorResource) {
    const familyValue = familyResource || {};
    const factorValue = factorResource || {};
    const familyScopes = familyValue.family_scopes || familyValue.family_tabs || {};
    const factorScopes = factorValue.family_scopes || factorValue.family_tabs || {};
    const scopes = {};
    for (const key of new Set([
      ...Object.keys(familyScopes), ...Object.keys(factorScopes),
    ])) {
      const familyScope = familyScopes[key] || {};
      const factorScope = factorScopes[key] || {};
      scopes[key] = {
        ...familyScope,
        ...factorScope,
        families: Array.isArray(familyScope.families)
          ? familyScope.families : [],
        factors: Array.isArray(factorScope.factors)
          ? factorScope.factors : [],
      };
    }
    return {
      ...familyValue,
      ...factorValue,
      families: Array.isArray(familyValue.families) ? familyValue.families : [],
      factors: Array.isArray(factorValue.factors) ? factorValue.factors : [],
      family_scopes: scopes,
    };
  }

  async function loadLibrary(context, refresh = false) {
    const data = ensureCache();
    if (data.libraryLoaded) return data;
    if (!libraryPromise) {
      const suffix = refresh ? "?refresh=1" : "";
      const request = Promise.all([
        context.api(`/api/factor-library/families${suffix}`),
        context.api(`/api/factor-library/factors${suffix}`),
      ]).then(([families, factors]) => mergeLibraryResources(families, factors));
      const started = generation;
      libraryPromise = request
        .then(value => {
          if (started !== generation) throw new Error("因子目录已刷新，请重试");
          return applyLibrary(value);
        })
        .catch(error => {
          if (started === generation) libraryPromise = null;
          throw error;
        });
    }
    return libraryPromise;
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

  async function load(context, options = {}) {
    const refresh = options === true || options.refresh === true;
    const includeLibrary = options === true || options.library === true;
    const includeSets = options === true || options.sets === true;
    const includeGroups = options === true || options.groups === true;
    if (refresh && context.session) {
      await context.api("/api/catalog/refresh", {method: "POST"});
    }
    const key = `${globalThis.location?.origin || ""}:${context.session?.username || ""}:${context.session?.role || ""}`;
    if (refresh || key !== accessKey) {
      reset();
      accessKey = key;
    }
    let data = ensureCache();
    if (includeLibrary) data = await loadLibrary(context, refresh);
    if (includeSets) data = await loadSets(context);
    if (includeGroups) data = await loadGroups(context);
    return data;
  }

  function isCurrent(context) {
    return context.isRouteCurrent?.() !== false;
  }

  window.FTFactorCatalog = Object.freeze({
    load, isCurrent, upsertFactor,
  });
})();
