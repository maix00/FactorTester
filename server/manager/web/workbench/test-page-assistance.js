(() => {
  function coerce(prior, value) {
    if (typeof prior === "boolean") return [true, "true", "1", 1].includes(value);
    if (typeof prior === "number") {
      const parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : prior;
    }
    if (Array.isArray(prior)) {
      if (Array.isArray(value)) return value;
      try { return JSON.parse(String(value)); } catch (_) { return prior; }
    }
    return value;
  }

  function register(context, state, refresh, host) {
    const key = `test-configuration:${state.kind}`;
    const registeredFields = () => Object.entries(state.manifest?.defaults || {})
      .filter(([, definition]) => (
        !definition?.adapter_managed
        && state.settingsMountedTabs.includes(definition?.tab_key)
        && window.FTSettingRules.isVisible(definition, state.values)
      ));
    context.pageState?.register?.(key, {
      capture: () => ({
        settings_tab: state.settingsTabKey,
        mounted_tabs: state.settingsMountedTabs,
        values: state.values,
      }),
      restore: value => {
        if (value?.settings_tab) state.settingsTabKey = value.settings_tab;
        if (Array.isArray(value?.mounted_tabs)) state.settingsMountedTabs = value.mounted_tabs;
        if (value?.values && typeof value.values === "object") {
          Object.assign(state.values, value.values);
        }
      },
      describe: () => ({
        page: `${state.kind}-configuration`,
        section: state.settingsTabKey || "",
        fields: registeredFields().map(([field, definition]) => ({
          key: field,
          label: definition?.label || field,
          tab: definition?.tab_key || "",
          editable: window.FTSettingRules.isEditable(definition, state.values),
          value: state.values[field],
        })),
      }),
      apply: action => {
        const field = String(action?.field || "");
        const definition = state.manifest?.defaults?.[field];
        if (
          !definition || definition.adapter_managed
          || !state.settingsMountedTabs.includes(definition.tab_key)
          || !window.FTSettingRules.isVisible(definition, state.values)
          || !window.FTSettingRules.isEditable(definition, state.values)
        ) return false;
        window.FTSettingRules.setValue(
          state.manifest, state.values, field, definition,
          coerce(state.values[field], action.value),
        );
        refresh();
        return true;
      },
    });
    void window.FTPageAgentProfiles.attachSelf(context, {
      pageKind: `${state.kind}-configuration`,
      section: state.settingsTabKey || "",
      buttonHost: host,
    }).catch(() => {});
  }

  window.FTTestPageAssistance = Object.freeze({register});
})();
