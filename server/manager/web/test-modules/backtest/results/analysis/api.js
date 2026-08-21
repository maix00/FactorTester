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

  function storagePath(options, suffix) {
    const jobID = encodeURIComponent(String(options?.jobID || ""));
    if (!jobID) throw new Error("缺少 Job ID");
    return `/api/jobs/${jobID}/${suffix}${options?.artifactQuery || options?.portQuery || ""}`;
  }

  function delay(milliseconds) {
    return new Promise(resolve => setTimeout(resolve, milliseconds));
  }

  async function waitForSupplemental(context, options, job) {
    const childID = encodeURIComponent(String(job?.job_id || ""));
    if (!childID) throw new Error("补充任务缺少 Job ID");
    for (;;) {
      const value = await context.api(storagePath(
        options, `supplementals/${childID}`,
      ));
      const child = value?.job || {};
      if (child.status === "succeeded") return value;
      if (["failed", "cancelled"].includes(child.status)) {
        const error = value?.error;
        throw new Error(
          error?.message || error?.code || context.t("补充分析失败"),
        );
      }
      await delay(500);
    }
  }

  async function loadSupplementalArtifact(context, options, artifact) {
    const name = String(artifact?.name || artifact?.artifact_name || "");
    if (!name) throw new Error(context.t("补充分析未返回生成物"));
    const response = await FTJobArtifacts.fetch(
      context,
      storagePath(options, `artifacts/${encodeURIComponent(name)}`),
    );
    return JSON.parse(await response.text());
  }

  async function supplemental(context, options, params) {
    const created = await context.api(storagePath(options, "supplementals"), {
      method: "POST",
      body: JSON.stringify({kind: "backtest_strategy_analysis", params}),
    });
    if (created?.success === false) {
      throw new Error(created.error || context.t("补充分析请求失败"));
    }
    if (created.artifact) {
      return loadSupplementalArtifact(context, options, created.artifact);
    }
    const completed = await waitForSupplemental(context, options, created.job);
    const result = completed?.result_summary || {};
    const artifactName = result?.artifact_names?.[String(params?.analysis_tab || "")]
      || result?.artifact_name;
    return loadSupplementalArtifact(context, options, {name: artifactName});
  }

  const detail = (context, options, payload) => (
    supplemental(context, options, payload)
  );
  const ranking = (context, options, payload) => (
    supplemental(context, options, {...payload, analysis_tab: "ranking"})
  );
  const snapshot = (context, options, payload) => (
    request(context, options, "group-snapshot", payload)
  );
  const orderFlow = (context, options, payload) => (
    request(context, options, "group-order-flow", payload)
  );

  window.FTBacktestAnalysisAPI = Object.freeze({
    detail, jobPath, orderFlow, ranking, request, snapshot, supplemental,
  });
})();
