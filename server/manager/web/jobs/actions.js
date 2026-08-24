(() => {
  const terminalStatuses = new Set(["succeeded", "failed", "cancelled"]);
  const cancellableStatuses = new Set([
    "submitted", "planning", "awaiting_confirmation", "queued", "running", "paused",
  ]);

  function actionPath(jobID, action, portQuery) {
    return `/api/jobs/${encodeURIComponent(jobID)}/${action}${portQuery}`;
  }

  function confirmed(context, label) {
    return window.confirm(
      context.t("确认执行“%@”？").replace("%@", context.t(label)),
    );
  }

  function workbenchKind(job = {}) {
    const shared = window.FTJobGeneration?.analysisOf?.({job}, {});
    if (shared) return shared;
    const kind = String(job.kind || job.job_type || "").toLowerCase();
    if (["ic", "ic_test", "ic-test"].includes(kind)) return "ic";
    if (["backtest", "group_backtest", "group-test", "group_test"].includes(kind)) {
      return "backtest";
    }
    return "";
  }

  function runID(job = {}) {
    return String(job.run_id || job.run?.run_id || "").trim();
  }

  async function cloneRunWorkspace(context, options) {
    const {
      job, jobID = "", portQuery = "", title = "", derivedPrefill = null,
      resolvedPort = 0, serverID = "", openNewTab = false,
    } = options || {};
    const kind = workbenchKind(job);
    const sourceRunID = runID(job);
    if (!kind || !sourceRunID) throw new Error(context.t("任务缺少可恢复的冻结运行配置"));
    const value = await context.api(
      `/api/runs/${encodeURIComponent(sourceRunID)}/clone-workspace${portQuery}`,
      {method: "POST", body: JSON.stringify({title})},
    );
    const workspaceID = String(value.workspace?.workspace_id || "");
    if (!workspaceID) throw new Error(context.t("恢复响应缺少工作区"));
    if (!openNewTab) localStorage.setItem(`ft-${kind}-workspace`, workspaceID);
    if (kind === "backtest" && derivedPrefill) {
      sessionStorage.setItem("ft-backtest-derived-prefill", JSON.stringify({
        ...derivedPrefill, workspaceID,
      }));
    }
    const route = kind === "ic" ? "/ic-test" : "/backtest";
    if (openNewTab) {
      const params = new URLSearchParams({
        workspace_id: workspaceID,
        job_id: String(jobID || job.job_id || ""),
        run_id: sourceRunID,
        run_spec_hash: String(job.run_spec_hash || ""),
        status: String(job.status || "succeeded"),
        port: String(resolvedPort || job.execution_port || job.port || 0),
        server_id: String(serverID || job.execution_server_id || job.server_id || ""),
        group_id: String(
          job.configuration_group_id || job.group_id || job.task_group_id || "",
        ),
      });
      context.openTab(`${route}?${params}`, {
        forceNew: true,
        title: `${context.t(kind === "ic" ? "IC 测试" : "回测")} · ${String(jobID || sourceRunID).slice(0, 8)}`,
      });
    } else context.navigate(route);
    return value.workspace;
  }

  function install(context, {job, jobID, portQuery, resolvedPort, onRefresh}) {
    if (!context.session) return;
    const buttons = [];

    function add(label, action, options = {}) {
      const control = context.button(context.t(label), async () => {
        if (options.confirm && !confirmed(context, label)) return;
        buttons.forEach(item => { item.disabled = true; });
        context.showNotice("");
        try {
          const result = await context.api(actionPath(jobID, action, portQuery), {
            method: "POST",
            body: JSON.stringify(options.body || {}),
          });
          if (options.openNewAttempt && result.job_id) {
            const port = Number(result.port || resolvedPort || 0);
            const route = port
              ? `/jobs/${port}/${encodeURIComponent(result.job_id)}`
              : `/jobs/${encodeURIComponent(result.job_id)}`;
            context.navigate(route);
            return;
          }
          await onRefresh();
        } catch (error) {
          context.showNotice(
            `${context.t("任务操作失败")}: ${error.message}`,
            true,
          );
          buttons.forEach(item => { item.disabled = false; });
        }
      }, context.t(label));
      if (options.danger) control.classList.add("danger-action");
      buttons.push(control);
      context.toolbar.append(control);
    }

    if (job.status === "awaiting_confirmation") {
      add("确认任务", "approve");
    }
    if (job.status === "paused" && job.step_mode) {
      add("下一步", "continue", {body: {action: "continue"}});
      add("运行到底", "continue", {body: {action: "end"}, confirm: true});
    }
    if (cancellableStatuses.has(job.status) && !job.cancel_requested) {
      add("取消任务", "cancel", {confirm: true, danger: true});
    }
  }

  window.FTJobActions = Object.freeze({cloneRunWorkspace, install, runID, workbenchKind});
})();
