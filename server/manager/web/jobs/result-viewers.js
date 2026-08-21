(() => {
  function group(job, artifacts = [], result = null) {
    const kind = String(job?.kind || job?.job_type || job?.application || "")
      .toLowerCase();
    if (kind.includes("factor_evaluation")
      || (kind.includes("factor") && kind.includes("series"))) {
      return "job-detail-factor-series";
    }
    if (kind.includes("ic") || kind.includes("information_coefficient")) {
      return "job-detail-ic";
    }
    if (kind.includes("backtest") || kind.includes("group_test")
      || kind.includes("portfolio")) {
      return "job-detail-backtest";
    }
    const names = new Set((artifacts || []).map(
      item => String(item.name || "").toLowerCase(),
    ));
    if ([...names].some(name => (
      name.startsWith("ic_") || name.includes("ic_statistics")
    ))) return "job-detail-ic";
    if ([...names].some(name => (
      name.includes("equity") || name.includes("margin")
        || name.includes("group_execution")
    ))) return "job-detail-backtest";
    if (result && typeof result === "object"
      && (result.equity_curve || result.portfolios || result.groups)) {
      return "job-detail-backtest";
    }
    return "";
  }

  async function loadGroup(job, artifacts, result) {
    const name = group(job, artifacts, result);
    if (name) await window.FTStaticLoader?.loadGroups?.([name]);
    return name;
  }

  function domainSections(context, options) {
    const content = document.createDocumentFragment();
    const common = {
      artifacts: options.activeArtifacts,
      jobID: options.jobID,
      artifactQuery: options.artifactQuery,
      portQuery: options.executionQuery,
      configuration: options.taskDetail.configuration || {},
      customAnalyses: options.customAnalyses,
    };
    const factorSeries = window.FTFactorSeriesResults?.section(context, {
      ...common,
      jobKind: options.job.kind,
      resultSummary: options.results || options.payload.result_summary || {},
    });
    if (factorSeries) content.append(factorSeries);
    const icResults = window.FTICResults?.section(context, common);
    if (icResults) content.append(icResults);
    const backtestResults = window.FTBacktestResults?.section(context, {
      ...common,
      resultSummary: options.payload.result_summary
        || options.taskDetail.results?.summary || {},
      job: options.job,
      supplementalRequest:
        options.customAnalyses?.state?.requestedSupplemental || null,
    });
    if (backtestResults) content.append(backtestResults);
    return content;
  }

  function genericSection(context, options) {
    const root = document.createElement("section");
    root.className = "job-section generic-job-results";
    const state = options.state || {activeTab: "result"};
    const render = () => {
      const customTabs = options.customAnalyses?.tabs({
        onDeleted: () => { state.activeTab = "result"; render(); },
      }) || [];
      const header = FTJobResultTabs.create(context, {
        tabs: [{key: "result", label: "结果"}, ...customTabs],
        active: state.activeTab,
        onChange: async key => {
          if (key === "custom-analysis:new") {
            try {
              const analysis = await options.customAnalyses.add();
              state.activeTab = options.customAnalyses.keyFor(analysis.tab_id);
            } catch (error) {
              context.showNotice?.(error.message || String(error), true);
            }
          } else state.activeTab = key;
          render();
        },
      }).header;
      const content = document.createElement("div");
      content.className = "generic-job-result-content";
      const customID = options.customAnalyses?.tabIDFor(state.activeTab);
      if (customID) {
        options.customAnalyses.render(customID, content, {
          onTabsChanged: render,
          onDeleted: () => { state.activeTab = "result"; render(); },
        });
      } else {
        for (const declaration of options.declarations) {
          const artifacts = FTJobArtifacts.declarationArtifacts(
            declaration, options.activeArtifacts,
          );
          if (artifacts.length) content.append(FTJobArtifacts.lazyArtifactPreview(
            context, declaration, artifacts, options.jobID, options.artifactQuery,
          ));
        }
        if (options.results != null) content.append(FTJobArtifacts.collapsible(
          context.t("结果预览"), FTUI.code(options.results),
        ));
        if (options.results == null && !options.declarations.length) {
          content.append(FTUI.empty(
            context.t("暂无测试结果"), context.t("任务尚未生成可展示的结果"),
          ));
        }
      }
      root.replaceChildren(header, content);
    };
    render();
    return root;
  }

  window.FTJobResultViewers = Object.freeze({
    domainSections, genericSection, group, loadGroup,
  });
})();
