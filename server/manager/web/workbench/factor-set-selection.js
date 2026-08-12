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
    state.factorSetCatalog = state.factorSetCatalog || {
      items: [], busy: false, error: "", runInputs: new Map(),
    };
    await loadCatalog(context, state);
  }

  async function loadCatalog(context, state, query = "") {
    const entry = fieldDescriptor(state);
    if (!entry) return;
    const serialization = entry[1].serialization || {};
    state.factorSetCatalog.busy = true;
    state.factorSetCatalog.error = "";
    try {
      const serverRequest = context.api(
        `${serialization.catalog_endpoint}?query=${encodeURIComponent(query)}`,
      );
      const localRequest = nativeHandler()
        ? nativeRequest(serialization.native_catalog_action, {query})
        : Promise.resolve({items: []});
      const [server, local] = await Promise.all([serverRequest, localRequest]);
      state.factorSetCatalog.items = FTFactorModel.mergeFactorSets(
        server.items || [], local.items || [],
      ).filter(item => item.target_ref);
    } catch (error) {
      state.factorSetCatalog.error = error.message || String(error);
    } finally {
      state.factorSetCatalog.busy = false;
    }
  }

  function panel(context, state, refresh) {
    if (!fieldDescriptor(state)) return null;
    const root = document.createElement("section");
    root.className = "test-factor-set-panel";
    const heading = document.createElement("div");
    const copy = document.createElement("span");
    const title = document.createElement("b"); title.textContent = context.t("因子集合");
    const help = document.createElement("small");
    help.textContent = context.t("选择冻结集合并展开为具体因子候选");
    copy.append(title, help);
    const choose = context.button(context.t("选择因子集合"), () => (
      openPicker(context, state, refresh)
    ));
    heading.append(copy, choose); root.append(heading);
    const selected = selections(state);
    if (selected.length) root.append(selectedList(context, state, selected, refresh));
    if (state.factorSetCatalog?.error) {
      const error = document.createElement("p");
      error.className = "form-error"; error.textContent = state.factorSetCatalog.error;
      root.append(error);
    }
    return root;
  }

  function selectedList(context, state, values, refresh) {
    const list = document.createElement("div");
    list.className = "test-factor-set-selected";
    for (const value of values) {
      const row = document.createElement("div");
      const copy = document.createElement("span");
      const name = document.createElement("b");
      name.textContent = value.title_zh || value.set_id || value.target_ref;
      const note = document.createElement("small");
      note.textContent = `${Number(value.member_count || 0)} ${context.t("个因子")}`;
      copy.append(name, note);
      const remove = context.button(context.t("移除"), () => {
        FTTestFactorSelection.detachFactorSet(state, value.target_ref);
        FTTestInputState.detachFactorSet(state, value.target_ref);
        state.factorSetCatalog.runInputs.delete(value.target_ref);
        setSelections(state, selections(state).filter(item => (
          item.target_ref !== value.target_ref
        )));
        refresh();
      });
      row.append(copy, remove); list.append(row);
    }
    return list;
  }

  function openPicker(context, state, refresh) {
    const dialog = document.createElement("dialog");
    dialog.className = "factor-family-picker-dialog";
    const card = document.createElement("section");
    card.className = "dialog-card wide factor-family-picker";
    const title = document.createElement("h2"); title.textContent = context.t("选择因子集合");
    const search = document.createElement("input");
    search.type = "search"; search.placeholder = context.t("搜索集合名称或说明");
    const list = document.createElement("div"); list.className = "factor-family-picker-list";
    const render = () => renderRows(context, state, list, search.value, dialog, refresh);
    search.addEventListener("input", render);
    const actions = document.createElement("div"); actions.className = "dialog-actions";
    actions.append(FTUI.actionButton(context.t("取消"), () => dialog.close(), {
      variant: "secondary",
    }));
    card.append(title, search, list, actions); dialog.append(card);
    dialog.addEventListener("close", () => dialog.remove(), {once: true});
    document.body.append(dialog); dialog.showModal(); render(); search.focus();
  }

  function renderRows(context, state, mount, query, dialog, refresh) {
    const needle = String(query || "").trim().toLocaleLowerCase();
    const selected = new Set(selections(state).map(item => item.target_ref));
    const items = (state.factorSetCatalog?.items || []).filter(item => (
      !needle || JSON.stringify(item).toLocaleLowerCase().includes(needle)
    ));
    if (!items.length) {
      mount.replaceChildren(FTUI.empty(context.t("没有匹配的因子集合"), ""));
      return;
    }
    const fragment = document.createDocumentFragment();
    for (const item of items) {
      const row = document.createElement("button"); row.type = "button";
      row.className = `factor-family-picker-row${selected.has(item.target_ref) ? " selected" : ""}`;
      const copy = document.createElement("span");
      const name = document.createElement("b");
      name.textContent = item.title_zh || item.set_id || item.target_ref;
      const note = document.createElement("small");
      note.textContent = item.description_zh || `${item.member_count || 0} ${context.t("个因子")}`;
      const source = document.createElement("span"); source.className = "factor-family-source";
      source.textContent = context.t(item.visibility === "local" ? "本地" : "服务器");
      copy.append(name, note); row.append(copy, source);
      row.addEventListener("click", async () => {
        if (!selected.has(item.target_ref)) await selectSet(context, state, item);
        dialog.close(); refresh();
      });
      fragment.append(row);
    }
    mount.replaceChildren(fragment);
  }

  async function selectSet(context, state, item) {
    state.factorSetCatalog.busy = true;
    try {
      const members = await loadMembers(context, state, item);
      const priorRef = state.factorRef;
      const priorFactor = state.values.factor;
      for (const reference of members) {
        const factor = factorFromReference(reference, item.target_ref);
        if (!factor) throw new Error(context.t("因子集合包含无法解析的冻结因子"));
        FTTestFactorSelection.addCandidate(state, factor);
      }
      if (state.kind !== "ic" && priorRef) {
        state.factorRef = priorRef; state.values.factor = priorFactor;
      }
      setSelections(state, [...selections(state), summary(item)]);
    } finally {
      state.factorSetCatalog.busy = false;
    }
  }

  async function loadMembers(context, state, item) {
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
    const target = reference?.target_ref || reference;
    const decoded = FTFactorModel.decodeFrozenFactorRef(target);
    if (!decoded) return null;
    return {
      factor_ref: target, target_ref: target,
      factor_alias: decoded.alias, alias: decoded.alias,
      factor_family_alias: decoded.family, family: decoded.family,
      owner_ref: decoded.ownerRef, git_commit: decoded.gitCommit,
      git_blob: decoded.gitBlob, relative_path: decoded.relativePath,
      params: Object.fromEntries(decoded.params.map(item => [item.alias, item.value])),
      factor_set_refs: [setRef],
      source_kind: "factor_set",
      factor_set_only: true,
    };
  }

  function summary(item) {
    return Object.fromEntries([
      "target_ref", "set_ref", "set_id", "title_zh", "description_zh",
      "member_hash", "member_count", "visibility",
    ].map(key => [key, item[key]]).filter(([, value]) => value !== undefined));
  }

  async function descriptors(context, state, factors) {
    const selected = selections(state);
    if (!selected.length) return [];
    const values = [];
    for (const item of selected) values.push(await runInput(context, state, item));
    const declared = new Set(values.flatMap(value => (
      value.manifest.member_refs.map(ref => FTFactorModel.decodeFrozenFactorRef(ref)?.alias)
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
    if (item.visibility !== "server") {
      bundle = await nativeRequest(serialization.native_run_input_action, {
        target_ref: item.target_ref,
      });
      for (const source of bundle.transient_factor_sources || []) {
        FTTestInputState.putFactor(state, {
          ...source,
          source_origin: "factor_set",
          factor_set_refs: [item.target_ref],
        }, {factor_name: source.factor_id});
      }
    } else {
      const payload = await context.api(
        `${serialization.descriptor_endpoint}?target_ref=${encodeURIComponent(item.target_ref)}`,
      );
      bundle = {descriptor: payload.descriptor || payload};
    }
    state.factorSetCatalog.runInputs.set(item.target_ref, bundle);
    return bundle.descriptor;
  }

  function nativeHandler() {
    return window.webkit?.messageHandlers?.factorTesterLocalFactorSets;
  }
  async function nativeRequest(action, payload = {}) {
    const handler = nativeHandler();
    if (!handler?.postMessage) throw new Error("FTClient local factor catalog is unavailable");
    return await handler.postMessage({action, ...payload});
  }

  window.FTTestFactorSets = Object.freeze({descriptors, initialize, panel, selections});
})();
