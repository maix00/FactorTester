(() => {
  function analysisOf(taskDetail, payload) {
    const raw = String(taskDetail?.job?.kind || payload?.kind || "").toLowerCase();
    if (["ic", "ic_test", "ic-test"].includes(raw)) return "ic";
    if (["backtest", "group_backtest", "group-test", "group_test"].includes(raw)) {
      return "backtest";
    }
    return "";
  }

  async function capabilities(context, serverQuery = "") {
    const payload = await context.api(`/api/jobs/artifact-capabilities${serverQuery}`);
    return Array.isArray(payload.outputs) ? payload.outputs : [];
  }

  const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

  async function waitForGeneration(context, options, child) {
    const childID = encodeURIComponent(String(child?.job_id || ""));
    if (!childID) throw new Error(context.t("补充任务缺少 Job ID"));
    const query = options.artifactQuery || options.executionQuery || options.portQuery || "";
    for (;;) {
      const payload = await context.api(
        `/api/jobs/${encodeURIComponent(options.jobID)}/supplementals/${childID}${query}`,
      );
      const job = payload?.job || {};
      if (job.status === "succeeded") return payload;
      if (["failed", "cancelled"].includes(job.status)) {
        const error = payload?.error || {};
        throw new Error(error.message || error.code || context.t("结果生成失败"));
      }
      await delay(500);
    }
  }

  function panel(context, options) {
    const section = document.createElement("section");
    section.className = "job-section job-output-generation";
    const heading = document.createElement("h2");
    heading.textContent = context.t("生成其他结果");
    section.append(heading);
    if (options.error) {
      section.append(FTUI.empty(context.t("无法读取生成能力"), options.error));
      return section;
    }
    const analysis = analysisOf(options.taskDetail, options.payload);
    const definitions = FTOutputChoices.available(
      options.capabilities, analysis, "after_run",
    );
    if (!definitions.length) {
      section.append(Object.assign(document.createElement("p"), {
        textContent: context.t("该任务没有可事后生成的结果"),
      }));
      return section;
    }
    let selected = FTOutputChoices.initialSelection(
      options.capabilities,
      analysis,
      [...new Set([
        ...(options.taskDetail.output_requests || []),
        ...(options.taskDetail.generated_output_requests || []),
      ])],
      "after_run",
    );
    const executionQuery = options.artifactQuery || options.executionQuery || options.portQuery || "";
    const status = document.createElement("span");
    status.className = "output-generation-status";
    const generate = context.button(context.t("生成所选结果"), async () => {
      if (!selected.length) {
        status.textContent = context.t("请至少选择一项输出");
        return;
      }
      generate.disabled = true;
      status.textContent = context.t("正在生成…");
      try {
        const created = await context.api(
          `/api/jobs/${encodeURIComponent(options.jobID)}/supplementals${executionQuery}`,
          {method: "POST", body: JSON.stringify({
            kind: "report_output_generation",
            params: {output_requests: selected},
          })},
        );
        if (created.job) {
          status.textContent = context.t("已加入补充任务队列…");
          await waitForGeneration(context, options, created.job);
        }
        status.textContent = context.t("已生成，正在刷新任务详情…");
        await options.onGenerated();
      } catch (error) {
        status.textContent = error.message;
        generate.disabled = false;
      }
    }, context.t("从任务保留的原始结果生成表格或图像"));
    generate.className = "primary";
    section.append(FTOutputChoices.fieldValueSelector(
      context, definitions, selected, value => { selected = value; },
    ));
    const actions = document.createElement("div");
    actions.className = "output-generation-actions";
    actions.append(generate, status); section.append(actions);
    return section;
  }

  window.FTJobGeneration = Object.freeze({analysisOf, capabilities, panel});
})();
