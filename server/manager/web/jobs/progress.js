(() => {
  let progressAbort = null;

  function statusTitle(value, context) {
    const title = {
      succeeded: "成功", failed: "失败", running: "运行中", queued: "排队中",
      planning: "规划中", cancelled: "已取消", paused: "已暂停",
      submitted: "已提交", created: "已创建",
    }[value];
    return title ? context.t(title) : value || context.t("未知");
  }

  function progressView(context, status) {
    const root = document.createElement("section");
    root.className = "job-progress job-section";
    const heading = document.createElement("h2");
    heading.textContent = context.t("任务进度");
    const bar = document.createElement("progress");
    bar.max = 100;
    const label = document.createElement("span");
    label.textContent = statusTitle(status, context);
    root.append(heading, bar, label);
    if (status === "succeeded") bar.value = 100;
    else if (!["running", "planning"].includes(status)) bar.value = 0;
    return {root, bar, label};
  }

  function updateProgress(view, payload) {
    const source = payload?.latest_progress?.data || payload?.data || payload || {};
    const completed = Number(source.completed);
    const total = Number(source.total);
    const percent = Number.isFinite(Number(source.percent)) ? Number(source.percent)
      : Number.isFinite(completed) && Number.isFinite(total) && total > 0 ? completed / total * 100 : null;
    const status = String(source.status || payload?.status || source.phase || "").trim();
    if (percent != null) view.bar.value = Math.max(0, Math.min(100, percent));
    else if (status === "succeeded") view.bar.value = 100;
    else view.bar.removeAttribute("value");
    const phase = source.phase || payload?.status || "";
    const count = Number.isFinite(completed) && Number.isFinite(total) && total > 0 ? ` · ${completed}/${total}` : "";
    view.label.textContent = `${phase}${count}${percent == null ? "" : ` · ${percent.toFixed(1)}%`}`;
  }

  async function watchProgress(context, jobID, portQuery, view, options = {}) {
    const controller = new AbortController();
    progressAbort = controller;
    try {
      const response = await context.raw(`/api/jobs/${encodeURIComponent(jobID)}/stream${portQuery}`, {signal: controller.signal});
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (!controller.signal.aborted) {
        const {done, value} = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, {stream: true});
        const frames = buffer.split(/\r?\n\r?\n/);
        buffer = frames.pop() || "";
        frames.forEach(frame => {
          const data = frame.split(/\r?\n/).filter(line => line.startsWith("data:"))
            .map(line => line.slice(5).trim()).join("\n");
          if (!data) return;
          try {
            const payload = JSON.parse(data);
            updateProgress(view, payload);
            options.onPayload?.(payload);
          } catch (_) {}
        });
      }
    } catch (error) {
      if (error.name !== "AbortError") view.label.textContent = context.t("实时进度暂不可用");
    } finally {
      options.onComplete?.();
    }
  }

  function stopProgress() {
    progressAbort?.abort();
    progressAbort = null;
  }

  window.FTJobProgress = {progressView, stopProgress, watchProgress};
})();
