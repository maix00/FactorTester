(() => {
  function create(context, profileID, assistance, options = {}) {
    let sequence = 0;
    let timer = null;
    let disposed = false;
    let lastPublished = "";
    let lastPublishedAt = 0;
    let requestController = null;
    const interval = Math.max(100, Number(options.interval) || 250);
    const heartbeatMs = Math.max(1000, Number(options.heartbeatMs) || 60000);
    const now = typeof options.now === "function" ? options.now : () => Date.now();
    const waitSeconds = Math.max(1, Math.min(
      25, Number(options.waitSeconds) || 20,
    ));

    async function publish() {
      const value = assistance.snapshot();
      const serialized = JSON.stringify(value);
      if (serialized === lastPublished && now() - lastPublishedAt < heartbeatMs) return;
      await context.api("/api/client/profile-agent/assistance/publish", {
        method: "POST",
        body: JSON.stringify({
          profile_id: profileID, tab_id: context.tabID, assistance: value,
        }),
      });
      lastPublished = serialized;
      lastPublishedAt = now();
    }

    async function syncOnce() {
      if (disposed) return;
      await publish();
      const controller = new AbortController();
      requestController = controller;
      const payload = await context.api(
        `/api/client/profile-agent/assistance/applications?profile_id=${encodeURIComponent(profileID)}`
        + `&tab_id=${encodeURIComponent(context.tabID)}&after=${sequence}`
        + `&wait=${waitSeconds}`,
        {signal: controller.signal},
      ).finally(() => {
        if (requestController === controller) requestController = null;
      });
      for (const item of payload.applications || []) {
        sequence = Math.max(sequence, Number(item.sequence || 0));
        let result;
        try {
          if (Number(item.expires_at || 0) > 0
              && Number(item.expires_at) * 1000 < Date.now()) {
            throw new Error("page assistance application expired before it reached the page");
          }
          const revision = item.kind === "replace_document"
            ? await assistance.apply(item) : assistance.snapshot().revision;
          result = {success: true, revision};
        } catch (error) {
          result = {success: false, error: String(error?.message || error)};
        }
        await context.api("/api/client/profile-agent/assistance/acknowledge", {
          method: "POST",
          body: JSON.stringify({profile_id: profileID, sequence: item.sequence, ...result}),
        });
      }
      if ((payload.applications || []).length) {
        lastPublished = "";
        await publish();
        context.checkpointTabSession?.();
      }
    }

    function schedule(delay = interval) {
      if (disposed || timer !== null) return;
      timer = setTimeout(async () => {
        timer = null;
        try { await syncOnce(); } catch (_) { /* retry on the next tick */ }
        schedule();
      }, delay);
    }

    async function start() {
      // Publishing the current page is required before the Agent can inspect
      // it, but waiting for the applications long-poll can block drawer mount
      // for the complete server wait window (normally 20 seconds). Keep that
      // receive loop entirely off the interactive drawer-open path.
      await publish();
      schedule(0);
    }

    function dispose() {
      disposed = true;
      requestController?.abort();
      requestController = null;
      if (timer) clearTimeout(timer);
      timer = null;
    }

    return Object.freeze({dispose, start, syncOnce});
  }

  window.FTPageAgentContext = Object.freeze({create});
})();
