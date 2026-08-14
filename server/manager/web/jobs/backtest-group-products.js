(() => {
  const ui = () => window.FTBacktestAnalysisUI;
  const common = () => window.FTBacktestGroupDetailParts;

  function productName(product) {
    const value = typeof product === "string" ? product : product?.name || product?.alias;
    return String(value || "").trim();
  }

  function productDescription(product) {
    if (!product || typeof product === "string") return "—";
    const name = String(product.name || product.alias || "");
    const description = String(product.desc || product.description || "");
    return description && description !== name ? description : "—";
  }

  function productIdentity(product) {
    if (!product || typeof product === "string") return ui().product(product);
    const root = document.createElement("div");
    root.className = "backtest-product-identity";
    const name = document.createElement("span");
    name.textContent = String(product.name || product.alias || "—");
    root.append(name);
    const sources = Array.isArray(product.source_names) ? product.source_names : [];
    if (sources.length) {
      const detail = document.createElement("small");
      detail.textContent = sources.join("、");
      root.append(detail);
    }
    return root;
  }

  function roundTripFee(row) {
    const fee = row?.product?.fee || {};
    const declared = ui().finite(fee.total);
    if (declared != null) return declared;
    const open = ui().finite(fee.open);
    const close = ui().finite(fee.close_today ?? fee.close_yesterday ?? fee.close);
    return open == null || close == null ? null : open + close;
  }

  function feeCoverageClass(row) {
    const returnValue = ui().finite(row?.mean_active_contribution ?? row?.mean_return);
    const fee = roundTripFee(row);
    return returnValue != null && fee != null && returnValue > fee
      ? "backtest-fee-covered" : "";
  }

  function frequency(context, rows, options = {}) {
    const selectable = typeof options.onCreateDerived === "function";
    const selected = new Set((rows || []).filter(feeCoverageClass)
      .map(row => productName(row.product)).filter(Boolean));
    const columns = [
      {label: "产品", value: row => productIdentity(row.product)},
      {label: "产品描述", value: row => productDescription(row.product)},
      {label: "入组次数", value: row => ui().number(row.count, 0)},
      {label: "进入比例", value: row => ui().percent(row.frequency)},
      {label: "平均收益", value: row => ui().basisPoints(row.mean_return)},
      {label: "开仓费率", value: row => ui().basisPoints(row.product?.fee?.open)},
      {label: "平今费率", value: row => ui().basisPoints(row.product?.fee?.close_today)},
      {label: "平昨费率", value: row => ui().basisPoints(
        row.product?.fee?.close_yesterday ?? row.product?.fee?.close,
      )},
    ];
    if (selectable) columns.unshift({label: "选择", value: row => {
      const checkbox = document.createElement("input");
      const name = productName(row.product);
      Object.assign(checkbox, {type: "checkbox", checked: selected.has(name), disabled: !name});
      checkbox.addEventListener("change", () => (
        checkbox.checked ? selected.add(name) : selected.delete(name)
      ));
      return checkbox;
    }});
    const table = ui().table(context, columns, rows,
      {empty: "暂无产品进入频率", rowClass: feeCoverageClass});
    if (!selectable || !(rows || []).length) return table;
    const actions = document.createElement("div"); actions.className = "backtest-analysis-actions";
    const button = window.FTUI.actionButton(context.t("用所选品种建立派生组"),
      () => options.onCreateDerived([...selected]), {variant: "secondary"});
    const note = document.createElement("small");
    note.textContent = context.t("默认勾选平均收益覆盖一开一平手续费的品种");
    actions.append(button, note);
    return common().stack(actions, table);
  }

  function contributionTable(context, rows) {
    const first = rows?.[0] || {};
    const weighted = Boolean(first.product?.fee?._is_weighted || first.market_rule?._is_weighted);
    const table = ui().table(context, [
      {label: "产品", value: row => productIdentity(row.product)},
      {label: "描述", value: row => productDescription(row.product)},
      {label: "平均收益", value: row => ui().basisPoints(row.mean_return)},
      {label: "开仓费率", value: row => ui().basisPoints(row.product?.fee?.open)},
      {label: "平今费率", value: row => ui().basisPoints(row.product?.fee?.close_today)},
      {label: "平昨费率", value: row => ui().basisPoints(
        row.product?.fee?.close_yesterday ?? row.product?.fee?.close,
      )},
      {label: "合约乘数", value: row => ui().number(row.market_rule?.multiplier)},
      {label: "最小手数", value: row => ui().number(row.market_rule?.lot_size)},
      {label: "保证金率", value: row => ui().percent(row.market_rule?.margin_ratio)},
      {label: "活跃期数", value: row => ui().number(row.active_period_count, 0)},
      {label: "毛收益贡献", value: row => ui().percent(row.gross_contribution)},
      {label: "活跃期平均贡献", value: row => ui().basisPoints(row.mean_active_contribution)},
    ], rows, {empty: "暂无产品贡献", rowClass: feeCoverageClass});
    return weighted ? common().stack(
      common().note(context.t("费率与市场规则为持仓加权值")), table,
    ) : table;
  }

  function productAnalysis(context, value) {
    const byLevel = value?.by_level || {};
    const levels = ["products", "contracts"].filter(key => byLevel[key]);
    let level = levels.includes(value?.default_level) ? value.default_level : levels[0];
    if (!level) return contributionTable(context, value?.rows || []);
    const root = document.createElement("div"); root.className = "backtest-analysis-stack";
    const buttons = document.createElement("div"); buttons.className = "backtest-analysis-switch";
    const content = document.createElement("div");
    const render = () => {
      const current = byLevel[level] || {};
      [...buttons.children].forEach(button => button.classList.toggle(
        "active", button.dataset.level === level,
      ));
      content.replaceChildren(
        common().note(`${context.t("最强 1 项贡献正毛收益")} ${ui().percent(current.top1_positive_contribution_ratio)} · ${context.t("最强 3 项")} ${ui().percent(current.top3_positive_contribution_ratio)}`),
        Object.assign(document.createElement("h4"), {textContent: context.t("正贡献")}),
        contributionTable(context, current.top_products || []),
        Object.assign(document.createElement("h4"), {textContent: context.t("负贡献")}),
        contributionTable(context, current.bottom_products || []),
      );
    };
    levels.forEach(key => {
      const button = document.createElement("button"); button.type = "button";
      button.dataset.level = key; button.textContent = context.t(key === "products" ? "品种" : "合约");
      button.addEventListener("click", () => { level = key; render(); }); buttons.append(button);
    });
    root.append(buttons, content); render(); return root;
  }

  window.FTBacktestGroupDetailProducts = Object.freeze({
    contributionTable, feeCoverageClass, frequency, productAnalysis,
    productDescription, productIdentity, productName, roundTripFee,
  });
})();
