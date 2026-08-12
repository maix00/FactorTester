(() => {
  function jobPath(options, suffix) {
    const jobID = encodeURIComponent(String(options?.jobID || ""));
    if (!jobID) throw new Error("缺少 Job ID");
    return `/api/jobs/${jobID}/${suffix}${options?.portQuery || ""}`;
  }

  async function request(context, options, suffix, payload) {
    const value = await context.api(jobPath(options, suffix), {
      method: "POST",
      body: JSON.stringify(payload || {}),
    });
    if (value?.success === false) throw new Error(value.error || "分析请求失败");
    return value || {};
  }

  const detail = (context, options, payload) => (
    request(context, options, "group-detail", payload).then(value => value.detail || {})
  );
  const ranking = (context, options, payload) => (
    request(context, options, "group-ranking-detail", payload)
      .then(value => value.detail || {})
  );
  const snapshot = (context, options, payload) => (
    request(context, options, "group-snapshot", payload)
  );
  const orderFlow = (context, options, payload) => (
    request(context, options, "group-order-flow", payload)
  );

  window.FTBacktestAnalysisAPI = Object.freeze({
    detail, jobPath, orderFlow, ranking, request, snapshot,
  });
})();
