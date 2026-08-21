(() => {
  const PAGE_SIZE = 20;

  function kindLabel(value, context) {
    const labels = {
      backtest_strategy_analysis: "策略分析",
      custom_python_analysis: "自定义分析",
    };
    return context.t(labels[String(value || "")] || value || "补充任务");
  }

  function errorText(value) {
    if (!value) return "";
    if (typeof value === "string") return value;
    return String(value.message || value.code || "");
  }

  function create(context, options) {
    const root = document.createElement("section");
    root.className = "job-section job-supplementals";
    const toolbar = document.createElement("div");
    toolbar.className = "job-supplemental-toolbar";
    const search = document.createElement("input");
    search.type = "search";
    search.className = "input input-bordered";
    search.placeholder = context.t("搜索补充任务");
    const refresh = document.createElement("button");
    refresh.type = "button";
    refresh.className = "secondary-button";
    refresh.textContent = context.t("刷新");
    toolbar.append(search, refresh);
    const host = document.createElement("div");
    root.append(toolbar, host);
    let page = 1;
    let loading = false;
    let timer = null;

    async function load(targetPage = page) {
      if (loading) return;
      loading = true;
      page = Math.max(1, Number(targetPage) || 1);
      host.replaceChildren(FTUI.loading(context.t("正在读取补充任务…")));
      try {
        const params = new URLSearchParams({
          page: String(page), limit: String(PAGE_SIZE),
        });
        const query = search.value.trim();
        if (query) params.set("search", query);
        const route = `/api/jobs/${encodeURIComponent(options.jobID)}`
          + `/supplementals?${params}${options.artifactQuery
            ? `&${options.artifactQuery.slice(1)}` : ""}`;
        const payload = await context.api(route);
        const rows = (payload.jobs || []).map(job => [
          kindLabel(job.supplemental_kind, context),
          String(job.job_id || ""),
          FTJobListFormat.statusPill(job.status, context),
          FTJobListFormat.date(job.updated_at),
          errorText(job.error),
        ]);
        if (!rows.length && !Number(payload.total || 0)) {
          host.replaceChildren(FTUI.empty(
            context.t("暂无补充任务"),
            context.t("按需分析会在这里显示运行历史"),
          ));
          return;
        }
        const view = FTUI.pagedTable([
          context.t("类型"), context.t("任务 ID"), context.t("状态"),
          context.t("更新时间"), context.t("错误"),
        ], rows, {
          remote: true, page, pageSize: Number(payload.page_size || PAGE_SIZE),
          total: Number(payload.total || 0),
          previousLabel: context.t("上一页"), nextLabel: context.t("下一页"),
          pageLabel: (current, total) => `${current} / ${total}`,
          totalLabel: total => `${context.t("共")} ${total}`,
          onPageChange: load,
        });
        host.replaceChildren(view.shell);
      } catch (error) {
        host.replaceChildren(FTUI.empty(
          context.t("补充任务读取失败"), error.message || String(error),
        ));
      } finally {
        loading = false;
      }
    }

    search.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(() => load(1), 250);
    });
    refresh.addEventListener("click", () => load(page));
    return {root, load};
  }

  window.FTJobSupplementals = Object.freeze({create});
})();
