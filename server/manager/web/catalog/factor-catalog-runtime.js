(() => {
  let cache = null;
  let libraryPromise = null;
  let setsPromise = null;
  let groupsPromise = null;

  function emptyCache() {
    return {
      factors: [], families: [], familyScopes: {}, principal: "", visitor: false,
      sets: [], setScopes: {}, groups: [],
      libraryLoaded: false, setsLoaded: false, groupsLoaded: false,
    };
  }

  function ensureCache() {
    if (!cache) cache = emptyCache();
    return cache;
  }

  function reset() {
    cache = null;
    libraryPromise = null;
    setsPromise = null;
    groupsPromise = null;
  }

  function applyLibrary(library) {
    const value = library || {};
    const data = ensureCache();
    // Mutate the shared cache object instead of replacing it.  List pages can
    // request the library and the set/group catalogs concurrently during a
    // route transition; replacing the object would let one in-flight loader
    // write into a detached cache and lose its result.
    Object.assign(data, {
      factors: Array.isArray(value.factors) ? value.factors : [],
      families: Array.isArray(value.families) ? value.families : [],
      familyScopes: value.family_scopes || value.family_tabs || {},
      principal: String(value.principal || ""),
      visitor: Boolean(value.visitor),
      libraryLoaded: true,
    });
    return data;
  }

  async function loadLibrary(context) {
    const data = ensureCache();
    if (data.libraryLoaded) return data;
    if (!libraryPromise) {
      libraryPromise = context.api("/api/catalog/factors")
        .then(applyLibrary)
        .catch(error => {
          libraryPromise = null;
          throw error;
        });
    }
    return libraryPromise;
  }

  async function loadSets(context) {
    const data = ensureCache();
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
    const data = ensureCache();
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
    const includeLibrary = options === true || options.library === true;
    const includeSets = options === true || options.sets === true;
    const includeGroups = options === true || options.groups === true;
    if (refresh) reset();
    let data = ensureCache();
    if (includeLibrary) data = await loadLibrary(context);
    if (includeSets) data = await loadSets(context);
    if (includeGroups) data = await loadGroups(context);
    return data;
  }

  function isCurrent(context) {
    return context.isRouteCurrent?.() !== false;
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

  window.FTFactorCatalog = Object.freeze({load, isCurrent, nativeRequest});
})();
