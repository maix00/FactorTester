(() => {
  function factorCount(state) {
    const selected = window.FTTestFactorSelection?.selectedIDs?.(state) || [];
    if (selected.length) return selected.length;
    const values = Array.isArray(state.values?.factor_selections)
      ? state.values.factor_selections : [];
    return values.length || (state.factorRef ? 1 : 0);
  }

  function evaluationPlan(state) {
    if (state.kind !== "ic") return null;
    return FTICConfiguration.evaluationPlan({
      values: state.values,
      factorCount: factorCount(state),
      productCount: FTTestProducts.selectedGroups(state).length,
    });
  }

  function planSummary(context, state) {
    const plan = evaluationPlan(state);
    if (!plan) return null;
    const root = document.createElement("div");
    root.className = "test-run-matrix";
    const label = document.createElement("strong");
    label.textContent = context.t("评估矩阵");
    const values = [
      ["因子", plan.factors],
      ["收益期", plan.horizons == null
        ? "按因子频率展开"
        : `${plan.exact ? "" : "≤"}${plan.horizons}`],
      ["延迟", plan.delays],
      ["IC 类型", plan.methods],
      ["产品任务", plan.jobs],
    ];
    root.append(label, ...values.map(([name, value]) => {
      const chip = document.createElement("span");
      chip.textContent = `${context.t(name)} ${value}`;
      return chip;
    }));
    if (plan.slicesPerJob != null) {
      const total = document.createElement("small");
      const template = plan.exact
        ? "每个产品任务复用因子值，计算 %lld 个评估切片"
        : "每个产品任务复用因子值，最多计算 %lld 个评估切片；物理时长重复项会去重";
      total.textContent = context.t(template).replace("%lld", String(plan.slicesPerJob));
      root.append(total);
    }
    return root;
  }

  window.FTTestRunSummary = Object.freeze({evaluationPlan, planSummary});
})();
