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
    return {
      root, bar, label,
      progressState: {
        lastSeq: 0,
        percent: status === "succeeded" ? 100 : null,
        phaseIndex: new Map(),
        phaseCount: 0,
        terminal: ["succeeded", "failed", "cancelled"].includes(status),
      },
    };
  }

  function stateOf(view) {
    if (!view.progressState) {
      view.progressState = {
        lastSeq: 0, percent: null, phaseIndex: new Map(), phaseCount: 0, terminal: false,
      };
    }
    return view.progressState;
  }

  function registerPhases(state, phases) {
    if (!Array.isArray(phases) || !phases.length) return;
    const keys = phases.map(item => String(item?.key || item?.phase || item || "").trim())
      .filter(Boolean);
    if (!keys.length) return;
    state.phaseIndex = new Map(keys.map((key, index) => [key, index]));
    state.phaseCount = keys.length;
  }

  function terminalStatus(event, source, payload) {
    const status = String(source.status || payload?.status || "").trim();
    if (["succeeded", "failed", "cancelled"].includes(status)) return status;
    if (event === "result") return "succeeded";
    if (event === "error") return "failed";
    return "";
  }

  function measuredPercent(state, source) {
    const completed = Number(source.completed);
    const total = Number(source.total);
    const local = Number.isFinite(Number(source.percent)) ? Number(source.percent)
      : Number.isFinite(completed) && Number.isFinite(total) && total > 0 ? completed / total * 100 : null;
    if (local == null) return null;
    const phase = String(source.phase || "").trim();
    if (state.phaseCount > 0 && state.phaseIndex.has(phase)) {
      return (state.phaseIndex.get(phase) + Math.max(0, Math.min(100, local)) / 100)
        * 100 / state.phaseCount;
    }
    return local;
  }

  function updateProgress(view, payload) {
    const state = stateOf(view);
    if (state.terminal) return state;
    const event = String(payload?.event || "message");
    const wrapped = payload?.latest_progress;
    const source = wrapped?.data || payload?.data || payload || {};
    const seq = Number(payload?.seq ?? wrapped?.seq ?? 0);
    if (Number.isFinite(seq) && seq > 0) {
      if (seq <= state.lastSeq) return state;
      state.lastSeq = seq;
    }
    registerPhases(state, source.phases || source.manifest?.phases);
    const status = terminalStatus(event, source, payload);
    const measured = measuredPercent(state, source);
    if (measured != null) {
      state.percent = Math.max(state.percent ?? 0, Math.max(0, Math.min(100, measured)));
    }
    if (status === "succeeded") state.percent = 100;
    if (status) {
      state.percent ??= 0;
      state.terminal = true;
    }

    // Once determinate, heartbeats and count-less phase messages must not put
    // the native progress element back into its indeterminate animation.
    if (state.percent != null && view.bar.value !== state.percent) view.bar.value = state.percent;
    else if (state.percent == null && !state.terminal) view.bar.removeAttribute("value");
    const phase = source.phase || status || payload?.status || "";
    const completed = Number(source.completed);
    const total = Number(source.total);
    const count = Number.isFinite(completed) && Number.isFinite(total) && total > 0 ? ` · ${completed}/${total}` : "";
    const text = `${phase}${count}${state.percent == null ? "" : ` · ${state.percent.toFixed(1)}%`}`;
    if (text && view.label.textContent !== text) view.label.textContent = text;
    return state;
  }

  async function watchProgress(context, jobID, portQuery, view, options = {}) {
    const controller = new AbortController();
    progressAbort = controller;
    let streamError = null;
    try {
      const cursor = stateOf(view).lastSeq;
      const separator = portQuery ? "&" : "?";
      const path = `/api/jobs/${encodeURIComponent(jobID)}/stream${portQuery}`
        + (cursor > 0 ? `${separator}after=${encodeURIComponent(cursor)}` : "");
      const response = await context.raw(path, {signal: controller.signal});
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
          const event = frame.split(/\r?\n/).find(line => line.startsWith("event:"))
            ?.slice(6).trim() || "message";
          const id = Number(frame.split(/\r?\n/).find(line => line.startsWith("id:"))
            ?.slice(3).trim() || 0);
          const data = frame.split(/\r?\n/).filter(line => line.startsWith("data:"))
            .map(line => line.slice(5).trim()).join("\n");
          if (!data) return;
          try {
            const raw = JSON.parse(data);
            const payload = {event, seq: id, data: raw};
            updateProgress(view, payload);
            options.onPayload?.(payload);
          } catch (_) {}
        });
      }
    } catch (error) {
      if (error.name !== "AbortError") {
        streamError = error;
        view.label.textContent = context.t("实时进度暂不可用");
      }
    } finally {
      const terminal = stateOf(view).terminal;
      if (!controller.signal.aborted && !terminal) {
        view.label.textContent = context.t("实时进度暂不可用");
      }
      if (progressAbort === controller) progressAbort = null;
      // Replacing a watcher or leaving the page is not task completion and
      // must not launch an obsolete cross-server detail read. A terminal
      // payload deliberately aborts its own stream and still converges once.
      if (!controller.signal.aborted || terminal) {
        options.onComplete?.({
          aborted: controller.signal.aborted,
          error: streamError,
          terminal,
        });
      }
    }
  }

  function stopProgress() {
    progressAbort?.abort();
    progressAbort = null;
  }

  window.FTJobProgress = {progressView, stopProgress, updateProgress, watchProgress};
})();
