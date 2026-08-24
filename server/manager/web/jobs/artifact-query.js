(() => {
  const retryDelays = [200, 600];

  function endpoint(path) {
    const origin = window.location.origin && window.location.origin !== "null"
      ? window.location.origin : "http://localhost";
    const url = new URL(path, origin);
    url.pathname = url.pathname.replace(/\/$/, "") + "/query";
    return url.pathname + url.search;
  }

  function retryable(error, signal) {
    if (signal?.aborted || error?.name === "AbortError") return false;
    return [502, 503, 504].includes(Number(error?.status))
      || error?.name === "TypeError" || error?.name === "NetworkError";
  }

  async function query(context, path, request, options = {}) {
    for (let attempt = 0; ; attempt += 1) {
      try {
        const payload = await context.api(endpoint(path), {
          method: "POST",
          body: JSON.stringify(request || {}),
          signal: options.signal,
        });
        return payload?.data || {};
      } catch (error) {
        if (attempt >= retryDelays.length || !retryable(error, options.signal)) {
          throw error;
        }
        await new Promise(resolve => setTimeout(resolve, retryDelays[attempt]));
      }
    }
  }

  function tableSource(context, path, options = {}) {
    const pageSize = Math.max(1, Number(options.pageSize) || 20);
    return Object.freeze({
      async page(page, request = {}) {
        return query(context, path, {
          ...request, mode: "table", page, page_size: pageSize,
        });
      },
    });
  }

  function timeSource(context, path, options = {}) {
    let controller = null;
    let generation = 0;
    const mode = options.mode === "time_rows" ? "time_rows" : "series";
    const maximum = Math.max(20, Number(options.maxPoints) || 800);
    return Object.freeze({
      cancel() { generation += 1; controller?.abort(); controller = null; },
      async load(range = {}, request = {}) {
        const current = ++generation;
        controller?.abort();
        controller = new AbortController();
        const data = await query(context, path, {
          ...request,
          mode,
          max_points: Math.max(20, Number(range.maxPoints) || maximum),
          from: Number.isFinite(Number(range.min)) ? Number(range.min) : null,
          to: Number.isFinite(Number(range.max)) ? Number(range.max) : null,
        }, {signal: controller.signal});
        return current === generation ? data : null;
      },
    });
  }

  function pagedTable(context, data, options = {}) {
    const columns = Array.isArray(data?.columns) ? data.columns.map(String) : [];
    const rows = Array.isArray(data?.rows) ? data.rows : [];
    const renderCell = options.renderCell || (value => document.createTextNode(
      String(value ?? ""),
    ));
    const values = rows.map(row => columns.map(key => renderCell(
      row?.[key], row, key, data?.column_presentations || {},
    )));
    const table = window.FTUI.pagedTable(
      columns.map(key => options.renderHeader?.(key) || context.t(key)),
      values,
      {
        remote: true,
        page: Number(data?.page) || 1,
        pageSize: Number(data?.page_size) || Number(options.pageSize) || 20,
        total: Number(data?.total) || rows.length,
        previousLabel: context.t("上一页"), nextLabel: context.t("下一页"),
        pageLabel: (current, total) => `${current} / ${total}`,
        totalLabel: total => `${context.t("共")} ${total} ${context.t("行")}`,
        onPageChange: options.onPageChange,
      },
    );
    options.className?.split(/\s+/).filter(Boolean).forEach(name => (
      table.shell.classList.add(name)
    ));
    return table.shell;
  }

  window.FTJobArtifactQuery = Object.freeze({
    endpoint, pagedTable, query, tableSource, timeSource,
  });
})();
