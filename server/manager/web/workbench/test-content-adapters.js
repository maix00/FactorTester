(() => {
  const candidateIndexes = new WeakMap();
  const directSourceIndexes = new WeakMap();
  const factorSetIndexes = new WeakMap();
  const referenceDigests = new WeakMap();

  function moduleReady(name) {
    return Boolean(window[name] || globalThis[name]);
  }

  const adapters = Object.freeze({
    settings: Object.freeze({}),
    test_templates: Object.freeze({
      lazyKey: "templates",
      ready: () => moduleReady("FTTestTemplates"),
      render: options => FTTestTemplates.panel(
        options.context,
        options.state.templates,
        options.state.kind,
        options.actions.templates,
      ),
    }),
    factor_selection: Object.freeze({
      lazyKey: "factors",
      ready: () => moduleReady("FTTestFactors"),
      render: options => FTTestFactors.panel(
        options.context, options.state, options.refresh,
        options.tab?.content_options || {},
      ),
    }),
    product_path_selection: Object.freeze({
      lazyKey: "products",
      ready: () => moduleReady("FTTestProducts"),
      render: options => FTTestProducts.panel(
        options.context, options.state, options.refresh,
      ),
    }),
    category_selection: Object.freeze({
      lazyKey: "categories",
      ready: () => moduleReady("FTTestCategories"),
      render: options => FTTestCategories.panel(
        options.context, options.state, options.refresh,
      ),
    }),
    run_inputs: Object.freeze({
      lazyKey: "run_inputs",
      ready: () => moduleReady("FTTestSourceUpload"),
      render: options => FTTestSourceUpload.dependencyPanel(
        options.context, options.state, options.refresh,
        options.tab?.content_options || {},
      ),
    }),
  });

  function name(tab) {
    return String(tab?.content_adapter || "settings");
  }

  function descriptor(tab) {
    return adapters[name(tab)] || null;
  }

  function hasContent(tab) {
    return typeof descriptor(tab)?.render === "function";
  }

  function supports(tab) {
    return Boolean(descriptor(tab));
  }

  function render(tab, options) {
    const adapter = descriptor(tab);
    if (!adapter) throw new Error(`未实现的测试内容适配器: ${name(tab)}`);
    return typeof adapter.render === "function" ? adapter.render(options) : null;
  }

  function lazyKey(tab) {
    return descriptor(tab)?.lazyKey || "";
  }

  function isReady(tab) {
    const adapter = descriptor(tab);
    return !adapter || typeof adapter.ready !== "function" || adapter.ready();
  }

  function chipSources(state, item = null) {
    const values = {};
    for (const chip of state.manifest?.chip_fields || []) {
      const source = sourceValues(chip.source_adapter, state, item);
      for (const key of chip.source_keys || []) values[key] = source[key];
      const detailSource = chip.detail_overlay?.source_key
        || chip.detail_overlay?.sourceKey;
      if (detailSource && Object.prototype.hasOwnProperty.call(source, detailSource)) {
        values[detailSource] = source[detailSource];
      }
    }
    return values;
  }

  function sourceValues(adapter, state, item = null) {
    if (adapter === "selected_factor_candidates") {
      const rawItemRefs = Array.isArray(item?.factor_candidate_refs)
        ? item.factor_candidate_refs : [];
      const itemRefs = rawItemRefs.map(String).filter(Boolean);
      const factors = itemRefs.length
        ? factorObjects(state, itemRefs)
        : factorCandidateObjects(state);
      const references = factors.map(factorReference).filter(Boolean);
      if (!references.length) return {};
      const directIndex = indexedValues(
        sourceList(state, "factor_source_selections"), directSourceIndexes,
        factorReference,
      );
      const directFactors = references.map(ref => directIndex.get(ref)).filter(Boolean)
        .map(value => ({
          target_ref: factorReference(value), label: factorLabel(value),
        }));
      const referencedSets = new Set(factors.flatMap(value => (
        Array.isArray(value?.factor_set_refs) ? value.factor_set_refs : []
      )).map(String).filter(Boolean));
      const setSources = sourceList(state, "factor_set_selections");
      const setIndex = indexedValues(
        setSources, factorSetIndexes, factorSetReference,
      );
      const factorSets = (item
        ? [...referencedSets].map(ref => setIndex.get(ref)).filter(Boolean)
        : setSources)
        .map(value => ({
          target_ref: factorSetReference(value),
          label: factorSetLabel(value),
        })).filter(value => value.target_ref);
      const soleSet = references.length > 1 && directFactors.length === 0
        && factorSets.length === 1
        && factors.every(value => (
          Array.isArray(value?.factor_set_refs)
          && value.factor_set_refs.map(String).includes(factorSets[0].target_ref)
        ))
        ? factorSets[0] : null;
      const candidateSet = {
        target_ref: `factor-candidates:${referenceDigest(
          references, rawItemRefs.length ? rawItemRefs : null,
        )}:${references.length}`,
        title_zh: `因子候选（${references.length}）`,
        related_references: factors.map(factor => ({
          target_ref: factorReference(factor),
          label: factorLabel(factor),
        })),
        source_factors: directFactors,
        source_factor_sets: factorSets,
        temporary: true,
        source_origin: "test_inline",
      };
      return {
        factorCandidateCount: references.length,
        factorCandidateLabel: references.length === 1
          ? factorLabel(factors[0])
          : soleSet?.label || `${references.length} 个`,
        factor_candidates: [candidateSet],
      };
    }
    if (adapter === "selected_factors") {
      const itemRefs = Array.isArray(item?.factor_candidate_refs)
        ? item.factor_candidate_refs.map(String).filter(Boolean) : [];
      const factors = itemRefs.length
        ? factorObjects(state, itemRefs)
        : selectedFactorObjects(state);
      return {
        factorRef: factors.map(factorReference).filter(Boolean),
        factorLabel: factors.map(factorLabel).filter(Boolean),
        factor: factors,
      };
    }
    if (adapter === "selected_product_paths") {
      const itemSelection = itemProductSelection(item);
      const projections = itemSelection
        ? [itemSelection]
        : window.FTTestProducts?.selectedProjections?.(state) || [];
      return {
        product_path_selection: projections,
        product_group: productObjects(state, item, projections),
      };
    }
    if (adapter === "selected_category") {
      const ref = String(item?.category || state.values?.category || "");
      const category = (state.values?.category_candidates || []).find(value => (
        String(value?.id || value?.name || value?.label || "") === ref
      ));
      return ref ? {
        category: [category || {id: ref, name: ref}],
        categoryLabel: category?.title_zh || category?.alias
          || category?.name || category?.label || ref,
      } : {};
    }
    if (adapter === "primary_strategy_group") {
      const group = item || state.analysis?.groups?.[0] || {};
      return {
        n_groups: group.splitCount,
        group_index: group.groupIndex,
        productMask: group.productMask || [],
      };
    }
    if (adapter === "run_inputs") {
      // The source-state module is intentionally deferred until the input
      // tab or a submission path is used.  Chips can still render a cheap
      // count from the lightweight state shape during route bootstrap.
      const counts = window.FTTestInputState?.counts?.(state) || {
        factors: (state.transientFactorSources || []).length,
        strategies: (state.transientStrategySources || []).length,
        dependencies: (state.runInputDependencies || []).length,
      };
      return counts.dependencies ? {run_input_count: counts.dependencies} : {};
    }
    return {};
  }

  function selectedFactorObjects(state) {
    if (!window.FTTestFactorSelection || !window.FTTestFactors) return [];
    return state.kind === "ic"
      ? FTTestFactorSelection.selectedFactors(state)
      : [FTTestFactors.selectedFactor(state)].filter(Boolean);
  }

  function factorCandidateObjects(state) {
    if (!window.FTTestFactorSelection) return [];
    return FTTestFactorSelection.candidates(state);
  }

  function indexedValues(values, cache, keyFor) {
    if (!Array.isArray(values)) return new Map();
    const prior = cache.get(values);
    if (prior?.length === values.length) return prior.index;
    const index = new Map();
    for (const value of values) {
      const key = keyFor(value);
      if (key) index.set(key, value);
    }
    cache.set(values, {length: values.length, index});
    return index;
  }

  function referenceDigest(references, cacheKey = null) {
    if (cacheKey) {
      const prior = referenceDigests.get(cacheKey);
      if (prior) return prior;
    }
    let hash = 0x811c9dc5;
    for (const reference of references) {
      for (let index = 0; index < reference.length; index += 1) {
        hash ^= reference.charCodeAt(index);
        hash = Math.imul(hash, 0x01000193);
      }
      hash ^= 0xff;
      hash = Math.imul(hash, 0x01000193);
    }
    const digest = (hash >>> 0).toString(16).padStart(8, "0");
    if (cacheKey) referenceDigests.set(cacheKey, digest);
    return digest;
  }

  function sourceList(state, key) {
    return Array.isArray(state.values?.[key]) ? state.values[key] : [];
  }

  function factorSetReference(value) {
    return typeof value === "string"
      ? value : String(value?.target_ref || value?.set_ref || value?.id || "").trim();
  }

  function factorSetLabel(value) {
    if (typeof value === "string") return value;
    return String(value?.title_zh || value?.set_id || value?.name
      || factorSetReference(value)).trim();
  }

  function factorReference(value) {
    if (typeof value === "string") return value;
    return String(value?.factor_ref || value?.target_ref || "").trim();
  }

  function factorLabel(value) {
    if (typeof value === "string") return value;
    return String(value?.factor_alias || value?.alias || value?.name
      || factorReference(value)).trim();
  }

  function factorObjects(state, refs) {
    const wanted = new Set(refs || []);
    const candidates = mergeFactorCatalogs(
      state.savedFactors,
      state.factors,
      state.analysis?.factors,
      state.values?.factor_candidates,
      window.FTTestFactorSelection?.candidates?.(state),
    );
    const matched = indexedValues(candidates, candidateIndexes, factorReference);
    // Strategy rows are rendered before the catalog is necessarily loaded.
    // Preserve their stable factor reference/alias so the detail overlay stays
    // clickable; the catalog detail view resolves the full object lazily.
    return [...wanted].map(ref => matched.get(ref) || {factor_ref: ref});
  }

  function mergeFactorCatalogs(...catalogs) {
    const values = new Map();
    for (const catalog of catalogs) {
      for (const value of Array.isArray(catalog) ? catalog : []) {
        const ref = factorReference(value);
        if (!ref) continue;
        const previous = values.get(ref);
        values.set(ref, previous && typeof previous === "object"
          && typeof value === "object" ? {...previous, ...value} : value);
      }
    }
    return [...values.values()];
  }

  function itemProductSelection(item) {
    if (!item) return null;
    return item.product_path_selection
      || item.product_group
      || item.productGroup
      || item.product_path_selection_id
      || item.product_group_ref
      || null;
  }

  function productObjects(state, item, projections) {
    const explicit = [
      item?.product_group,
      item?.productGroup,
      item?.product_path_selection_id,
      item?.product_group_ref,
    ].filter(Boolean);
    const catalog = Array.isArray(state.groups) ? state.groups : [];
    const index = state.productGroupIndex instanceof Map
      ? state.productGroupIndex
      : new Map(catalog.map(group => [productGroupID(group), group]));
    const values = [...explicit];
    for (const projection of projections || []) {
      const ref = productGroupID(projection);
      const match = index.get(ref);
      if (match) values.push(match);
      else if (ref) values.push(projection);
    }
    const seen = new Set();
    return values.map(value => {
      const ref = productGroupID(value);
      return index.get(ref) || value;
    }).filter(value => {
      const ref = productGroupID(value);
      if (!ref || seen.has(ref)) return false;
      seen.add(ref);
      return true;
    });
  }

  function productGroupID(value) {
    return typeof value === "string"
      ? value
      : value?.group_ref || value?.product_group_ref || value?.id
        || value?.product_group_template_id || value?.product_path_selection_id || "";
  }

  window.FTTestContentAdapters = Object.freeze({
    chipSources, hasContent, isReady, lazyKey, name, render, supports,
  });
})();
