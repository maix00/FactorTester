(() => {
  function tabURL(manifest, tabKey) {
    const template = String(manifest?.tab_url_template || "");
    return template
      ? template.replace("{tab_key}", encodeURIComponent(tabKey)) : "";
  }

  function mergeTab(state, tabKey, payload) {
    const defaults = payload?.defaults || {};
    if (!Object.keys(defaults).length) return;
    state.manifest.defaults = {
      ...(state.manifest.defaults || {}), ...defaults,
    };
    state.settingsLoadedTabs.add(tabKey);
  }

  function ensureTab(context, state, tabKey, refresh) {
    if (!tabKey || state.settingsLoadedTabs.has(tabKey)) return Promise.resolve();
    const existing = state.settingsTabLoads[tabKey];
    if (existing?.status === "loading" && existing.promise) return existing.promise;
    const record = existing || (state.settingsTabLoads[tabKey] = {
      status: "idle", error: "", promise: null,
    });
    const url = tabURL(state.manifest, tabKey);
    if (!url) {
      state.settingsLoadedTabs.add(tabKey);
      return Promise.resolve();
    }
    record.status = "loading";
    record.error = "";
    record.promise = context.api(url)
      .then(payload => {
        mergeTab(state, tabKey, payload);
        record.status = "ready";
        refresh?.();
      })
      .catch(error => {
        record.status = "error";
        record.error = error.message || String(error);
        refresh?.();
      });
    return record.promise;
  }

  window.FTTestSettingsSchema = Object.freeze({ensureTab});
})();
