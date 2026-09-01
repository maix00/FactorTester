(() => {
  function openEditor(context, mode, ref, onSaved, testState = null, initialValue = null) {
    return FTTestLazyCode.openObjectEditor(context, {
      kind: "factor", mode, ref, onSaved, testState,
      temporary: mode === "create" || initialValue?.temporary === true,
      initialValue,
    });
  }

  function editAction(context, factor, onSaved) {
    if (!context.session || !factor?.can_edit || factor.is_public || factor.factor_kind === "public") {
      return null;
    }
    const ref = FTTestFactorSelection.factorID(factor);
    return {
      label: context.t("编辑"),
      title: context.t("在当前浮层编辑因子"),
      buttonClass: "secondary",
      onClick: event => {
        event?.preventDefault();
        void openEditor(context, "edit", ref, onSaved, null, factor);
      },
    };
  }

  function sourceDescription(context, state, factor) {
    const refs = [...new Set((factor?.factor_set_refs || []).filter(Boolean))];
    const selectedSets = state?.values?.factor_set_selections || [];
    const setNames = refs.map(ref => {
      const item = selectedSets.find(value => value?.target_ref === ref);
      return item?.title_zh || item?.set_id || ref;
    });
    let source = "";
    if (setNames.length) {
      source = `${context.t("因子集合")}: ${setNames.join("、")}`;
    } else if (factor?.source_kind === "transient" || factor?.source_origin === "transient") {
      source = context.t("现场新建/临时因子");
    } else if (factor?.source_kind === "factor_set") {
      source = context.t("因子集合");
    } else {
      source = context.t("因子库");
    }
    return [
      source,
      factor?.owner_ref || factor?.owner_alias || "",
      factor?.family_formula_fingerprint
        ? factor.family_formula_fingerprint.slice(0, 12) : "",
    ].filter(Boolean).join(" · ");
  }

  function list(context, state, refresh) {
    const root = document.createElement("div");
    root.className = "test-factor-candidates";
    const rows = FTTestFactorSelection.candidates(state);
    // In a backtest the outer factor tab only constructs the candidate pool.
    // Selection belongs to a nested strategy, so this page is deliberately
    // read-only and exposes the legacy primary factor as an automatic value.
    if (state.kind !== "ic") return outerSummary(context, state, rows);
    const savedFactor = value => {
      if (!value) return;
      FTTestFactorSelection.addCandidate(state, value);
      refresh?.();
    };
    const picker = FTTestObjectPicker.create(context, {
      title: context.t("因子候选"),
      note: context.t(state.kind === "ic"
        ? "可多选因子候选；每个候选冻结为独立 IC 任务"
        : "选择一个因子候选作为本次回测因子"),
      items: rows.map(factor => ({
        value: FTTestFactorSelection.factorID(factor),
        label: factor.alias,
        description: sourceDescription(context, state, factor),
        factor,
      })).filter(item => item.value),
      selected: FTTestFactorSelection.selectedIDs(state),
      multi: state.kind === "ic",
      compact: true,
      name: `test-factors-${state.kind}`,
      onCreate: context.session
        ? () => void (
          window.FTStrategyEditorFactorOverlay?.open
            ? FTStrategyEditorFactorOverlay.open(context, state, savedFactor)
            : openEditor(context, "create", "new", savedFactor, state)
        )
        : null,
      createLabel: context.t("新建因子"),
      itemActions: item => {
        const factor = rows.find(value => FTTestFactorSelection.factorID(value) === item.value);
        const actions = [];
        const edit = editAction(context, factor, savedFactor);
        if (edit) actions.push(edit);
        actions.push({
          label: context.t("移除"),
          title: context.t("从本次测试候选中移除"),
          buttonClass: "secondary",
          onClick: event => {
            event?.preventDefault();
            FTTestFactorSelection.removeCandidate(state, factor);
            refresh?.();
          },
        });
        return actions;
      },
      onChange: values => {
        FTTestFactorSelection.setSelectedIDs(state, values);
        refresh?.();
      },
    });
    const control = FTTestFieldRow.create(
      context.t("因子"), picker.element,
      window.FTTestFieldHelp?.forField?.(
        state.manifest,
        state.kind === "ic" ? ["factor_selections", "factor"] : ["factor", "factor_selections"],
        context,
      ) || "",
      {className: "test-factor-candidates"},
    );
    if (!rows.length) {
      control.querySelector(".test-field-row-control").append(FTUI.empty(
        context.t("暂无因子候选"), context.t("通过因子集合或因子来源添加"),
      ));
    }
    root.append(control);
    return root;
  }

  function outerSummary(context, state, rows) {
    FTTestFactorSelection.autoSelectPrimary?.(state);
    const root = document.createElement("div");
    root.className = "test-factor-candidates test-factor-candidates-summary";
    const candidateHelp = window.FTTestFieldHelp?.forField?.(
      state.manifest, "factor_candidates", context,
    ) || "";
    root.append(FTTestFieldRow.create(
      context.t("因子候选"), summaryControl(context, state, rows), candidateHelp,
    ));
    const primary = FTTestFactorSelection.selectedFactor(state);
    const factorField = window.FTTestFieldHelp?.field?.(state.manifest, "factor");
    const primaryLabel = factorField?.serialization?.outer_selection_label
      || factorField?.label || context.t("因子");
    const primaryValue = document.createElement("span");
    primaryValue.className = "test-factor-primary-value";
    primaryValue.textContent = primary
      ? FTTestFactorSelection.factorAlias(primary)
      : context.t("未设置");
    root.append(FTTestFieldRow.create(
      primaryLabel, primaryValue,
      window.FTTestFieldHelp?.forField?.(state.manifest, "factor", context) || "",
    ));
    return root;
  }

  function summaryControl(context, state, rows = FTTestFactorSelection.candidates(state)) {
    const root = document.createElement("div");
    root.className = "test-factor-candidate-summary-control";
    if (!rows.length) {
      root.append(FTUI.empty(
        context.t("暂无因子候选"), context.t("通过因子集合或因子来源添加"),
      ));
      return root;
    }
    const list = document.createElement("ul");
    list.className = "test-factor-candidate-summary-list";
    rows.forEach(factor => {
      const item = document.createElement("li");
      const label = document.createElement("strong");
      label.textContent = factor.alias;
      const description = document.createElement("small");
      description.textContent = sourceDescription(context, state, factor);
      item.append(label, description);
      list.append(item);
    });
    root.append(list);
    return root;
  }

  window.FTTestFactorCandidates = Object.freeze({list, sourceDescription, summaryControl});
})();
