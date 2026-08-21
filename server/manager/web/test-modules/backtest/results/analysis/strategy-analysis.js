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
    const detailTabs = FTBacktestGroupDetail.tabs || [{id: "overview", label: "概览"}];
    const allTabs = [...detailTabs, {id: "ranking", label: "排序诊断"}];
    let activeTab = detailTabs[0].id;
    let activeEntry = entries.find(item => item.key === entry?.key) || entries[0];

    async function renderDetail(target) {
      const key = `detail:${activeEntry.key}:${activeTab}`;
      if (!cache.has(key)) {
        cache.set(key, FTBacktestGroupDetail.load(
          context, options, activeEntry, activeTab,
        ));
      }
      FTBacktestGroupDetail.renderTab(
        context, target, await cache.get(key), activeTab, options, activeEntry,
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
      navigation.replaceChildren(...allTabs.map(tab => tabButton(
        context, tab.label, activeTab === tab.id, () => {
          activeTab = tab.id; render();
        },
      )));
      content.replaceChildren(FTUI.loading(context.t(
        activeTab === "ranking" ? "正在读取排序诊断…" : "正在读取策略分析…",
      )));
      const target = document.createElement("div");
      target.className = "backtest-strategy-analysis-pane";
      const task = activeTab === "ranking" ? renderRanking(target) : renderDetail(target);
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
          if (activeTab !== "ranking") render();
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
