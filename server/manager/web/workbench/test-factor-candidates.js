(() => {
  function openEditor(context, mode, ref, onSaved) {
    return FTTestObjectEditorOverlay.open(context, {
      kind: "factor", mode, ref, onSaved,
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
        void openEditor(context, "edit", ref, onSaved);
      },
    };
  }

  function list(context, state, refresh) {
    const root = document.createElement("div");
    root.className = "test-factor-candidates";
    const rows = FTTestFactorSelection.candidates(state);
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
        label: factor.factor_alias || factor.alias || factor.factor_ref,
        description: [
          factor.owner_ref || factor.owner_alias || "",
          factor.source_kind === "transient"
            ? context.t("任务临时输入")
            : factor.git_commit ? factor.git_commit.slice(0, 10) : context.t("服务器登记"),
        ].filter(Boolean).join(" · "),
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
            : openEditor(context, "create", "new", savedFactor)
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
        context.t("暂无因子候选"), context.t("选择因子家族并填写参数后添加"),
      ));
    }
    root.append(control);
    return root;
  }

  window.FTTestFactorCandidates = Object.freeze({list});
})();
