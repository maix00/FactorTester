(() => {
  function rows(summary = {}) {
    const result = [];
    const defaults = (Array.isArray(summary.silent_default_settings)
      ? summary.silent_default_settings : []).flatMap(item => {
      const label = String(item?.label || item?.setting_key || item?.module || "");
      const value = String(item?.value_label ?? item?.value ?? item?.applied_value ?? "");
      return label && value ? [`${label}: ${value}`] : [];
    });
    if (defaults.length) {
      result.push({type: "当前运行配置", status: "默认", detail: defaults.join("；")});
    }
    const fallbacks = (Array.isArray(summary.setting_fallbacks)
      ? summary.setting_fallbacks : []).flatMap(item => {
      const label = String(item?.setting_key || item?.module || "");
      if (!label) return [];
      return [`${label}: ${String(item.requested_value)} → ${String(item.applied_value)}`];
    });
    if (summary.setting_fallback_warning || fallbacks.length) {
      result.push({
        type: "默认值替换", status: "已使用默认值",
        detail: [summary.setting_fallback_warning, ...fallbacks].filter(Boolean).join("；"),
      });
    }
    result.push(...(Array.isArray(summary.runtime_info_rows)
      ? summary.runtime_info_rows : []).flatMap(item => {
      if (!item || typeof item !== "object") return [];
      let detail = String(item.detail || item.message || "");
      if (!detail && Array.isArray(item.product_displays) && item.product_displays.length) {
        detail = `回测范围外产品: ${item.product_displays.map(product => (
          typeof product === "string" ? product
            : product.desc || product.name || product.alias || product.product || ""
        )).filter(Boolean).join("、")}`;
      }
      if (!detail) return [];
      const status = item.status || ({warning: "提示", error: "异常"}[item.level] || "信息");
      return [{type: String(item.type || "运行信息"), status: String(status), detail}];
    }));
    if (summary.capital_warning) {
      result.push({type: "资金约束", status: "提示", detail: String(summary.capital_warning)});
    }
    if (summary.market_rule_warning) {
      result.push({type: "市场规则", status: "近似", detail: String(summary.market_rule_warning)});
    }
    const diagnostics = summary.capital_diagnostics;
    if (diagnostics && typeof diagnostics === "object") {
      const details = [];
      if (diagnostics.blocked_group_count != null) {
        details.push(`未开仓组数: ${diagnostics.blocked_group_count}`);
      }
      const blocked = Array.isArray(diagnostics.blocked_groups)
        ? diagnostics.blocked_groups : [];
      if (blocked.length) {
        const sample = blocked[0] || {};
        const parts = [];
        if (sample.group_name) parts.push(`组 ${sample.group_name}`);
        if (sample.cheapest_product_name) {
          parts.push(`最便宜品种 ${sample.cheapest_product_name}`);
        }
        if (sample.cheapest_required_capital != null) {
          parts.push(`需求约 ${Math.round(Number(sample.cheapest_required_capital))}`);
        }
        if (sample.budget_per_product != null) {
          parts.push(`预算约 ${Math.round(Number(sample.budget_per_product))}`);
        }
        if (parts.length) details.push(parts.join("，"));
      }
      if (details.length) {
        result.push({type: "资金约束", status: "诊断", detail: details.join("；")});
      }
    }
    return result;
  }

  window.FTBacktestRuntimeModel = Object.freeze({rows});
})();
