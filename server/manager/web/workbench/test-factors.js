(() => {
  const {
    candidates, factorID, factorAlias, addCandidate, removeCandidate,
    setSelected, isSelected, syncSelection,
    restoreFrozenSelections,
    selectedFactor, selectedFamily,
  } = FTTestFactorSelection;
  function prepare(state) {
    if (state.factorCatalog?.prepared) return;
    state.factorCatalog = {
      native: Boolean(nativeHandler()), owners: [], revisions: [], families: [],
      selectedFamily: null, selectedFamilyEntry: null, selectedFamilyName: "",
      busy: false, error: "", prepared: true, initialized: false,
    };
    state.values.factor_candidates = candidates(state);
    restoreFrozenSelections(state);
    syncSelection(state);
    FTTestFactorSets.prepare(state);
  }
  async function initialize(context, state) {
    prepare(state);
    if (state.factorCatalog.initialized) return;
    state.factorCatalog.initialized = true;
    if (!state.factorCatalog.native) {
      restoreFamilyEntry(state);
      await FTTestFactorSets.initialize(context, state);
      return;
    }
    try {
      state.factorCatalog.owners = await nativeList("owners");
      if (!state.values.factor_owner_ref && state.factorCatalog.owners.length) state.values.factor_owner_ref = state.factorCatalog.owners[0].owner_ref;
      await loadRevisions(state);
    } catch (error) {
      state.factorCatalog.error = error.message;
    }
    await FTTestFactorSets.initialize(context, state);
  }
  function panel(context, state, refresh, contentOptions = {}) {
    const root = document.createElement("div");
    root.className = "test-factor-builder";
    const catalog = state.factorCatalog;
    const sourceInput = (contentOptions.inputs || [])
      .find(item => item.kind === "factor_source");
    const setPanel = FTTestFactorSets.panel(context, state, refresh);
    if (setPanel) root.append(setPanel);
    if (sourceInput) root.append(FTTestSourceUpload.factorControls(
      context, state, refresh, entry => selectFamily(context, state, entry, refresh),
      sourceInput,
    ));
    if (!catalog.native) {
      root.append(
        familyChooser(context, state, refresh),
        familyContent(context, state, refresh, sourceInput),
        candidateList(context, state, refresh),
      ); return root;
    }
    const source = document.createElement("div");
    source.className = "test-factor-source-grid";
    source.append(
      selectField(context.t("所有者"), catalog.owners.map(item => ({
        value: item.owner_ref,
        label: item.display_name || item.title_zh
          || item.profile_name || item.owner_ref,
      })), state.values.factor_owner_ref, async value => {
        state.values.factor_owner_ref = value;
        state.values.factor_git_commit = "";
        state.values.factor_family_ref = "";
        state.values.factor_params = {};
        catalog.selectedFamilyEntry = null;
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
        catalog.selectedFamilyEntry = null;
        catalog.selectedFamilyName = "";
        await update(context, state, refresh, () => loadFamilies(state));
      }),
      familyChooser(context, state, refresh),
    );
    root.append(source);
    root.append(familyContent(context, state, refresh, sourceInput));
    if (catalog.busy) root.append(FTUI.loading(context.t("正在读取因子工作区…")));
    if (catalog.error) root.append(errorText(catalog.error));
    root.append(candidateList(context, state, refresh));
    return root;
  }
  function familyChooser(context, state, refresh) {
    const field = document.createElement("div");
    field.className = "test-object-field test-factor-family-field";
    const label = document.createElement("b"); label.textContent = context.t("因子家族");
    const button = context.button(
      familyButtonLabel(context, state),
      () => FTFactorFamilyPicker.open(context, {
        items: familyEntries(state),
        selectedKey: state.factorCatalog.selectedFamilyEntry?.key || "",
        onSelect: entry => selectFamily(context, state, entry, refresh),
      }),
    );
    button.classList.add("test-factor-family-button");
    field.append(label, button);
    return field;
  }
  function familyEntries(state) {
    return FTFactorFamilyPicker.entries({
      publicFamilies: state.families,
      localFamilies: state.factorCatalog.families,
      transientFamilies: state.transientFactorFamilies,
      ownerRef: state.values.factor_owner_ref,
      gitCommit: state.values.factor_git_commit,
    });
  }
  function familyButtonLabel(context, state) {
    const selected = state.factorCatalog.selectedFamilyEntry;
    if (!selected) return context.t("搜索并选择因子家族…");
    const labels = {
      local: "本地修订", public: "公共因子库", transient: "任务临时源码",
    };
    const source = context.t(labels[selected.sourceKind] || selected.sourceKind);
    return `${selected.title} · ${source}`;
  }
  async function selectFamily(context, state, entry, refresh) {
    const catalog = state.factorCatalog;
    catalog.selectedFamilyEntry = entry;
    catalog.selectedFamilyName = entry.family;
    if (entry.sourceKind === "transient") {
      catalog.selectedFamily = entry.familyMetadata || entry;
      state.values.factor_family_ref = "";
      state.values.factor_params = defaultParameters(catalog.selectedFamily);
      refresh();
      return;
    }
    if (entry.sourceKind === "local") {
      await update(context, state, refresh, () => loadFamily(state));
      return;
    }
    catalog.selectedFamily = null;
    state.values.factor_family_ref = entry.familyRef;
    state.values.factor_params = {};
    refresh();
  }
  function familyContent(context, state, refresh, sourceInput) {
    const entry = state.factorCatalog.selectedFamilyEntry;
    if (!entry) return FTUI.empty(
      context.t("尚未选择因子家族"), context.t("搜索公共因子库或本地 Git 修订"),
    );
    if (entry.sourceKind === "public") {
      return registeredFactorPanel(context, state, entry, refresh);
    }
    const family = selectedFamily(state);
    return family
      ? parameterEditor(context, state, family, refresh, sourceInput)
      : document.createElement("div");
  }
  function registeredFactorPanel(context, state, family, refresh) {
    const root = document.createElement("div");
    root.className = "test-registered-factor-list";
    const title = document.createElement("b"); title.textContent = context.t("公共因子家族中的已登记因子");
    root.append(title);
    const factors = FTFactorFamilyPicker.familyFactors(family, state.factors);
    if (!factors.length) {
      root.append(FTUI.empty(context.t("该家族暂无可用因子"), ""));
      return root;
    }
    for (const factor of factors) {
      const row = document.createElement("div");
      const copy = document.createElement("span");
      const name = document.createElement("b"); name.textContent = factorAlias(factor);
      const note = document.createElement("small"); note.textContent = factor.chinese_name || factor.description || factor.owner_alias || "";
      copy.append(name, note);
      const exists = candidates(state).some(item => factorID(item) === factorID(factor));
      const add = context.button(context.t(exists ? "已加入" : "加入候选"), () => {
        addCandidate(state, factor); refresh();
      });
      add.disabled = exists;
      row.append(copy, add); root.append(row);
    }
    return root;
  }
  function parameterEditor(context, state, family, refresh, sourceInput) {
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
        const entry = state.factorCatalog.selectedFamilyEntry;
        const value = entry?.sourceKind === "transient"
          ? await FTTestSourceUpload.instantiateFactor(
            context, state, entry, state.values.factor_params || {},
            sourceInput,
          )
          : await nativeRequest("instantiate", {
            owner_ref: state.values.factor_owner_ref,
            git_commit: state.values.factor_git_commit,
            family: family.family,
            params: state.values.factor_params || {},
          });
        addCandidate(state, value);
      });
    });
    add.disabled = state.factorCatalog.selectedFamilyEntry?.sourceKind !== "transient"
      && !(state.values.factor_owner_ref && state.values.factor_git_commit);
    root.append(add);
    return root;
  }
  function candidateList(context, state, refresh) {
    const root = document.createElement("div");
    root.className = "test-factor-candidates";
    const title = document.createElement("b"); title.textContent = context.t("因子候选");
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
      const name = document.createElement("b"); name.textContent = factor.factor_alias || factor.alias || factor.factor_ref;
      const detail = document.createElement("small");
      const revision = factor.source_kind === "transient"
        ? context.t("任务临时输入")
        : factor.git_commit ? factor.git_commit.slice(0, 10) : context.t("服务器登记");
      detail.textContent = factor.source_kind === "transient"
        ? revision
        : `${factor.owner_ref || ""} · ${revision}`.replace(/^ · | · $/g, "");
      copy.append(name, detail);
      const remove = context.button(context.t("移除"), event => {
        event.preventDefault();
        removeCandidate(state, factor);
        refresh();
      });
      row.append(input, copy, remove); list.append(row);
    }
    root.append(list);
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
    restoreFamilyEntry(state);
    await loadFamily(state);
  }
  function restoreFamilyEntry(state) {
    const catalog = state.factorCatalog;
    if (catalog.selectedFamilyEntry) return;
    const current = candidates(state)
      .find(item => factorID(item) === state.factorRef) || selectedFactor(state);
    const entries = familyEntries(state);
    const exact = entries.find(item => (
      item.factor_refs?.includes(factorID(current))
      || item.familyRef === current?.family_ref
      || item.familyRef === current?.factor_family_ref
    ));
    const currentSource = current?.source_kind === "transient"
      ? "transient" : current?.git_commit ? "local" : "public";
    const named = entries.find(item => item.sourceKind === currentSource
      && (item.family === current?.family || item.family === current?.factor_family_alias));
    catalog.selectedFamilyEntry = exact || named || null;
    catalog.selectedFamilyName = catalog.selectedFamilyEntry?.family || "";
  }
  async function loadFamily(state) {
    const catalog = state.factorCatalog;
    if (catalog.selectedFamilyEntry?.sourceKind === "transient") {
      catalog.selectedFamily = catalog.selectedFamilyEntry.familyMetadata
        || catalog.selectedFamilyEntry;
      state.values.factor_family_ref = "";
      return;
    }
    if (catalog.selectedFamilyEntry?.sourceKind === "public") {
      catalog.selectedFamily = null;
      state.values.factor_family_ref = catalog.selectedFamilyEntry.familyRef;
      state.values.factor_params = {};
      return;
    }
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
    control.addEventListener("input", () => {
      values[parameter.alias] = control.value;
    });
    return control;
  }
  function defaultParameters(family) {
    return Object.fromEntries((family?.params || []).map(item => (
      [item.alias, item.default_value ?? ""]
    )));
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
    const node = document.createElement("p"); node.className = "form-error";
    node.textContent = message; return node;
  }
  window.FTTestFactors = {initialize, panel, prepare, selectedFactor, selectedFamily};
})();
