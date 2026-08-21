(() => {
  function errorNode(error) {
    return Object.assign(document.createElement("p"), {
      className: "backtest-domain-empty",
      textContent: error?.message || String(error || ""),
    });
  }

  function tabButton(context, label, active, action) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = context.t(label);
    button.classList.toggle("active", active);
    button.addEventListener("click", action);
    return button;
  }

  function open(context, options, entry) {
    const summary = options.resultSummary || {};
    const related = FTBacktestResultModel.relatedGroupEntries(summary, entry);
    const entries = related.length ? related : [entry];
    const view = FTBacktestAnalysisUI.dialog(context, "策略分析", entries[0]?.label || "");
    const navigation = document.createElement("div");
    navigation.className = "backtest-analysis-switch backtest-strategy-analysis-tabs";
    const content = document.createElement("div");
    content.className = "backtest-strategy-analysis-content";
    const cache = new Map();
    let activeTab = "detail";
    let activeEntry = entries.find(item => item.key === entry?.key) || entries[0];

    async function renderDetail(target) {
      const key = `detail:${activeEntry.key}`;
      if (!cache.has(key)) {
        cache.set(key, FTBacktestGroupDetail.load(context, options, activeEntry));
      }
      FTBacktestGroupDetail.render(
        context, target, await cache.get(key), options, activeEntry,
      );
    }

    async function renderRanking(target) {
      const key = `ranking:${FTBacktestResultModel.diagnosticKey(activeEntry, summary)}`;
      if (!cache.has(key)) {
        cache.set(key, FTBacktestRankingView.load(context, options, activeEntry));
      }
      FTBacktestRankingView.render(context, target, await cache.get(key));
    }

    function render() {
      navigation.replaceChildren(
        tabButton(context, "分组详情", activeTab === "detail", () => {
          activeTab = "detail"; render();
        }),
        tabButton(context, "排序诊断", activeTab === "ranking", () => {
          activeTab = "ranking"; render();
        }),
      );
      content.replaceChildren(FTUI.loading(context.t(
        activeTab === "detail" ? "正在读取分组详情…" : "正在读取排序诊断…",
      )));
      const target = document.createElement("div");
      target.className = "backtest-strategy-analysis-pane";
      const task = activeTab === "detail" ? renderDetail(target) : renderRanking(target);
      task.then(() => content.replaceChildren(target))
        .catch(error => content.replaceChildren(errorNode(error)));
    }

    if (entries.length > 1) {
      const strategies = document.createElement("div");
      strategies.className = "backtest-analysis-switch backtest-strategy-analysis-entries";
      entries.forEach(candidate => strategies.append(tabButton(
        context, candidate.label, candidate.key === activeEntry.key, () => {
          activeEntry = candidate;
          [...strategies.children].forEach((button, index) => {
            button.classList.toggle("active", entries[index].key === activeEntry.key);
          });
          if (activeTab === "detail") render();
        },
      )));
      view.body.append(strategies);
    }
    view.body.append(navigation, content);
    render();
    return view;
  }

  window.FTBacktestStrategyAnalysis = Object.freeze({open});
})();
