(() => {
  function fieldDescriptor(state) {
    return Object.entries(state.manifest?.defaults || {}).find(([, field]) => (
      field?.serialization?.kind === "factor_set_selection_list"
    )) || null;
  }

  function storageKey(state) {
    const entry = fieldDescriptor(state);
    return entry ? FTSettingRules.storageKey(entry[0], entry[1]) : "";
  }

  function selections(state) {
    const key = storageKey(state);
    return key && Array.isArray(state.values?.[key]) ? state.values[key] : [];
  }

  function setSelections(state, values) {
    const entry = fieldDescriptor(state);
    if (!entry) return;
    FTSettingRules.setValue(state.manifest, state.values, entry[0], entry[1], values);
  }

  async function initialize(context, state) {
    if (!fieldDescriptor(state)) return;
    prepare(state);
    await loadCatalog(context, state);
  }

  // Keep the execution path usable before the factor-set tab is opened.  The
  // catalog is intentionally not fetched here; only the small in-memory
  // cache needed by a later submission is prepared.
  function prepare(state) {
    if (!fieldDescriptor(state)) return;
    const restored = Array.isArray(state.savedTemporaryObjects?.factor_sets)
      ? state.savedTemporaryObjects.factor_sets : [];
    state.factorSetCatalog = state.factorSetCatalog || {
      items: [...restored], busy: false, error: "", runInputs: new Map(),
    };
  }

  async function loadCatalog(context, state, query = "") {
    const entry = fieldDescriptor(state);
    if (!entry) return;
    const serialization = entry[1].serialization || {};
    state.factorSetCatalog.busy = true;
    state.factorSetCatalog.error = "";
    try {
      const server = await context.api(
        `${serialization.catalog_endpoint}?query=${encodeURIComponent(query)}`,
      );
      const byRef = new Map((state.factorSetCatalog.items || []).map(item => [
        item.target_ref, item,
      ]));
      for (const item of server.items || []) byRef.set(item.target_ref, item);
      state.factorSetCatalog.items = [...byRef.values()].filter(item => item.target_ref);
    } catch (error) {
      state.factorSetCatalog.error = error.message || String(error);
    } finally {
      state.factorSetCatalog.busy = false;
    }
  }

  function control(context, state, refresh) {
    if (!fieldDescriptor(state)) return null;
    const root = document.createElement("div");
    root.className = "test-factor-set-control";
    const items = (state.factorSetCatalog?.items || []).map(item => ({
      value: item.target_ref,
      label: item.title_zh || item.set_id || item.target_ref,
      description: item.description_zh
        || `${item.member_count || 0} ${context.t("个因子")} · ${context.t(
          item.visibility === "local" ? "本地" : "服务器",
        )}`,
      factorSet: item,
      view: window.FTFactorDetailShared?.factorSetRowView?.(item)
        || {kind: "factor_set", ref: item.target_ref},
    })).filter(item => item.value);
    const updateSelection = async values => {
      const requested = new Set(values);
      const current = selections(state);
      const removed = current.filter(item => !requested.has(item.target_ref));
      const added = items.filter(item => requested.has(item.value)
        && !current.some(value => value.target_ref === item.value));
      state.factorSetCatalog.busy = true;
      refresh?.();
      try {
        for (const item of removed) {
          FTTestFactorSelection.detachFactorSet(state, item.target_ref);
          FTTestInputState.detachFactorSet(state, item.target_ref);
          state.factorSetCatalog.runInputs.delete(item.target_ref);
        }
        setSelections(state, current.filter(item => requested.has(item.target_ref)));
        for (const item of added) {
          const source = state.factorSetCatalog.items.find(value => (
            value.target_ref === item.value
          ));
          if (source) await selectSet(context, state, source);
        }
      } catch (error) {
        state.factorSetCatalog.error = error.message || String(error);
      } finally {
        state.factorSetCatalog.busy = false;
        refresh?.();
      }
    };
    const picker = FTTestObjectPicker.create(context, {
      title: context.t("因子集合"),
      note: context.t("选择冻结集合并展开为具体因子候选"),
      className: "test-factor-set-picker",
      compact: true,
      name: "test-factor-sets",
      items,
      selected: selections(state).map(item => item.target_ref),
      loading: FTTestObjectPicker.lazyLoading(state, "factors") && !items.length,
      loadingText: context.t("正在读取因子集合…"),
      onCreate: context.session ? () => {
        void FTTestLazyCode.openObjectEditor(context, {
          kind: "factor_set",
          mode: "create",
          ref: "new",
          temporary: true,
          testState: state,
          onSaved: value => { void addInlineSet(context, state, value, refresh); },
        });
      } : null,
      createLabel: context.t("新建因子集合"),
      editSelected: item => item.factorSet?.temporary === true,
      onEdit: (_event, item) => {
        void FTTestLazyCode.openObjectEditor(context, {
          kind: "factor_set", mode: "edit",
          ref: item.factorSet.target_ref, initialValue: item.factorSet,
          temporary: true, testState: state,
          onSaved: value => { void addInlineSet(context, state, value, refresh); },
        });
      },
      editLabel: context.t("编辑因子集合"),
      onChange: values => { void updateSelection(values); },
    });
    root.append(picker.element);
    if (state.factorSetCatalog?.error) {
      const error = document.createElement("p");
      error.className = "form-error"; error.textContent = state.factorSetCatalog.error;
      root.append(error);
    }
    return root;
  }

  function panel(context, state, refresh) {
    const value = control(context, state, refresh);
    if (!value) return null;
    return FTTestFieldRow.create(
      context.t("因子集合"), value,
      window.FTTestFieldHelp?.forField?.(
        state.manifest, "factor_set_selections", context,
      ) || "",
    );
  }

  async function selectSet(context, state, item) {
    const members = await loadMembers(context, state, item);
    const priorRef = state.factorRef;
    const priorFactor = state.values.factor;
    for (const reference of members) {
      const factor = factorFromReference(reference, item.target_ref);
      if (!factor) throw new Error(context.t("因子集合包含无法解析的冻结因子"));
      // A factor set builds the outer candidate pool.  It must not turn the
      // last expanded member into a second manual selection; the scalar
      // primary factor is synchronized automatically by the shared selector.
      FTTestFactorSelection.addCandidate(state, factor, {select: false});
    }
    if (state.kind !== "ic" && priorRef) {
      state.factorRef = priorRef; state.values.factor = priorFactor;
    }
    setSelections(state, [...selections(state), summary(item)]);
  }

  async function addInlineSet(context, state, value, refresh) {
    if (!value?.target_ref || !value?.manifest) return;
    const item = {...value, visibility: "temporary", temporary: true};
    const index = state.factorSetCatalog.items.findIndex(candidate => (
      candidate.target_ref === item.target_ref
    ));
    if (index >= 0) state.factorSetCatalog.items[index] = item;
    else state.factorSetCatalog.items.push(item);
    await selectSet(context, state, item);
    refresh?.();
  }

  async function loadMembers(context, state, item) {
    if (item.temporary && Array.isArray(item.manifest?.identity?.members)) {
      return item.manifest.identity.members;
    }
    const serialization = fieldDescriptor(state)[1].serialization || {};
    const result = [];
    let offset = 0;
    for (let page = 0; page < 11; page += 1) {
      const payload = item.visibility === "local"
        ? await nativeRequest(serialization.native_detail_action, {
          target_ref: item.target_ref, offset, limit: 100,
        })
        : await context.api(
          `${serialization.detail_endpoint}?target_ref=${encodeURIComponent(item.target_ref)}`
          + `&offset=${offset}&limit=100`,
        );
      const value = payload.factor_set || payload;
      result.push(...(value.related_references || []));
      if (!value.has_more) return result;
      offset = Number(value.next_offset || result.length);
    }
    throw new Error(context.t("因子集合成员超过允许上限"));
  }

  function factorFromReference(reference, setRef) {
    const source = reference?.data || reference;
    const frozen = FTFactorModel.frozenFactorIdentity(source);
    if (!frozen) return null;
    return {
      ...source,
      factor_set_refs: [setRef],
      source_kind: "factor_set",
      factor_set_only: true,
    };
  }

  function summary(item) {
    return Object.fromEntries([
      "target_ref", "set_ref", "set_id", "title_zh", "description_zh",
      "member_fingerprint", "member_count", "visibility", "manifest",
      "temporary",
    ].map(key => [key, item[key]]).filter(([, value]) => value !== undefined));
  }

  async function descriptors(context, state, factors) {
    const selected = selections(state);
    if (!selected.length) return [];
    const values = [];
    for (const item of selected) values.push(await runInput(context, state, item));
    const declared = new Set(values.flatMap(value => (
      value.manifest.identity.members.map(member => member.alias)
    )).filter(Boolean));
    const executing = new Set((factors || []).map(FTTestFactorSelection.factorAlias).filter(Boolean));
    const missing = [...executing].filter(alias => !declared.has(alias));
    const extra = [...declared].filter(alias => !executing.has(alias));
    if (missing.length || extra.length) {
      throw new Error(context.t("因子集合成员与当前运行因子不一致，请调整因子选择或移除集合来源"));
    }
    return values;
  }

  async function runInput(context, state, item) {
    const cached = state.factorSetCatalog.runInputs.get(item.target_ref);
    if (cached) return cached.descriptor;
    const serialization = fieldDescriptor(state)[1].serialization || {};
    let bundle;
    if (item.temporary && item.manifest) {
      bundle = {descriptor: {target_ref: item.target_ref, manifest: item.manifest}};
      state.factorSetCatalog.runInputs.set(item.target_ref, bundle);
      return bundle.descriptor;
    }
    const payload = await context.api(
      `${serialization.descriptor_endpoint}?target_ref=${encodeURIComponent(item.target_ref)}`,
    );
    bundle = {descriptor: payload.descriptor || payload};
    state.factorSetCatalog.runInputs.set(item.target_ref, bundle);
    return bundle.descriptor;
  }

  window.FTTestFactorSets = Object.freeze({
    control, descriptors, initialize, panel, prepare, selections,
    selectSet, loadMembers, addInlineSet, setSelections, loadCatalog,
  });
})();
