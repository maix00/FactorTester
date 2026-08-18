(() => {
  const terminal = new Set(["succeeded", "failed", "cancelled"]);
  let activeKey = "";

  function statusOf(payload) {
    const source = payload?.latest_progress?.data || payload?.data || payload || {};
    return String(source.status || payload?.status || source.phase || "").trim();
  }

  function watch(context, state, item, rerender) {
    const key = [item.jobID, item.portQuery || "", item.serverID || ""].join("|");
    if (activeKey === key && item.progressWatchKey === key) return;
    window.FTJobProgress.stopProgress();
    activeKey = key;
    item.progressWatchKey = key;
    queueMicrotask(async () => {
      await window.FTJobProgress.watchProgress(
        context, item.jobID, item.portQuery || "", item.progressView,
        {
          onPayload: payload => {
            const status = statusOf(payload);
            if (status) item.phase = status;
          },
          onComplete: () => {
            if (item.progressWatchKey !== key) return;
            item.progressWatchKey = "";
            if (activeKey === key) activeKey = "";
            if (!terminal.has(item.phase)) {
              rerender?.();
              return;
            }
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
    if (!terminal.has(item.phase)
      && activeKey === key && item.progressWatchKey === key && item.progressView) {
      return item.progressView.root;
    }
    const view = window.FTJobProgress.progressView(context, item.phase);
    item.progressView = view;
    if (!terminal.has(item.phase)) watch(context, _state, item, rerender);
    return view.root;
  }

  window.FTTestRunProgress = Object.freeze({render});
})();
