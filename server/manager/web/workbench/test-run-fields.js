(() => {
  function definitions(manifest) {
    return [...(manifest?.run_fields || [])]
      .sort((left, right) => Number(left.order || 0) - Number(right.order || 0));
  }

  function field(manifest, key) {
    return definitions(manifest).find(item => item.key === key) || null;
  }

  function forPlacement(manifest, placement) {
    return definitions(manifest).filter(item => item.placement === placement);
  }

  function initialValues(manifest) {
    const values = {};
    definitions(manifest).forEach(item => {
      if (item.placement === "outputs") return;
      values[item.key] = structuredClone(item.default);
    });
    return values;
  }

  function requestBody(state) {
    const result = {};
    definitions(state.manifest).forEach(item => {
      if (item.request_location !== "body") return;
      if (item.placement === "outputs") {
        result[item.key] = Array.isArray(state.outputRequests)
          ? [...state.outputRequests] : [];
        return;
      }
      const value = state.runValues?.[item.key];
      if (item.enabled_payload != null) {
        if (value) result[item.key] = structuredClone(item.enabled_payload);
        return;
      }
      if (value !== undefined) result[item.key] = structuredClone(value);
    });
    return result;
  }

  function controlField(item) {
    return {
      ...item, value: structuredClone(item.default), serialization: {},
      visible_when: {}, editable_when: {}, disabled_values_by_engine: {},
      engine_defaults: {}, default_when: {}, minimum: null, maximum: null, step: null,
    };
  }

  function row(context, state, item, refresh) {
    const root = document.createElement("div");
    root.className = "test-setting-row";
    const copy = document.createElement("span");
    const label = document.createElement("b"); label.textContent = context.t(item.label);
    copy.append(label);
    if (item.help_text) {
      const hint = context.t(item.help_text);
      root.title = hint;
      root.setAttribute("aria-label", `${label.textContent}: ${hint}`);
    }
    const fieldValue = controlField(item);
    const manifest = {defaults: {[item.key]: fieldValue}};
    const control = item.control_template === "profile"
      ? profileControl(context, state, refresh, item)
      : FTTestSettings.controlFor(
        item.key, fieldValue, manifest, state.runValues, context,
        {
          onCommit: ({key, value}) => { state.runValues[key] = value; },
          refresh,
          ensureControl: field => window.FTTests?.ensureControl?.(
            context, state, field, refresh,
          ),
        },
        false,
      );
    root.append(copy, control);
    return root;
  }

  function rows(context, state, items, refresh) {
    const root = document.createElement("div"); root.className = "test-setting-rows";
    items.forEach(item => root.append(row(context, state, item, refresh)));
    return root;
  }

  function profileControl(context, state, refresh, item) {
    const control = document.createElement("select");
    const user = document.createElement("option");
    user.value = "";
    user.textContent = context.t("用户本人（不绑定 Profile）");
    control.append(user);
    if (!state.profilesLoaded) {
      const deferred = document.createElement("option");
      deferred.value = "";
      deferred.textContent = context.t("点击后读取其他提交身份…");
      deferred.disabled = true;
      control.append(deferred);
      control.addEventListener("focus", () => {
        window.FTTests?.ensureProfiles?.(context, state, refresh);
        refresh?.();
      }, {once: true});
    }
    (Array.isArray(state.profiles) ? state.profiles : []).forEach(profile => {
      const profileID = String(profile.profile_id || "").trim();
      if (!profileID) return;
      const option = document.createElement("option");
      option.value = `profile:${profileID}`;
      const displayName = String(profile.display_name || profileID);
      option.textContent = `${displayName}（${profileID}）`;
      control.append(option);
    });
    control.value = String(state.runValues[item.key] || item.default || "");
    control.addEventListener("change", () => {
      state.runValues[item.key] = control.value;
      refresh?.();
    });
    return control;
  }

  function panel(context, state, refresh) {
    const root = document.createElement("div");
    root.className = "test-run-settings-content";
    const note = document.createElement("p");
    note.className = "test-run-settings-note";
    note.textContent = context.t(
      "这些字段只作用于本次提交；提交后会冻结到 Job 和 RunSpec，不写入可复用测试模板",
    );
    root.append(note);
    const standard = [
      ...forPlacement(state.manifest, "run_identity"),
      ...forPlacement(state.manifest, "run_options"),
    ].sort((left, right) => Number(left.order || 0) - Number(right.order || 0));
    if (standard.length) {
      const standardRows = rows(context, state, standard, refresh);
      standardRows.classList?.add?.("test-run-field-rows");
      root.append(standardRows);
    }
    const advanced = forPlacement(state.manifest, "advanced_run_options");
    if (advanced.length) {
      const details = document.createElement("details");
      details.className = "test-run-advanced";
      const summary = document.createElement("summary");
      summary.textContent = context.t("诊断选项");
      details.append(summary, rows(context, state, advanced, refresh));
      root.append(details);
    }
    const output = forPlacement(state.manifest, "outputs")[0];
    if (output && typeof window.FTTestOutputs?.content === "function") {
      root.append(window.FTTestOutputs.content(context, state, refresh));
    }
    return root;
  }

  window.FTTestRunFields = Object.freeze({
    definitions, field, forPlacement, initialValues, panel, render: panel, requestBody,
  });
})();
