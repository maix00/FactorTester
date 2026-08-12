(() => {
  function filePicker(options, onFile) {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = options.accept;
    input.multiple = Boolean(options.multiple);
    input.hidden = true;
    input.addEventListener("change", async () => {
      for (const file of Array.from(input.files || [])) await onFile(file);
      input.value = "";
    });
    return input;
  }

  function setStatus(state, key, value) {
    FTTestInputState.initialize(state);
    state.runInputStatus[key] = value;
  }

  async function inspectFactor(context, state, file, descriptor) {
    if (!allowsFile(file, descriptor)) {
      throw new Error(context.t("因子源码必须是 .py 文件"));
    }
    const sourceCode = await file.text();
    const value = await context.api(context.servicePath(descriptor.inspect_endpoint), {
      method: "POST",
      body: JSON.stringify({source_code: sourceCode}),
    });
    if (!value.valid) throw new Error(value.error || context.t("因子源码无法通过检查"));
    return FTTestInputState.putFactor(state, {
      factor_id: value.factor_name,
      path: `${descriptor.path_prefix}/${value.factor_name}.py`,
      source_code: sourceCode,
    }, value);
  }

  async function instantiateFactor(context, state, family, params, descriptor) {
    const factorID = family?.sourceID || family?.family;
    const source = FTTestInputState.factorSource(state, factorID);
    if (!source) throw new Error(context.t("临时因子源码已离开当前测试会话"));
    const value = await context.api(context.servicePath(descriptor.inspect_endpoint), {
      method: "POST",
      body: JSON.stringify({source_code: source.source_code, params: params || {}}),
    });
    if (!value.valid) throw new Error(value.error || context.t("因子参数无法实例化"));
    return {
      factor_alias: value.factor_alias,
      factor_family_alias: value.factor_name,
      family: value.factor_name,
      params: value.normalized_params || params || {},
      math_expr: value.math_expr || family.math_expr || "",
      description: value.desc || value.description || family.description || "",
      source_kind: "transient",
      transient_factor_id: value.factor_name,
    };
  }

  async function inspectStrategy(context, state, file, descriptor, strategySpec = null) {
    if (!allowsFile(file, descriptor)) {
      throw new Error(context.t("策略源码必须是 .py 文件"));
    }
    const sourceCode = await file.text();
    const path = `${descriptor.path_prefix}/${fileName(file)}`;
    const value = await context.api(context.servicePath(descriptor.inspect_endpoint), {
      method: "POST",
      body: JSON.stringify({path, source_code: sourceCode, strategy_spec: strategySpec}),
    });
    if (!value.valid) throw new Error(value.error || context.t("策略源码无法通过检查"));
    FTTestInputState.putStrategy(state, {path, source_code: sourceCode}, value);
    return value;
  }

  async function importStrategySpec(context, state, file, descriptor) {
    if (!allowsFile(file, descriptor)) {
      throw new Error(context.t("策略配置必须是 JSON 文件"));
    }
    let raw;
    try { raw = JSON.parse(await file.text()); }
    catch (_) { throw new Error(context.t("策略配置不是有效 JSON")); }
    const spec = Array.isArray(raw) && raw.length === 1 ? raw[0] : raw;
    if (!spec || typeof spec !== "object" || Array.isArray(spec)) {
      throw new Error(context.t("策略配置必须是单个对象"));
    }
    const path = String(spec.source || "").replace(/^profile:/, "");
    const source = FTTestInputState.strategySource(state, path);
    if (!source) throw new Error(context.t("请先上传该配置引用的策略源码"));
    const value = await context.api(context.servicePath(descriptor.inspect_endpoint), {
      method: "POST",
      body: JSON.stringify({
        ...source, entrypoint: spec.entrypoint || "", strategy_spec: spec,
      }),
    });
    if (!value.valid) throw new Error(value.error || context.t("策略配置无法通过检查"));
    FTTestInputState.putStrategy(state, source, value);
    return value;
  }

  async function importDependency(context, state, file, requestedPurpose, descriptor) {
    const name = fileName(file);
    const suffix = name.includes(".") ? `.${name.split(".").pop().toLowerCase()}` : "";
    if (!allowsFile(file, descriptor)) {
      throw new Error(context.t("任务依赖必须是受支持的文本文件"));
    }
    const inferredPurpose = descriptor.purpose_by_extension?.[suffix]
      || descriptor.default_purpose;
    const purposes = descriptor.purposes || [];
    const purpose = String(requestedPurpose || inferredPurpose || "");
    const selectedPurpose = purposes.find(item => item.value === purpose);
    if (!selectedPurpose?.path_prefix) {
      throw new Error(context.t("任务依赖用途无效"));
    }
    FTTestInputState.putDependency(state, {
      path: `${selectedPurpose.path_prefix}/${name}`,
      content: await file.text(),
      content_type: descriptor.content_types?.[suffix] || "text/plain",
      title_zh: `${context.t(selectedPurpose.label)}：${name}`,
      purpose,
      analyses: [...(descriptor.analyses || [])],
    });
  }

  function factorControls(context, state, refresh, onFamily, descriptor) {
    const root = document.createElement("div");
    root.className = "test-input-toolbar";
    const picker = filePicker(descriptor, async file => {
      setStatus(state, "factorBusy", true); setStatus(state, "factorError", ""); refresh();
      try { onFamily(await inspectFactor(context, state, file, descriptor)); }
      catch (error) { setStatus(state, "factorError", error.message); }
      finally { setStatus(state, "factorBusy", false); refresh(); }
    });
    const upload = context.button(context.t(descriptor.label), () => picker.click());
    upload.disabled = Boolean(state.runInputStatus?.factorBusy);
    const note = document.createElement("small");
    note.textContent = context.t(descriptor.description || "");
    root.append(upload, note, picker);
    if (state.runInputStatus?.factorError) root.append(error(state.runInputStatus.factorError));
    const previews = sourcePreviews(context, (state.transientFactorSources || []).map(source => ({
      title: source.factor_id,
      detail: source.path,
      blocks: [{label: "Python", content: source.source_code}],
      remove: () => {
        FTTestInputState.removeFactor(state, source.factor_id);
        if (state.factorCatalog?.selectedFamilyEntry?.sourceID === source.factor_id) {
          state.factorCatalog.selectedFamilyEntry = null;
          state.factorCatalog.selectedFamily = null;
          state.factorCatalog.selectedFamilyName = "";
        }
        refresh();
      },
    })));
    if (previews) root.append(previews);
    return root;
  }

  function strategyPanel(context, state, refresh, contentOptions) {
    FTTestInputState.initialize(state);
    const root = document.createElement("section");
    root.className = "test-run-inputs";
    const heading = document.createElement("div"); heading.className = "section-heading";
    const copy = document.createElement("div");
    const title = document.createElement("h2");
    title.textContent = context.t(contentOptions.title || "运行输入");
    const note = document.createElement("p");
    note.textContent = context.t(contentOptions.description || "");
    copy.append(title, note);
    const actions = document.createElement("div"); actions.className = "test-input-actions";
    for (const descriptor of contentOptions.inputs || []) {
      appendInputAction(context, state, refresh, actions, descriptor);
    }
    heading.append(copy, actions); root.append(heading);
    const previews = runInputPreviews(context, state, refresh);
    if (previews) root.append(previews);
    else {
      const empty = document.createElement("small");
      empty.className = "test-input-empty";
      empty.textContent = context.t("未添加自定义策略，使用运行配置中的内置策略");
      root.append(empty);
    }
    if (state.runInputStatus?.strategyError) root.append(error(state.runInputStatus.strategyError));
    return root;
  }

  function appendInputAction(context, state, refresh, actions, descriptor) {
    let purpose = null;
    if (descriptor.kind === "run_dependency") {
      purpose = document.createElement("select");
      purpose.title = context.t("任务输入用途");
      purpose.setAttribute("aria-label", context.t("任务输入用途"));
      for (const item of descriptor.purposes || []) {
        const option = document.createElement("option");
        option.value = item.value; option.textContent = context.t(item.label);
        purpose.append(option);
      }
      actions.append(purpose);
    }
    const picker = filePicker(descriptor, file => runUpload(
      state, "strategyBusy", refresh, () => inputOperation(
        context, state, file, descriptor, purpose?.value || "",
      ),
    ));
    actions.append(
      context.button(context.t(descriptor.label), () => picker.click()), picker,
    );
  }

  function inputOperation(context, state, file, descriptor, purpose) {
    if (descriptor.kind === "strategy_source") {
      return inspectStrategy(context, state, file, descriptor);
    }
    if (descriptor.kind === "strategy_spec") {
      return importStrategySpec(context, state, file, descriptor);
    }
    if (descriptor.kind === "run_dependency") {
      return importDependency(context, state, file, purpose, descriptor);
    }
    throw new Error(context.t(`不支持的运行输入类型: ${descriptor.kind}`));
  }

  async function runUpload(state, busyKey, refresh, operation) {
    setStatus(state, busyKey, true); setStatus(state, "strategyError", ""); refresh();
    try { await operation(); }
    catch (errorValue) { setStatus(state, "strategyError", errorValue.message); }
    finally { setStatus(state, busyKey, false); refresh(); }
  }

  function fileName(file) {
    return String(file.name || "").replaceAll("\\", "/").split("/").pop();
  }

  function allowsFile(file, descriptor) {
    const name = fileName(file).toLowerCase();
    return (descriptor?.extensions || []).some(extension => name.endsWith(extension));
  }

  function runInputPreviews(context, state, refresh) {
    const entries = (state.transientStrategySources || []).map(source => {
      const spec = (state.strategySpecs || []).find(value => (
        value.source === `profile:${source.path}`
      ));
      const blocks = [{label: "Python", content: source.source_code}];
      if (spec) blocks.push({label: "StrategySpec JSON", content: JSON.stringify(spec, null, 2)});
      return {
        title: spec?.strategy_id || source.path,
        detail: source.path,
        blocks,
        remove: () => { FTTestInputState.removeStrategy(state, source.path); refresh(); },
      };
    });
    for (const dependency of state.runInputDependencies || []) {
      entries.push({
        title: dependency.title_zh || dependency.path,
        detail: dependency.path,
        blocks: [{label: dependency.content_type || "text/plain", content: dependency.content}],
        remove: () => { FTTestInputState.removeDependency(state, dependency.path); refresh(); },
      });
    }
    return sourcePreviews(context, entries);
  }

  function sourcePreviews(context, entries) {
    if (!entries.length) return null;
    const root = document.createElement("div"); root.className = "test-input-previews";
    for (const entry of entries) {
      const details = document.createElement("details"); details.className = "test-input-preview";
      const summary = document.createElement("summary");
      const copy = document.createElement("span");
      const title = document.createElement("b"); title.textContent = entry.title;
      const detail = document.createElement("small"); detail.textContent = entry.detail || "";
      copy.append(title, detail);
      const remove = document.createElement("button"); remove.type = "button";
      remove.textContent = "×"; remove.title = context.t("移除");
      remove.addEventListener("click", event => {
        event.preventDefault(); event.stopPropagation(); entry.remove();
      });
      summary.append(copy, remove); details.append(summary);
      details.addEventListener("toggle", () => {
        if (!details.open || details._sourceLoaded) return;
        details._sourceLoaded = true;
        const body = document.createElement("div"); body.className = "test-input-preview-body";
        for (const block of entry.blocks || []) {
          const label = document.createElement("small"); label.textContent = block.label;
          const pre = document.createElement("pre");
          const code = document.createElement("code"); code.textContent = block.content || "";
          pre.append(code); body.append(label, pre);
        }
        details.append(body);
      });
      root.append(details);
    }
    return root;
  }

  function error(message) {
    const node = document.createElement("span");
    node.className = "form-error"; node.textContent = message; return node;
  }

  window.FTTestSourceUpload = Object.freeze({
    factorControls,
    importStrategySpec,
    importDependency,
    inspectFactor,
    inspectStrategy,
    instantiateFactor,
    strategyPanel,
  });
})();
