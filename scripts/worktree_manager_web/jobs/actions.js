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
    if (terminalStatuses.has(job.status)) {
      add("按冻结配置重试", "retry", {
        confirm: true, openNewAttempt: true,
      });
    }
  }

  window.FTJobActions = Object.freeze({install});
})();
