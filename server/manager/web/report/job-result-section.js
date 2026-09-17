(() => {
  // A report's Job result special section (``kind=special``,
  // ``display_kind=test_result``, ``component_id=job-<32 hex>-result``) is the
  // same 运行过程与结果 surface the Job configuration page already renders after
  // a run.  This module only resolves the Job identity from the report
  // component and forwards to the existing implementations:
  //
  //   FTJobs.loadDetail            — the Job detail read (payload/taskDetail/job)
  //   FTJobProgress.progressView   — 运行过程（任务进度）
  //   FTJobResultViewers           — 按 job 类型分发的结果视图
  //
  // It deliberately owns no result rendering of its own: a second renderer for
  // the same Job would drift from the Job detail page.
  const JOB_RESULT_COMPONENT_ID = /^job-([0-9a-f]{32})-result$/;
  // The Job detail implementation's own lazy group.  The report route keeps a
  // focused initial payload, so the shared readers load on first use exactly
  // like the other on-demand report/Job surfaces.
  const JOB_DETAIL_GROUP = "job-detail-core";
  const LIVE_STATUSES = ["queued", "planning", "running", "paused"];

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

  // The result section's binding is written with the Job and already carries
  // the execution port and server identity, so a federated Job is read through
  // the same reference the report's Job hyperlinks use.  An unresolved
  // reference falls back to the Manager's Job index — the same fallback the
  // Job route itself uses — instead of inventing a port or server.
  function jobReference(context, jobID) {
    const target = `job:${jobID}`;
    const binding = context?.referenceMeta?.[target]
      || Object.values(context?.bindingByID || {})
        .find(item => item?.target_ref === target);
    const data = binding?.data || {};
    const port = Number(data.port);
    return {
      port: Number.isInteger(port) && port > 0 && port <= 65535 ? port : 0,
      serverID: String(data.server_id || data.execution_server_id || "").trim(),
    };
  }

  function placeholders(context) {
    const host = document.createElement("div");
    host.className = "report-job-result";
    const progress = document.createElement("div");
    progress.className = "report-job-result-progress";
    progress.append(FTUI.loading(t(context, "正在读取任务运行过程…")));
    const results = document.createElement("div");
    results.className = "report-job-result-results";
    results.append(FTUI.loading(t(context, "正在加载结果查看器…")));
    host.append(progress, results);
    return {host, progress, results};
  }

  function arm(context, jobID, executionQuery, progress, host, refresh) {
    // FTJobProgress owns one live watcher per page and replacing it is the
    // existing contract, so the previous stream is stopped first — exactly as
    // the Job detail page does before it watches a run.
    window.FTJobProgress.stopProgress();
    window.FTJobProgress.watchProgress(
      context, jobID, executionQuery, progress, {
        onPayload: () => {
          // A detached section must not keep streaming progress into removed
          // DOM, and a terminal payload ends its own stream.
          if (progress.progressState?.terminal || host.__ftReportDisposed
            || host.isConnected === false) {
            window.FTJobProgress.stopProgress();
          }
        },
        onComplete: ({aborted, terminal}) => {
          // A watcher replaced by another view is not task completion.  A
          // terminal stream converges once against the authoritative detail
          // projection without arming a second stream.
          if (aborted && !terminal) return;
          if (host.__ftReportDisposed || host.isConnected === false) return;
          void refresh({live: false});
        },
      },
    );
  }

  function mount(component, context, options = {}) {
    const jobID = jobResultID(component);
    const {host, progress: progressHost, results: resultsHost} = placeholders(context);
    host.dataset.reportJobID = jobID;
    host.dataset.reportJobResult = "loading";
    const generation = Number(context?.renderGeneration || 0);
    const isCurrent = () => !host.__ftReportDisposed
      && host.isConnected !== false
      && Number(context?.renderGeneration || 0) === generation;

    const render = async ({live = Boolean(options.live)} = {}) => {
      try {
        await window.FTStaticLoader?.loadGroups?.([JOB_DETAIL_GROUP]);
        if (typeof window.FTJobs?.loadDetail !== "function") {
          throw new Error(t(context, "任务详情实现不可用"));
        }
        const reference = jobReference(context, jobID);
        const loaded = await window.FTJobs.loadDetail(
          context, reference.port, jobID, reference.serverID,
        );
        if (!isCurrent()) return;
        const {
          payload, taskDetail, job, executionQuery, artifactQuery,
        } = loaded;
        const artifacts = taskDetail.artifacts || [];
        const inputNames = new Set(
          (taskDetail.input_artifacts || []).map(item => item.name),
        );
        const outputArtifacts = artifacts.filter(item => (
          item.role !== "input" && !inputNames.has(item.name)
        ));
        // A report is a read-only projection: it never owns the local-run
        // client path and never authors custom analyses, so it passes the same
        // inputs the Job detail page uses for the non-local read-only render.
        const activeArtifacts = outputArtifacts.filter(item => item.state === "active");
        const results = taskDetail.results?.summary || payload.result_summary
          || taskDetail.results || payload.result;
        const progress = window.FTJobProgress.progressView(context, job.status);
        progressHost.replaceChildren(progress.root);
        if (live && LIVE_STATUSES.includes(String(job.status || ""))) {
          arm(context, jobID, executionQuery, progress, host, render);
        }
        const groupName = window.FTJobResultViewers.group(
          job, activeArtifacts, results,
        );
        if (groupName) {
          await window.FTJobResultViewers.loadGroup(job, activeArtifacts, results);
          if (!isCurrent()) return;
          resultsHost.replaceChildren(window.FTJobResultViewers.domainSections(
            context, {
              job, taskDetail, payload, activeArtifacts, results, jobID,
              artifactQuery, executionQuery, customAnalyses: null,
              onGenerated: () => void render({live: false}),
            },
          ));
        } else {
          resultsHost.replaceChildren(window.FTJobResultViewers.genericSection(
            context, {
              declarations: FTJobArtifacts.effectiveDeclarations(
                taskDetail.output_declarations || [], outputArtifacts, context,
              ),
              activeArtifacts, results, jobID, artifactQuery, customAnalyses: null,
            },
          ));
        }
        host.dataset.reportJobResult = "ready";
      } catch (error) {
        if (!isCurrent()) return;
        // An unavailable Job result is stated explicitly; a silently empty
        // section would read as "this Job has no result".
        host.dataset.reportJobResult = "error";
        host.replaceChildren(FTUI.empty(
          t(context, "结果查看器不可用"), error?.message || String(error || ""),
        ));
      }
    };

    const dispose = window.FTReportLazyRuntime?.observe?.(
      host, context, () => void render(),
    );
    if (!dispose) void render();
    return host;
  }

  window.FTReportJobResult = Object.freeze({
    jobResultID, isJobResultSection, jobReference, mount,
  });
})();
