(() => {
  const sourceKeys = [
    "factor_owner_ref", "factor_git_commit", "factor_family_ref", "factor_params",
  ];
  const {
    candidates, factorID, factorAlias, addCandidate, removeCandidate,
    setSelected, isSelected, syncSelection, restoreFrozenSelections,
    selectedFactor, selectedFamily,
  } = FTTestFactorSelection;

  async function initialize(context, state) {
    state.factorCatalog = {
      native: Boolean(nativeHandler()), owners: [], revisions: [], families: [],
      selectedFamily: null, selectedFamilyName: "", busy: false, error: "",
    };
    state.values.factor_candidates = candidates(state);
    restoreFrozenSelections(state);
    syncSelection(state);
    if (!state.factorCatalog.native) return;
    try {
      state.factorCatalog.owners = await nativeList("owners");
      if (!state.values.factor_owner_ref && state.factorCatalog.owners.length) {
        state.values.factor_owner_ref = state.factorCatalog.owners[0].owner_ref;
      }
      await loadRevisions(state);
    } catch (error) {
      state.factorCatalog.error = error.message;
    }
  }

  function panel(context, state, refresh) {
    const root = document.createElement("div");
    root.className = "test-factor-builder";
    const catalog = state.factorCatalog;
    if (!catalog.native) {
      root.append(serverFallback(context, state, refresh));
      return root;
    }
    const source = document.createElement("div");
    source.className = "test-factor-source-grid";
    source.append(
      selectField(context.t("所有者"), catalog.owners.map(item => ({
        value: item.owner_ref,
        label: item.display_name || item.title_zh || item.profile_name || item.owner_ref,
      })), state.values.factor_owner_ref, async value => {
        state.values.factor_owner_ref = value;
        state.values.factor_git_commit = "";
        state.values.factor_family_ref = "";
        state.values.factor_params = {};
        catalog.selectedFamilyName = "";
        await update(context, state, refresh, () => loadRevisions(state));
      }),
      selectField(context.t("Git commit"), catalog.revisions.map(item => ({
        value: item.git_commit,
        label: `${item.git_commit.slice(0, 10)} · ${item.subject || ""}`,
      })), state.values.factor_git_commit, async value => {
        state.values.factor_git_commit = value;
        state.values.factor_family_ref = "";
        state.values.factor_params = {};
        catalog.selectedFamilyName = "";
        await update(context, state, refresh, () => loadFamilies(state));
      }),
      selectField(context.t("因子家族"), catalog.families.map(item => ({
        value: item.family,
        label: item.family,
      })), catalog.selectedFamilyName, async value => {
        catalog.selectedFamilyName = value;
        await update(context, state, refresh, () => loadFamily(state));
      }),
    );
    root.append(source);
    const family = selectedFamily(state);
    if (family) root.append(parameterEditor(context, state, family, refresh));
    if (catalog.busy) root.append(FTUI.loading(context.t("正在读取因子工作区…")));
    if (catalog.error) root.append(errorText(catalog.error));
    root.append(candidateList(context, state, refresh));
    return root;
  }

  function parameterEditor(context, state, family, refresh) {
    const root = document.createElement("div");
    root.className = "test-factor-parameters";
    for (const parameter of family.params || []) {
      const field = document.createElement("label");
      const title = document.createElement("b");
      title.textContent = parameter.alias || parameter.name;
      const help = document.createElement("small");
      help.textContent = parameter.desc || parameter.value_space_desc || parameter.type || "";
      const control = parameterControl(parameter, state.values.factor_params || {});
      field.append(title, control, help);
      root.append(field);
    }
    const add = context.button(context.t("添加到因子候选"), async () => {
      await update(context, state, refresh, async () => {
        const value = await nativeRequest("instantiate", {
          owner_ref: state.values.factor_owner_ref,
          git_commit: state.values.factor_git_commit,
          family: family.family,
          params: state.values.factor_params || {},
        });
        addCandidate(state, value);
      });
    });
    add.disabled = !(state.values.factor_owner_ref && state.values.factor_git_commit);
    root.append(add);
    return root;
  }

  function candidateList(context, state, refresh) {
    const root = document.createElement("div");
    root.className = "test-factor-candidates";
    const title = document.createElement("b");
    title.textContent = context.t("因子候选");
    root.append(title);
    const rows = candidates(state);
    if (!rows.length) {
      root.append(FTUI.empty(context.t("暂无因子候选"), context.t("选择因子家族并填写参数后添加")));
      return root;
    }
    const list = document.createElement("div");
    list.className = "test-factor-candidate-list";
    for (const factor of rows) {
      const row = document.createElement("label");
      const input = document.createElement("input");
      input.type = state.kind === "ic" ? "checkbox" : "radio";
      input.name = state.kind === "ic" ? "" : `factor-${state.kind}`;
      input.checked = isSelected(state, factor);
      input.addEventListener("change", () => {
        setSelected(state, factor, input.checked);
        refresh();
      });
      const copy = document.createElement("span");
      const name = document.createElement("b");
      name.textContent = factor.factor_alias || factor.alias || factor.factor_ref;
      const detail = document.createElement("small");
      const revision = factor.git_commit ? factor.git_commit.slice(0, 10) : context.t("服务器登记");
      detail.textContent = `${factor.owner_ref || ""} · ${revision}`.replace(/^ · | · $/g, "");
      copy.append(name, detail);
      const remove = context.button(context.t("移除"), event => {
        event.preventDefault();
        removeCandidate(state, factor);
        refresh();
      });
      row.append(input, copy, remove);
      list.append(row);
    }
    root.append(list);
    return root;
  }

  function serverFallback(context, state, refresh) {
    const root = document.createElement("div");
    root.className = "test-factor-server-fallback";
    const note = document.createElement("small");
    note.textContent = context.t("Web 端可选择已同步到服务器的因子；本地 owner 与 Git commit 由 FTClient 提供");
    root.append(
      note,
      selectField(context.t("因子"), state.factors.map(item => ({
        value: factorID(item), label: factorAlias(item),
      })).filter(item => item.value), state.factorRef, value => {
        const factor = state.factors.find(item => factorID(item) === value);
        if (factor) addCandidate(state, factor);
        state.factorRef = value;
        syncSelection(state);
        refresh();
      }),
      candidateList(context, state, refresh),
    );
    return root;
  }

  async function loadRevisions(state) {
    const catalog = state.factorCatalog;
    catalog.revisions = state.values.factor_owner_ref
      ? await nativeList("revisions", {owner_ref: state.values.factor_owner_ref, limit: 50}) : [];
    if (!catalog.revisions.some(item => item.git_commit === state.values.factor_git_commit)) {
      state.values.factor_git_commit = catalog.revisions[0]?.git_commit || "";
    }
    await loadFamilies(state);
  }

  async function loadFamilies(state) {
    const catalog = state.factorCatalog;
    catalog.families = state.values.factor_owner_ref && state.values.factor_git_commit
      ? await nativeList("families", {
        owner_ref: state.values.factor_owner_ref,
        git_commit: state.values.factor_git_commit,
      }) : [];
    const current = candidates(state).find(item => factorID(item) === state.factorRef);
    const preferred = catalog.selectedFamilyName || current?.family
      || current?.factor_family_alias || catalog.families[0]?.family || "";
    catalog.selectedFamilyName = catalog.families.some(item => item.family === preferred)
      ? preferred : catalog.families[0]?.family || "";
    await loadFamily(state);
  }

  async function loadFamily(state) {
    const catalog = state.factorCatalog;
    if (!(state.values.factor_owner_ref && state.values.factor_git_commit
      && catalog.selectedFamilyName)) {
      catalog.selectedFamily = null;
      state.values.factor_family_ref = "";
      state.values.factor_params = {};
      return;
    }
    const previousRef = state.values.factor_family_ref;
    const value = await nativeRequest("family", {
      owner_ref: state.values.factor_owner_ref,
      git_commit: state.values.factor_git_commit,
      family: catalog.selectedFamilyName,
    });
    catalog.selectedFamily = value;
    state.values.factor_family_ref = value.family_ref || "";
    if (previousRef !== state.values.factor_family_ref) {
      state.values.factor_params = defaultParameters(value);
    }
  }

  function parameterControl(parameter, values) {
    let control;
    const options = Array.isArray(parameter.options) ? parameter.options : [];
    if (parameter.input_mode === "enum" && options.length) {
      control = document.createElement("select");
      for (const option of options) {
        const item = document.createElement("option");
        item.value = String(option.value ?? "");
        item.textContent = option.label || item.value;
        control.append(item);
      }
    } else {
      control = document.createElement("input");
      control.type = "text";
    }
    control.value = values[parameter.alias] ?? parameter.default_value ?? "";
    values[parameter.alias] = control.value;
    control.addEventListener("input", () => { values[parameter.alias] = control.value; });
    return control;
  }

  function defaultParameters(family) {
    return Object.fromEntries((family?.params || []).map(item => [
      item.alias, item.default_value ?? "",
    ]));
  }

  function selectField(label, options, value, updateValue) {
    const field = document.createElement("label");
    field.className = "test-object-field";
    const text = document.createElement("b"); text.textContent = label;
    const select = document.createElement("select");
    const empty = document.createElement("option");
    empty.value = ""; empty.textContent = `— ${label} —`; select.append(empty);
    for (const option of options) {
      const item = document.createElement("option");
      item.value = option.value; item.textContent = option.label; select.append(item);
    }
    select.value = value || "";
    select.addEventListener("change", () => updateValue(select.value));
    field.append(text, select);
    return field;
  }

  async function update(context, state, refresh, operation) {
    state.factorCatalog.busy = true;
    state.factorCatalog.error = "";
    refresh();
    try { await operation(); }
    catch (error) { state.factorCatalog.error = error.message; }
    finally { state.factorCatalog.busy = false; refresh(); }
  }

  function nativeHandler() {
    return window.webkit?.messageHandlers?.factorTesterLocalFactorSets;
  }
  async function nativeRequest(action, payload = {}) {
    const handler = nativeHandler();
    if (!handler?.postMessage) throw new Error("FTClient local factor catalog is unavailable");
    return await handler.postMessage({action, ...payload});
  }
  async function nativeList(action, payload = {}) {
    const value = await nativeRequest(action, payload);
    return Array.isArray(value) ? value : [];
  }
  function errorText(message) {
    const node = document.createElement("p");
    node.className = "form-error"; node.textContent = message; return node;
  }
  window.FTTestFactors = {
    initialize, panel, selectedFactor, selectedFamily, sourceKeys,
  };
})();
