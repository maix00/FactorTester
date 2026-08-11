(() => {
  const terminalStatuses = new Set(["succeeded", "failed", "cancelled"]);

  function factorCount(state) {
    const selected = window.FTTestFactorSelection?.selectedIDs?.(state) || [];
    if (selected.length) return selected.length;
    const values = Array.isArray(state.values?.factor_selections)
      ? state.values.factor_selections : [];
    return values.length || (state.factorRef ? 1 : 0);
  }

  function evaluationPlan(state) {
    const horizon = window.FTICHorizonSettings.normalizeHorizon(
      state.values?.forward_return_horizons,
    );
    const delays = window.FTICHorizonSettings.normalizeDelays(state.values?.ic_lags);
    const methods = state.values?.ic_correlation === "both" ? 2 : 1;
    const horizons = horizon.sampling === "explicit"
      ? horizon.bases.length * horizon.multipliers.length : null;
    const factors = factorCount(state);
    return {
      factors,
      horizons,
      horizonMode: horizon.sampling,
      delays: delays.length,
      methods,
      jobs: FTTestProducts.selectedGroups(state).length,
      slicesPerJob: horizons == null ? null : factors * horizons * delays.length * methods,
    };
  }

  function planSummary(context, state) {
    if (state.kind !== "ic") return null;
    const plan = evaluationPlan(state);
    const root = document.createElement("div");
    root.className = "test-run-matrix";
    const label = document.createElement("strong");
    label.textContent = context.t("评估矩阵");
    const values = [
      ["因子", plan.factors],
      ["收益期", plan.horizons == null ? "按因子频率展开" : plan.horizons],
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
      total.textContent = context.t("每个产品任务复用因子值，计算 %lld 个评估切片")
        .replace("%lld", String(plan.slicesPerJob));
      root.append(total);
    }
    return root;
  }

  function recordDetail(item, loaded) {
    item.detailPayload = loaded.payload;
    item.taskDetail = loaded.taskDetail;
    item.job = loaded.job;
    item.port = Number(loaded.resolvedPort || item.port || 0);
    item.portQuery = loaded.portQuery || (item.port ? `?port=${item.port}` : "");
    item.phase = String(loaded.job?.status || item.phase || "submitted");
    item.resultError = "";
    return item;
  }

  async function refresh(context, item, rerender) {
    if (!item.jobID || item.resultLoading) return false;
    item.resultLoading = true;
    item.resultError = "";
    rerender?.();
    try {
      recordDetail(item, await window.FTJobs.loadDetail(context, item.port, item.jobID));
      return true;
    } catch (error) {
      item.resultError = error.message || String(error);
      return false;
    } finally {
      item.resultLoading = false;
      rerender?.();
    }
  }

  function resultSection(context, state, item) {
    const task = item.taskDetail || {};
    const payload = item.detailPayload || {};
    const artifacts = (task.artifacts || []).filter(entry => entry.state === "active");
    const options = {artifacts, jobID: item.jobID, portQuery: item.portQuery || ""};
    if (state.kind === "ic") return window.FTICResults?.section(context, options);
    if (state.kind === "backtest") {
      return window.FTBacktestResults?.section(context, {
        ...options,
        configuration: task.configuration || {},
        resultSummary: payload.result_summary || task.results?.summary || {},
        job: item.job || {},
      });
    }
    return null;
  }

  function render(context, state, item, rerender) {
    const root = document.createElement("div");
    root.className = "test-run-inline-results";
    if (!item.jobID) return root;
    const toolbar = document.createElement("div");
    toolbar.className = "test-run-result-actions";
    const reload = context.button("↻", () => refresh(context, item, rerender), context.t("刷新任务结果"));
    reload.disabled = Boolean(item.resultLoading);
    toolbar.append(reload);
    root.append(toolbar);
    if (item.resultLoading) {
      root.append(window.FTUI.loading(context.t("正在读取任务结果…")));
      return root;
    }
    if (item.resultError) {
      const error = document.createElement("p");
      error.className = "test-run-error"; error.textContent = item.resultError;
      root.append(error); return root;
    }
    if (!item.taskDetail) {
      const hint = document.createElement("p");
      hint.className = "test-run-result-hint";
      hint.textContent = context.t("任务提交后可在此刷新并查看完整测试结果");
      root.append(hint); return root;
    }
    const section = resultSection(context, state, item);
    if (section) root.append(section);
    else {
      const hint = document.createElement("p");
      hint.className = "test-run-result-hint";
      hint.textContent = terminalStatuses.has(item.phase)
        ? context.t("该任务没有可展示的领域结果生成物")
        : context.t("任务尚未生成可展示结果，请稍后手动刷新");
      root.append(hint);
    }
    return root;
  }

  window.FTTestRunResults = Object.freeze({
    evaluationPlan, planSummary, recordDetail, refresh, render, resultSection,
  });
})();
