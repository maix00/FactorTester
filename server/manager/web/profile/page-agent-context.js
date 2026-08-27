(() => {
  function create(context, profileID, options = {}) {
    let sequence = 0;
    let timer = null;
    let disposed = false;
    let lastPublished = "";
    const interval = Math.max(500, Number(options.interval) || 1000);

    async function publish() {
      const value = context.pageState?.describe?.() || {schema_version: 1, sections: []};
      const serialized = JSON.stringify(value);
      if (serialized === lastPublished) return;
      await context.api("/api/client/profile-agent/page-context", {
        method: "POST",
        body: JSON.stringify({
          profile_id: profileID, tab_id: context.tabID, context: value,
        }),
      });
      lastPublished = serialized;
    }

    async function syncOnce() {
      if (disposed) return;
      await publish();
      const payload = await context.api(
        `/api/client/profile-agent/page-actions?profile_id=${encodeURIComponent(profileID)}`
        + `&tab_id=${encodeURIComponent(context.tabID)}&after=${sequence}`,
      );
      for (const item of payload.actions || []) {
        sequence = Math.max(sequence, Number(item.sequence || 0));
        context.pageState?.apply?.(item.section_id, item.action);
      }
      if ((payload.actions || []).length) {
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
