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
    // Submission identity and task labels describe this JobAttempt, not the
    // reusable test configuration, so they are kept outside the backend
    // setting registry and never enter saved templates.
    for (const key of ["task_name", "acting_profile_ref", "acting_profile_name"]) {
      if (Object.prototype.hasOwnProperty.call(state.runValues || {}, key)) {
        result[key] = structuredClone(state.runValues[key]);
      }
    }
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
    const help = document.createElement("small"); help.textContent = context.t(item.help_text || "");
    copy.append(label, help);
    const fieldValue = controlField(item);
    const manifest = {defaults: {[item.key]: fieldValue}};
    const control = FTTestSettings.controlFor(
      item.key, fieldValue, manifest, state.runValues, context,
      {
        onCommit: ({key, value}) => { state.runValues[key] = value; },
        refresh,
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

  function profileControl(context, state, refresh) {
    const control = document.createElement("select");
    const user = document.createElement("option");
    user.value = "";
    user.textContent = context.t("用户本人（不绑定 Profile）");
    control.append(user);
    (Array.isArray(state.profiles) ? state.profiles : []).forEach(profile => {
      const profileID = String(profile.profile_id || "").trim();
      if (!profileID) return;
      const option = document.createElement("option");
      option.value = `profile:${profileID}`;
      const displayName = String(profile.display_name || profileID);
      option.textContent = `${displayName}（${profileID}）`;
      control.append(option);
    });
    control.value = String(state.runValues.acting_profile_ref || "");
    control.addEventListener("change", () => {
      state.runValues.acting_profile_ref = control.value;
      const selected = (state.profiles || []).find(profile => (
        `profile:${String(profile.profile_id || "").trim()}` === control.value
      ));
      state.runValues.acting_profile_name = selected
        ? String(selected.display_name || selected.profile_id || "")
        : "";
      refresh?.();
    });
    return control;
  }

  function identityRows(context, state, refresh) {
    const root = rows(context, state, [{
      key: "task_name",
      label: "任务名称",
      help_text: "留空时列表使用运行配置 hash",
      control_template: "text",
      default: "",
    }], refresh);
    const profile = document.createElement("div");
    profile.className = "test-setting-row";
    const copy = document.createElement("span");
    const label = document.createElement("b"); label.textContent = context.t("提交身份");
    const help = document.createElement("small");
    help.textContent = context.t("任务列表显示为用户名（Profile）；不选时使用用户本人");
    copy.append(label, help);
    profile.append(copy, profileControl(context, state, refresh));
    root.append(profile);
    root.classList.add("test-run-identity-rows");
    return root;
  }

  function render(context, state, refresh) {
    const identity = document.createElement("section");
    identity.className = "test-run-identity";
    const identityHeading = document.createElement("div");
    identityHeading.className = "section-heading";
    const identityTitle = document.createElement("h2");
    identityTitle.textContent = context.t("任务名称与提交身份");
    const identityNote = document.createElement("p");
    identityNote.textContent = context.t("只作用于本次提交，不写入可复用测试模板");
    identityHeading.append(identityTitle, identityNote);
    identity.append(identityHeading, identityRows(context, state, refresh));

    const regular = forPlacement(state.manifest, "run_options");
    const advanced = forPlacement(state.manifest, "advanced_run_options");
    if (!regular.length && !advanced.length) return identity;
    const section = document.createElement("section"); section.className = "test-run-options";
    const heading = document.createElement("div"); heading.className = "section-heading";
    const copy = document.createElement("div");
    const title = document.createElement("h2"); title.textContent = context.t("运行选项");
    const note = document.createElement("p");
    note.textContent = context.t("这些选项只作用于本次运行，不写入可复用测试模板");
    copy.append(title, note); heading.append(copy); section.append(heading);
    if (regular.length) section.append(rows(context, state, regular, refresh));
    if (advanced.length) {
      const details = document.createElement("details"); details.className = "test-run-advanced";
      const summary = document.createElement("summary"); summary.textContent = context.t("诊断选项");
      details.append(summary, rows(context, state, advanced, refresh));
      section.append(details);
    }
    identity.append(section);
    return identity;
  }

  window.FTTestRunFields = Object.freeze({
    definitions, field, forPlacement, initialValues, render, requestBody,
  });
})();
