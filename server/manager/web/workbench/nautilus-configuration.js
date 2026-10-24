(() => {
  const BACKEND = "nautilus_trader";
  const SECTIONS = Object.freeze([
    {key: "research", label: "研究与数据", fields: [
      "data_source_mode", "data_source", "freq_mode", "freq_fixed", "historical_field_policy",
      "product_path_selection", "product_path_selection_id", "start_date", "end_date",
      "start_time", "end_time", "timezone", "evaluation_split", "signal_freq",
      "basepoint", "daily_basepoint", "calendar_frequency", "warmup_mode", "warmup_window",
    ]},
    {key: "factor", label: "因子与策略", fields: [
      "factor_candidate_refs", "factor_role_bindings", "strategy_bindings", "strategy_intent_mode",
      "split_count", "group_index", "screen_rule", "screen_lower", "screen_upper",
      "threshold_mode", "entry_threshold", "exit_threshold", "quantile_entry",
      "quantile_exit", "side_mode", "term_carry_near_rank", "term_carry_far_rank",
      "term_carry_entry_threshold", "term_carry_exit_threshold", "term_carry_gross_weight",
      "position_policy", "rebalance_trigger", "allocation_policy", "sizing_transform",
    ]},
    {key: "account", label: "账户资金", fields: [
      "initial_capital_major", "base_currency",
      "ledger_session_policy", "cash_reserve_ratio", "cash_reserve_major",
      "target_margin_utilization", "max_margin_utilization", "margin_mode", "fixed_margin_ratio",
      "collateral_fraction", "daily_mark_to_market_enabled", "cost_basis_method",
    ]},
    {key: "execution", label: "费用、撮合与风控", fields: [
      "fee_mode", "transaction_fee_source", "fixed_fee_rate", "fee_custom_product_fields",
      "slippage_mode", "slippage_bps", "order_type", "matching_model", "liquidity_mode",
      "participation_rate", "volume_execution_price_basis", "quantity_rounding_policy",
      "margin_call_mode", "liquidation_target_buffer", "force_close_before_expiry",
      "rollover_policy", "rollover_before_expiry", "bar_open_visibility_delay",
      "bar_end_visibility_delay", "end_session_skip", "end_session_gap",
    ]},
    {key: "audit", label: "结果与审计", fields: [
      "retention_mode", "output_requests", "step_mode", "performance_profile",
      "margin_execution_profile", "equity_compute_live", "engine", "engine_mode",
      "counterparty_profile", "accounting_mode", "custom_product_fields",
    ]},
  ]);
  const fieldSection = new Map(SECTIONS.flatMap(section => (
    section.fields.map(key => [key, section.key])
  )));
  const STATUS = Object.freeze({
    nt_native: "NT 原生", ft_adapter: "FT 适配", mapped: "已映射",
    not_applicable: "不适用", unsupported: "未支持",
  });
  const capabilityRequests = new WeakMap();
  const capabilityErrors = new WeakMap();
  const capabilityCache = new WeakMap();

  function backend(state) {
    return state?.executionBackend || state?.analysis?.execution?.backend || "legacy";
  }

  function enabled(state) { return state?.kind === "backtest" && backend(state) === BACKEND; }

  function loadCapabilities(context) {
    const path = context.servicePath("/api/nautilus/capabilities");
    let byPath = capabilityCache.get(context);
    if (!byPath) {
      byPath = new Map();
      capabilityCache.set(context, byPath);
    }
    if (!byPath.has(path)) {
      const request = context.api(path).catch(error => {
        byPath.delete(path);
        throw error;
      });
      byPath.set(path, request);
    }
    return byPath.get(path);
  }

  function ensureCapabilities(context, state, refresh) {
    if (!enabled(state) || state.nautilusCapabilities
        || capabilityErrors.has(state) || capabilityRequests.has(state)) return;
    const request = loadCapabilities(context).then(capabilities => {
      state.nautilusCapabilities = capabilities;
      capabilityErrors.delete(state);
      refresh?.();
    }).catch(error => {
      capabilityErrors.set(state, error.message || String(error));
      refresh?.();
    }).finally(() => capabilityRequests.delete(state));
    capabilityRequests.set(state, request);
  }

  function fingerprint(state) {
    return JSON.stringify([
      backend(state), state?.values || {}, state?.analysis?.groups || [],
      state?.analysis?.venues || [], state?.analysis?.strategy_venue_bindings || [],
      state?.strategyBindings || [], state?.runValues || {},
    ]);
  }

  function formatValue(value) {
    if (value === null || value === undefined || value === "") return "—";
    if (typeof value === "string") return value;
    if (Array.isArray(value)) return value.length ? value.map(formatValue).join("、") : "—";
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  }

  function candidateRows(state, manifest) {
    const settings = window.FTTestConfigurationCompiler?.executionSettings?.(
      manifest, state?.values || {},
    ) || {};
    const rows = Object.entries(settings).map(([key, value]) => ({
      path: `execution.nautilus.${key}`, key, value,
    }));
    const groups = state?.analysis?.groups || [];
    groups.forEach((group, index) => {
      for (const key of ["factor_candidate_refs", "factor_role_bindings",
        "product_path_selection", "strategy_intent_mode", "strategy_template_ref"]) {
        if (group?.[key] !== undefined) rows.push({
          path: `groups[${index}].${key}`, key, value: group[key],
        });
      }
    });
    rows.push({path: "groups", key: "groups", value: `${groups.length} 个策略组`});
    const venues = state?.analysis?.venues || [];
    const routes = state?.analysis?.strategy_venue_bindings || [];
    rows.push({path: "execution.venue_count", key: "venues", value: `${venues.length} 个 Venue 账户`});
    rows.push({
      path: "execution.strategy_route_count", key: "strategy_venue_bindings",
      value: `${routes.length} 个策略路由`,
    });
    return rows;
  }

  function reviewState(state) {
    const review = state?.nautilusReview;
    if (!review) return {status: "unchecked", response: null};
    if (review.fingerprint !== fingerprint(state)) return {status: "stale", response: null};
    return review;
  }

  async function validateServer(context, state, group) {
    if (!enabled(state)) throw new Error("当前未选择 NautilusTrader 执行内核");
    state.nautilusReview = {status: "loading", fingerprint: fingerprint(state), response: null};
    let expected = "";
    try {
      await window.FTTests?.ensureFactorsForExecution?.(context, state);
      await window.FTTests?.ensureProductsForExecution?.(context, state);
      const configuration = window.FTTestConfiguration.configurationPayload(state, group);
      expected = fingerprint(state);
      state.nautilusReview.fingerprint = expected;
      const capabilities = await loadCapabilities(context);
      state.nautilusCapabilities = capabilities;
      capabilityErrors.delete(state);
      const response = await context.api(context.servicePath("/api/nautilus/config/preview"), {
        method: "POST",
        body: JSON.stringify({
          analysis_kind: "backtest", configuration,
          run_options: window.FTTestRunFields?.requestBody?.(state) || {},
        }),
      });
      if (fingerprint(state) !== expected) throw new Error("配置在检查期间已变更，请重新检查");
      if (response?.engine !== BACKEND || !Array.isArray(response?.fields)
        || !Array.isArray(response?.blockers) || typeof response?.ready !== "boolean") {
        throw new Error("服务端未返回有效的 NautilusTrader 配置审查结果");
      }
      const canSubmit = capabilities?.backtest_submission?.available === true;
      const result = {
        ...response,
        ready: response.ready === true && response.blockers.length === 0 && canSubmit,
        blockers: canSubmit ? response.blockers : [
          ...response.blockers,
          {path: "execution.backend", reason: "服务端尚未启用 NautilusTrader 回测提交"},
        ],
      };
      state.nautilusReview = {status: "ready", fingerprint: expected, response: result};
      return result;
    } catch (error) {
      if ((!expected || fingerprint(state) === expected) && enabled(state)) state.nautilusReview = {
        status: "error", fingerprint: expected, error: error.message || String(error),
      };
      throw error;
    }
  }

  async function requireReady(context, state, group) {
    if (!enabled(state)) return;
    const response = await validateServer(context, state, group);
    if (!response.ready) {
      throw new Error(response.blockers.map(item => item.reason).filter(Boolean)
        .join("；") || "NautilusTrader 有未支持的执行配置");
    }
  }

  function render(context, state, manifest, options = {}) {
    if (state?.kind !== "backtest") return null;
    ensureCapabilities(context, state, options.refresh);
    const root = document.createElement("section");
    root.className = "nautilus-config-review";
    const head = document.createElement("div");
    head.className = "nautilus-config-review-head";
    const title = document.createElement("strong");
    title.textContent = context.t("执行内核与有效配置");
    const choices = document.createElement("div");
    choices.className = "nautilus-config-review-choices";
    for (const [value, label] of [["legacy", "现有回测"], [BACKEND, "NautilusTrader"]]) {
      const choice = context.button(context.t(label), () => {
        state.executionBackend = value;
        state.nautilusReview = null;
        options.refresh?.();
      });
      choice.classList.toggle("active", backend(state) === value);
      choice.setAttribute("aria-pressed", String(backend(state) === value));
      choices.append(choice);
    }
    head.append(title, choices);
    root.append(head);
    if (!enabled(state)) return root;

    const notice = document.createElement("p");
    notice.className = "nautilus-config-review-note";
    notice.textContent = context.t(
      "可保存尚未就绪的配置草稿；提交 NautilusTrader 任务前，服务端必须确认全部执行能力。",
    );
    root.append(notice);
    const capabilityError = capabilityErrors.get(state);
    if (capabilityError) {
      const error = document.createElement("p");
      error.className = "nautilus-config-review-note";
      error.textContent = `${context.t("读取 Nautilus 能力目录失败")}: ${capabilityError}`;
      root.append(error);
    }
    const schema = state.nautilusCapabilities?.simulated_venue_config;
    if (Array.isArray(schema?.parameter_coverage)) {
      const coverage = document.createElement("details");
      coverage.className = "nautilus-config-review-section";
      const summary = document.createElement("summary");
      summary.textContent = context.t("Nautilus add_venue 参数映射到 RunSpec");
      const rows = document.createElement("div");
      rows.className = "nautilus-config-review-rows";
      for (const item of schema.parameter_coverage) {
        const line = document.createElement("div");
        line.className = "nautilus-config-review-row nautilus-config-capability-row";
        const label = document.createElement("span");
        label.textContent = String(item.parameter || "");
        const value = document.createElement("span");
        value.textContent = `${item.native_parameters ? `${item.native_parameters} → ` : ""}`
          + String(item.runspec_path || "—");
        const status = document.createElement("span");
        status.className = `nautilus-config-review-status ${item.status || "pending"}`;
        status.textContent = context.t(STATUS[item.status] || "待映射");
        const note = document.createElement("span");
        note.className = "nautilus-config-capability-note";
        note.textContent = String(item.note || schema.excluded?.[item.parameter] || "");
        line.append(label, value, status, note);
        rows.append(line);
      }
      coverage.append(summary, rows);
      root.append(coverage);
    }
    if (Array.isArray(schema?.execution_policy_coverage)) {
      const coverage = document.createElement("details");
      coverage.className = "nautilus-config-review-section";
      const summary = document.createElement("summary");
      summary.textContent = context.t("Nautilus 执行语义参数映射到 RunSpec");
      const rows = document.createElement("div");
      rows.className = "nautilus-config-review-rows";
      for (const item of schema.execution_policy_coverage) {
        const line = document.createElement("div");
        line.className = "nautilus-config-review-row nautilus-config-capability-row";
        const label = document.createElement("span");
        label.textContent = String(item.parameter || "");
        const value = document.createElement("span");
        value.textContent = `${item.native_parameters ? `${item.native_parameters} → ` : ""}`
          + String(item.runspec_path || "—");
        const status = document.createElement("span");
        status.className = `nautilus-config-review-status ${item.status || "pending"}`;
        status.textContent = context.t(STATUS[item.status] || "待映射");
        const note = document.createElement("span");
        note.className = "nautilus-config-capability-note";
        note.textContent = String(item.note || "");
        line.append(label, value, status, note);
        rows.append(line);
      }
      coverage.append(summary, rows);
      root.append(coverage);
    }
    const review = reviewState(state);
    const response = review.response || {};
    const serverFields = new Map((response.fields || []).map(item => [item.path, item]));
    const sectionRoots = new Map();
    for (const section of SECTIONS) {
      const details = document.createElement("details");
      details.className = "nautilus-config-review-section";
      details.open = section.key === "research" || section.key === "execution";
      const summary = document.createElement("summary");
      summary.textContent = context.t(section.label);
      const rows = document.createElement("div");
      rows.className = "nautilus-config-review-rows";
      details.append(summary, rows);
      root.append(details);
      sectionRoots.set(section.key, rows);
    }
    const candidates = candidateRows(state, manifest);
    const seen = new Set();
    for (const row of [...candidates, ...(response.fields || [])]) {
      if (!row?.path || seen.has(row.path)) continue;
      seen.add(row.path);
      const key = row.key || row.path.split(".").pop();
      const field = serverFields.get(row.path) || row;
      const line = document.createElement("div");
      line.className = "nautilus-config-review-row";
      const label = document.createElement("span");
      label.textContent = context.t(field.label || manifest?.defaults?.[key]?.label || key);
      const value = document.createElement("span");
      value.textContent = formatValue(field.value === undefined ? row.value : field.value);
      const status = document.createElement("span");
      status.className = `nautilus-config-review-status ${field.status || "pending"}`;
      status.textContent = context.t(STATUS[field.status] || "待服务端核验");
      if (field.reason) status.title = String(field.reason);
      line.append(label, value, status);
      const section = field.review_section || fieldSection.get(key) || "audit";
      sectionRoots.get(sectionRoots.has(section) ? section : "audit").append(line);
    }
    for (const rows of sectionRoots.values()) {
      if (rows.childElementCount) continue;
      const empty = document.createElement("p");
      empty.textContent = context.t("此组暂未设置");
      rows.append(empty);
    }
    if (review.status === "ready") {
      const resolved = document.createElement("details");
      resolved.className = "nautilus-config-review-effective";
      const summary = document.createElement("summary");
      summary.textContent = context.t("服务端解析的完整有效配置");
      const source = document.createElement("pre");
      source.textContent = JSON.stringify(response.effective_configuration || {}, null, 2);
      resolved.append(summary, source);
      root.append(resolved);
    }
    const actions = document.createElement("div");
    actions.className = "nautilus-config-review-actions";
    const check = context.button(context.t("检查有效配置"), () => {
      check.disabled = true;
      void validateServer(context, state, options.group?.() || {id: "__backtest__"}).catch(error => {
        context.showNotice?.(`${context.t("配置检查失败")}: ${error.message}`, true);
      }).finally(() => {
        check.disabled = false;
        options.refresh?.();
      });
    });
    check.disabled = review.status === "loading";
    const result = document.createElement("span");
    result.className = "nautilus-config-review-result";
    if (review.status === "error") result.textContent = review.error;
    else if (review.status === "stale") result.textContent = context.t("配置已更改，请重新检查");
    else if (review.status === "ready") result.textContent = response.ready
      ? context.t("配置已通过服务端检查")
      : (response.blockers || []).map(item => item.reason).join("；");
    else result.textContent = context.t("尚未进行服务端检查");
    actions.append(check, result);
    root.append(actions);
    return root;
  }

  window.FTNautilusConfiguration = Object.freeze({
    backend, candidateRows, enabled, fingerprint, loadCapabilities, render, requireReady, validateServer,
  });
})();
