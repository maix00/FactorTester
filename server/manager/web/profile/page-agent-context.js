(() => {
  function create(context, profileID, assistance, options = {}) {
    let sequence = 0;
    let timer = null;
    let disposed = false;
    let lastPublished = "";
    const interval = Math.max(500, Number(options.interval) || 1000);

    async function publish() {
      const value = assistance.snapshot();
      const serialized = JSON.stringify(value);
      if (serialized === lastPublished) return;
      await context.api("/api/client/profile-agent/assistance/publish", {
        method: "POST",
        body: JSON.stringify({
          profile_id: profileID, tab_id: context.tabID, assistance: value,
        }),
      });
      lastPublished = serialized;
    }

    async function syncOnce() {
      if (disposed) return;
      if (options.isActive?.() === false) return;
      await publish();
      const payload = await context.api(
        `/api/client/profile-agent/assistance/applications?profile_id=${encodeURIComponent(profileID)}`
        + `&tab_id=${encodeURIComponent(context.tabID)}&after=${sequence}`,
      );
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

    function schedule() {
      if (disposed) return;
      timer = setTimeout(async () => {
        try { await syncOnce(); } catch (_) { /* retry on the next tick */ }
        schedule();
      }, interval);
    }

    async function start() {
      await syncOnce();
      schedule();
    }

    function dispose() {
      disposed = true;
      if (timer) clearTimeout(timer);
      timer = null;
    }

    return Object.freeze({dispose, start, syncOnce});
  }

  window.FTPageAgentContext = Object.freeze({create});
})();
