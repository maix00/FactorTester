(() => {
  // A report's Job result special section (kind=special, display_kind=test_result,
  // component_id=job-<32 hex>-result) must show the **same** run-process-and-result
  // panel the test configuration page shows after a run, so this module renders it
  // through that page's own composition:
  //
  //   workbench/test-run-results.js → FTTestRunResults.render(context, state, item)
  //     ├─ workbench/test-run-progress.js → FTTestRunProgress.render  (任务进度)
  //     └─ FTJobResultViewers.resultSection → 按 job 类型的领域结果视图 (运行摘要/概览/策略统计 …)
  //
  // It owns no progress or result rendering of its own: a second renderer for the
  // same Job would drift from the test page the reader compares it against.
  const JOB_RESULT_COMPONENT_ID = /^job-([0-9a-f]{32})-result$/;
  // The test page's run panel lives in this lazy group.
  const RUN_RESULT_GROUP = "workbench-run-results";

  function t(context, key) {
    return context?.t?.(key) || key;
  }

  function jobResultID(component) {
    const raw = String(component?.component_id || component?.node_id || "")
      .trim().toLowerCase();
    const match = JOB_RESULT_COMPONENT_ID.exec(raw);
    return match ? match[1] : "";
  }

  function isJobResultSection(component) {
    return String(component?.kind || "") === "special"
      && String(component?.display_kind || "") === "test_result"
      && Boolean(jobResultID(component));
  }

  function bindingFor(context, jobID) {
    const target = `job:${jobID}`;
    return context?.referenceMeta?.[target]
      || Object.values(context?.bindingByID || {})
        .find(item => item?.target_ref === target)
      || null;
  }

  // The result section's binding is written with the Job and already carries the
  // execution port and server identity, so a federated Job is read through the
  // same reference the report's Job hyperlinks use.
  function jobReference(context, jobID) {
    const data = bindingFor(context, jobID)?.data || {};
    const port = Number(data.port);
    return {
      port: Number.isInteger(port) && port > 0 && port <= 65535 ? port : 0,
      serverID: String(data.server_id || data.execution_server_id || "").trim(),
    };
  }

  // The Job kind decides which domain result view the panel shows.  The binding
  // carries it when the mount recorded it; otherwise read it from the Job the
  // binding points at, exactly like the Job route resolves its own kind.
  function normalizeKind(value) {
    const raw = String(value || "").trim().toLowerCase();
    return window.FTTestTypeRegistry?.normalize?.(raw) || raw;
  }

  function jobKind(component, context, jobID) {
    const data = bindingFor(context, jobID)?.data || {};
    return normalizeKind(
      data.kind || data.job_type || data.application
      || component?.job_kind || component?.kind_hint || "",
    );
  }

  async function resolveKind(component, context, jobID) {
    const declared = jobKind(component, context, jobID);
    if (declared || typeof window.FTJobs?.loadDetail !== "function") return declared;
    const reference = jobReference(context, jobID);
    const loaded = await window.FTJobs.loadDetail(
      context, reference.port, jobID, reference.serverID,
    );
    const job = loaded?.job || loaded?.payload?.job || {};
    return normalizeKind(job.kind || job.job_type || loaded?.payload?.job_kind || "");
  }

  async function ensureRunPanel() {
    if (typeof window.FTTestRunResults?.render === "function") return true;
    await window.FTStaticLoader?.loadGroups?.([RUN_RESULT_GROUP]);
    return typeof window.FTTestRunResults?.render === "function";
  }

  function mount(component, context) {
    const jobID = jobResultID(component);
    const host = document.createElement("div");
    host.className = "report-job-result";
    if (!jobID) return host;
    const reference = jobReference(context, jobID);
    let rendered = false;

    const render = async () => {
      if (rendered) return;
      rendered = true;
      host.replaceChildren(FTUI.loading(t(context, "正在读取任务运行过程…")));
      try {
        if (!await ensureRunPanel()) {
          throw new Error(t(context, "测试运行面板不可用"));
        }
        const kind = await resolveKind(component, context, jobID);
        // Same call the test configuration page makes: state carries the test
        // kind, item carries the Job and the run progress bookkeeping.
        const state = { kind, jobID, port: reference.port, serverID: reference.serverID };
        const item = {
          jobID, port: reference.port, serverID: reference.serverID,
          phase: "", progressStreamClosed: false,
        };
        const panel = window.FTTestRunResults.render(
          context, state, item, () => host.__ftReportRerender?.(),
        );
        host.replaceChildren(panel);
        host.dataset.reportJobResult = "ready";
      } catch (error) {
        // An unavailable Job result is stated explicitly; a silently empty
        // section would read as "this Job has no result".
        host.dataset.reportJobResult = "error";
        host.replaceChildren(FTUI.empty(
          t(context, "结果查看器不可用"), error?.message || String(error || ""),
        ));
      }
    };

    host.__ftReportRerender = () => { rendered = false; void render(); };
    const dispose = window.FTReportLazyRuntime?.observe?.(host, context, () => void render());
    if (!dispose) void render();
    return host;
  }

  window.FTReportJobResult = Object.freeze({
    jobResultID, isJobResultSection, jobReference, jobKind, mount,
  });
})();
