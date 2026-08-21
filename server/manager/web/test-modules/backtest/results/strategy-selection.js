(() => {
  const ALL_STRATEGIES = "__all_strategies__";

  function label(value) {
    return String(value?.label || value?.display_name || value?.name || value || "").trim();
  }

  function id(value) {
    return String(value?.id || value?.strategyID || value?.strategy_id || label(value)).trim();
  }

  function items(strategies = []) {
    return [
      {
        value: ALL_STRATEGIES,
        label: "全部策略",
        description: "显示所有策略的结果",
        exclusive: true,
      },
      ...strategies.map(value => {
        const strategyLabel = label(value);
        return {
          value: id(value),
          label: strategyLabel,
          description: `仅显示策略 ${strategyLabel} 的结果`,
        };
      }).filter(item => item.value),
    ];
  }

  function normalize(values, strategies = []) {
    const available = new Set(strategies.map(id).filter(Boolean));
    const selected = [...new Set((Array.isArray(values) ? values : [values])
      .map(value => String(value || "").trim()).filter(Boolean))];
    if (!selected.length || selected.includes(ALL_STRATEGIES)) return [ALL_STRATEGIES];
    const retained = selected.filter(value => available.has(value));
    return retained.length ? retained : [ALL_STRATEGIES];
  }

  function rowStrategy(row) {
    return String(
      row?.strategy_id || row?.strategy_ref || row?.strategy || row?.series || "",
    ).trim();
  }

  function createScope(strategies = [], values = []) {
    const selected = normalize(values, strategies);
    const selectedSet = selected.includes(ALL_STRATEGIES) ? null : new Set(selected);
    const aliases = new Map();
    strategies.forEach(strategy => {
      aliases.set(id(strategy), id(strategy));
      aliases.set(label(strategy), id(strategy));
    });
    const allows = value => {
      const raw = label(value);
      const strategy = aliases.get(raw) || raw;
      return !selectedSet || !strategy || strategy === "__aggregate__"
        || selectedSet.has(strategy);
    };
    const filterRows = (rows = [], scope = rowStrategy) => (
      (Array.isArray(rows) ? rows : []).filter(row => allows(scope(row)))
    );
    const filterPayload = payload => {
      if (!payload || typeof payload !== "object") return payload;
      const result = {...payload};
      if (Array.isArray(payload.series)) {
        result.series = payload.series.filter(item => allows(
          item?.strategy_id || item?.strategy_ref || item?.label || item?.series,
        ));
      }
      if (Array.isArray(payload.rows)) result.rows = filterRows(payload.rows);
      return result;
    };
    return Object.freeze({
      all: !selectedSet,
      selected,
      allows,
      filterEntries: entries => (entries || []).filter(entry => allows(label(entry))),
      filterPayload,
      filterRows,
    });
  }

  function control(context, options = {}) {
    const strategies = Array.isArray(options.strategies) ? options.strategies : [];
    const selected = normalize(options.selected, strategies);
    return window.FTMultiSelectFilter.create(context, {
      title: context.t("策略"),
      compact: true,
      multi: true,
      className: "backtest-result-strategy-filter",
      items: items(strategies).map(item => ({
        ...item,
        label: context.t(item.label),
        description: context.t(item.description),
      })),
      selected,
      searchPlaceholder: context.t("搜索策略…"),
      onApply: values => options.onApply?.(normalize(values, strategies)),
    });
  }

  window.FTBacktestStrategySelection = Object.freeze({
    ALL_STRATEGIES, control, createScope, items, normalize, rowStrategy,
  });
})();
