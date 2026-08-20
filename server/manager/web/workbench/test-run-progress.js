(() => {
  const terminal = new Set(["succeeded", "failed", "cancelled"]);
  let activeKey = "";

  function statusOf(payload) {
    const source = payload?.latest_progress?.data || payload?.data || payload || {};
    const eventStatus = payload?.event === "result" ? "succeeded"
      : payload?.event === "error" ? "failed" : "";
    return String(source.status || payload?.status || eventStatus || source.phase || "").trim();
  }

  function watch(context, state, item, rerender) {
    const key = [item.jobID, item.portQuery || "", item.serverID || ""].join("|");
    if (activeKey === key && item.progressWatchKey === key) return;
    window.FTJobProgress.stopProgress();
    activeKey = key;
    item.progressWatchKey = key;
    item.progressStreamClosed = false;
    queueMicrotask(async () => {
      await window.FTJobProgress.watchProgress(
        context, item.jobID, item.portQuery || "", item.progressView,
        {
          onPayload: payload => {
            const status = statusOf(payload);
            if (status) item.phase = status;
            // Do not wait for every proxy/browser combination to observe the
            // upstream EOF. A terminal event is authoritative and should
            // immediately finish the live watcher so detail/results can load.
            if (terminal.has(status)) window.FTJobProgress.stopProgress();
          },
          onComplete: () => {
            if (item.progressWatchKey !== key) return;
            item.progressWatchKey = "";
            item.progressStreamClosed = true;
            if (activeKey === key) activeKey = "";
            // The stream may close before its final frame reaches the browser.
            // Always fetch the authoritative Job detail once on completion;
            // recordDetail() reconciles the phase and result payload.
            if (item.resultLoading) {
              item.progressRefreshPending = true;
              return;
            }
            window.FTTestRunResults?.refresh(context, state, item, rerender);
          },
        },
      );
    });
  }

  function render(context, _state, item, rerender) {
    if (!item?.jobID || !window.FTJobProgress) return null;
    const key = [item.jobID, item.portQuery || "", item.serverID || ""].join("|");
    if (!terminal.has(item.phase) && item.progressStreamClosed && item.progressView) {
      if (!item.progressResumePending) {
        item.progressResumePending = true;
        queueMicrotask(async () => {
          try {
            await window.FTTestRunResults?.refresh(context, _state, item, rerender);
          } finally {
            item.progressResumePending = false;
            if (!terminal.has(item.phase)) {
              item.progressStreamClosed = false;
              rerender?.();
            }
          }
        });
      }
      return item.progressView.root;
    }
    if (!terminal.has(item.phase) && item.progressViewKey === key && item.progressView) {
      if (!(activeKey === key && item.progressWatchKey === key)) {
        watch(context, _state, item, rerender);
      }
      return item.progressView.root;
    }
    if (!terminal.has(item.phase)
      && activeKey === key && item.progressWatchKey === key && item.progressView) {
      return item.progressView.root;
    }
    const view = window.FTJobProgress.progressView(context, item.phase);
    item.progressView = view;
    item.progressViewKey = key;
    if (!terminal.has(item.phase) && !item.progressStreamClosed) {
      watch(context, _state, item, rerender);
    }
    return view.root;
  }

  function suspend(items = []) {
    window.FTJobProgress?.stopProgress?.();
    activeKey = "";
    (Array.isArray(items) ? items : []).forEach(item => {
      item.progressWatchKey = "";
      item.progressResumePending = false;
      if (!terminal.has(item.phase)) item.progressStreamClosed = true;
    });
  }

  window.FTTestRunProgress = Object.freeze({render, suspend});
})();
