(() => {
  const fallbackDescriptor = Object.freeze({
    kind: "factor_source",
    label: "上传临时因子源码",
    accept: ".py,text/x-python",
    inspect_endpoint: "/custom-factors/api/validate",
    path_prefix: "custom_factors",
  });

  function descriptor(state) {
    const tabs = state?.manifest?.tab_lists?.["local-settings"] || [];
    const tab = tabs.find(item => item.key === "run_inputs");
    const value = (tab?.content_options?.inputs || []).find(item => (
      item.kind === "factor_source"
    ));
    return value || fallbackDescriptor;
  }

  function open(context, state, onSaved) {
    return FTTestObjectEditorOverlay.open(context, {
      kind: "factor", mode: "create", ref: "new",
      inlineEditor: {state, onSaved},
    });
  }

  async function validateSource(context, state, sourceCode, path, refresh) {
    const value = await context.api(context.servicePath(
      descriptor(state).inspect_endpoint,
    ), {
      method: "POST",
      body: JSON.stringify({source_code: sourceCode}),
    });
    if (!value.valid) throw new Error(value.error || context.t("因子源码无法通过检查"));
    const family = FTTestInputState.putFactor(state, {
      factor_id: value.factor_name,
      path: path || `${descriptor(state).path_prefix}/${value.factor_name}.py`,
      source_code: sourceCode,
    }, value);
    const entry = FTTestFactorCatalog.familyEntries(state).find(item => (
      item.sourceKind === "transient" && item.sourceID === family.sourceID
    ));
    if (entry) await FTTestFactorCatalog.selectFamily(context, state, entry, refresh);
    return family;
  }

  function sourceEditor(context, state, refresh) {
    const root = document.createElement("section");
    root.className = "strategy-editor-factor-source-editor";
    const title = document.createElement("strong");
    title.textContent = context.t("上传或编写因子家族源码");
    const note = document.createElement("small");
    note.textContent = context.t("源码通过校验后会作为本次测试的临时因子家族，并解析参数");
    const code = document.createElement("textarea");
    code.rows = 8;
    code.placeholder = context.t("在此粘贴 Python 因子家族源码");
    const status = document.createElement("small");
    status.className = "strategy-editor-factor-source-status";
    const validate = context.button(context.t("校验源码"), async () => {
      validate.disabled = true; status.textContent = context.t("正在校验…");
      try {
        await validateSource(context, state, code.value, "", refresh);
        status.textContent = context.t("源码有效，已加入临时因子家族");
      } catch (error) {
        status.textContent = error.message || String(error);
      } finally { validate.disabled = false; }
    });
    validate.type = "button";
    root.append(title, note, code, validate, status);
    if (window.FTTestSourceUpload?.factorControls) {
      root.append(FTTestSourceUpload.factorControls(
        context, state, refresh,
        entry => FTTestFactorCatalog.selectFamily(context, state, entry, refresh),
        descriptor(state),
      ));
    }
    return root;
  }

  async function persistCreatedFactor(context, state, value, onSaved, refresh) {
    if (!value) return;
    if (value.source_kind !== "transient") {
      onSaved?.(value);
      return;
    }
    const source = FTTestInputState.factorSource(
      state, value.transient_factor_id || value.factor_family_alias || value.family,
    );
    if (!source?.source_code) throw new Error(context.t("因子源码不在当前测试会话中"));
    const response = await context.api("/custom-factors/api/create", {
      method: "POST",
      body: JSON.stringify({
        source_code: source.source_code,
        chinese_name: value.factor_alias || value.family || "",
        description: value.description || "",
        category: "自编",
        params: value.params || {},
      }),
    });
    const saved = response.factor || response;
    onSaved?.({
      ...value, ...saved,
      factor_alias: saved.factor_alias || saved.name || value.factor_alias,
      factor_ref: saved.factor_ref || saved.id || value.factor_alias,
      source_kind: "server",
      can_edit: true,
    });
    refresh?.();
  }

  async function render(context, ref, mode, options) {
    const state = options?.inlineEditor?.state;
    if (!state) throw new Error("inline factor editor requires test state");
    const mount = context.content;
    const redraw = () => {
      const onCreated = value => void persistCreatedFactor(
        context, state, value, options.inlineEditor.onSaved, redraw,
      ).catch(error => {
        state.factorCatalog.error = error.message || String(error);
        redraw();
      });
      const content = [
        sourceEditor(context, state, redraw),
        FTTestFactorEditor.familyChooser(context, state, redraw),
        FTTestFactorEditor.familyContent(
          context, state, redraw, descriptor(state),
          {onCreated},
        ),
      ];
      if (state.factorCatalog.error) {
        content.push(FTTestFactorEditor.errorText(state.factorCatalog.error));
      }
      mount.replaceChildren(...content);
    };
    FTTestFactorCatalog.prepare(state);
    mount.replaceChildren(FTUI.loading(context.t("正在读取因子家族…")));
    await FTTestFactorCatalog.initialize(context, state);
    if (!mount.isConnected && !mount.replaceChildren) return;
    redraw();
  }

  window.FTStrategyEditorFactorOverlay = Object.freeze({open, render});
})();
