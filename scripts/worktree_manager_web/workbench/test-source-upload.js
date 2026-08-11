(() => {
  function filePicker(options, onFile) {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = options.accept;
    input.hidden = true;
    input.addEventListener("change", async () => {
      const file = input.files?.[0];
      if (file) await onFile(file);
      input.value = "";
    });
    return input;
  }

  function setStatus(state, key, value) {
    FTTestInputState.initialize(state);
    state.runInputStatus[key] = value;
  }

  async function inspectFactor(context, state, file) {
    if (!String(file.name || "").toLowerCase().endsWith(".py")) {
      throw new Error(context.t("因子源码必须是 .py 文件"));
    }
    const sourceCode = await file.text();
    const value = await context.api(context.servicePath("/custom-factors/api/validate"), {
      method: "POST",
      body: JSON.stringify({source_code: sourceCode}),
    });
    if (!value.valid) throw new Error(value.error || context.t("因子源码无法通过检查"));
    return FTTestInputState.putFactor(state, {
      factor_id: value.factor_name,
      path: `custom_factors/${value.factor_name}.py`,
      source_code: sourceCode,
    }, value);
  }

  async function instantiateFactor(context, state, family, params) {
    const factorID = family?.sourceID || family?.family;
    const source = FTTestInputState.factorSource(state, factorID);
    if (!source) throw new Error(context.t("临时因子源码已离开当前测试会话"));
    const value = await context.api(context.servicePath("/custom-factors/api/validate"), {
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

  async function inspectStrategy(context, state, file, strategySpec = null) {
    if (!String(file.name || "").toLowerCase().endsWith(".py")) {
      throw new Error(context.t("策略源码必须是 .py 文件"));
    }
    const sourceCode = await file.text();
    const path = `strategies/${String(file.name).replaceAll("\\", "/").split("/").pop()}`;
    const value = await context.api(context.servicePath("/api/run-inputs/strategy/inspect"), {
      method: "POST",
      body: JSON.stringify({path, source_code: sourceCode, strategy_spec: strategySpec}),
    });
    if (!value.valid) throw new Error(value.error || context.t("策略源码无法通过检查"));
    FTTestInputState.putStrategy(state, {path, source_code: sourceCode}, value);
    return value;
  }

  async function importStrategySpec(context, state, file) {
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
    const value = await context.api(context.servicePath("/api/run-inputs/strategy/inspect"), {
      method: "POST",
      body: JSON.stringify({
        ...source, entrypoint: spec.entrypoint || "", strategy_spec: spec,
      }),
    });
    if (!value.valid) throw new Error(value.error || context.t("策略配置无法通过检查"));
    FTTestInputState.putStrategy(state, source, value);
    return value;
  }

  function factorControls(context, state, refresh, onFamily) {
    const root = document.createElement("div");
    root.className = "test-input-toolbar";
    const picker = filePicker({accept: ".py,text/x-python"}, async file => {
      setStatus(state, "factorBusy", true); setStatus(state, "factorError", ""); refresh();
      try { onFamily(await inspectFactor(context, state, file)); }
      catch (error) { setStatus(state, "factorError", error.message); }
      finally { setStatus(state, "factorBusy", false); refresh(); }
    });
    const upload = context.button(context.t("上传临时因子源码"), () => picker.click());
    upload.disabled = Boolean(state.runInputStatus?.factorBusy);
    const note = document.createElement("small");
    note.textContent = context.t("上传阶段不进入因子库；提交后作为任务输入保留，清空任务文件时一并删除");
    root.append(upload, note, picker);
    if (state.runInputStatus?.factorError) root.append(error(state.runInputStatus.factorError));
    return root;
  }

  function strategyPanel(context, state, refresh) {
    FTTestInputState.initialize(state);
    const root = document.createElement("section");
    root.className = "test-run-inputs";
    const heading = document.createElement("div"); heading.className = "section-heading";
    const copy = document.createElement("div");
    const title = document.createElement("h2"); title.textContent = context.t("策略 Hook 与运行输入");
    const note = document.createElement("p");
    note.textContent = context.t("上传的源码与规范化策略配置将冻结到每个测试任务");
    copy.append(title, note);
    const actions = document.createElement("div"); actions.className = "test-input-actions";
    const sourcePicker = filePicker({accept: ".py,text/x-python"}, file => (
      runUpload(state, "strategyBusy", refresh, () => inspectStrategy(context, state, file))
    ));
    const specPicker = filePicker({accept: ".json,application/json"}, file => (
      runUpload(state, "strategyBusy", refresh, () => importStrategySpec(context, state, file))
    ));
    actions.append(
      context.button(context.t("上传策略 Hook"), () => sourcePicker.click()),
      context.button(context.t("导入策略配置"), () => specPicker.click()),
      sourcePicker, specPicker,
    );
    heading.append(copy, actions); root.append(heading);
    root.append(inputChips(context, state, refresh));
    if (state.runInputStatus?.strategyError) root.append(error(state.runInputStatus.strategyError));
    return root;
  }

  async function runUpload(state, busyKey, refresh, operation) {
    setStatus(state, busyKey, true); setStatus(state, "strategyError", ""); refresh();
    try { await operation(); }
    catch (errorValue) { setStatus(state, "strategyError", errorValue.message); }
    finally { setStatus(state, busyKey, false); refresh(); }
  }

  function inputChips(context, state, refresh) {
    const root = document.createElement("div"); root.className = "test-input-chips";
    const sources = state.transientStrategySources || [];
    if (!sources.length) {
      const empty = document.createElement("small");
      empty.textContent = context.t("未添加自定义策略，使用运行配置中的内置策略");
      root.append(empty); return root;
    }
    sources.forEach((source, index) => {
      if (index >= 2) return;
      const chip = document.createElement("span"); chip.className = "test-input-chip";
      const spec = (state.strategySpecs || []).find(item => (
        item.source === `profile:${source.path}`
      ));
      const name = document.createElement("b");
      name.textContent = [source.path, spec?.strategy_id].filter(Boolean).join(" · ");
      const remove = document.createElement("button"); remove.type = "button";
      remove.textContent = "×"; remove.title = context.t("移除");
      remove.addEventListener("click", () => {
        FTTestInputState.removeStrategy(state, source.path); refresh();
      });
      chip.append(name, remove); root.append(chip);
    });
    if (sources.length > 2) {
      const remaining = document.createElement("span");
      remaining.className = "test-input-count";
      remaining.textContent = `+${sources.length - 2}`;
      root.append(remaining);
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
    inspectFactor,
    inspectStrategy,
    instantiateFactor,
    strategyPanel,
  });
})();
