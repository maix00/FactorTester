(() => {
  function definitions(manifest) {
    return [...(manifest?.run_fields || [])]
      .filter(item => {
        const targets = Array.isArray(item.client_targets)
          ? item.client_targets : ["web", "swift", "cli"];
        return targets.includes(window.FTTestClientScope || "web");
      })
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
      const field = controlField(item);
      if (window.FTSettingRules?.isVisible
        && !FTSettingRules.isVisible(field, state.runValues || {})) return;
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
      rules: item.rules || {},
    };
  }

  function outputItems(context, state) {
    const definitions = window.FTOutputChoices?.available?.(
      state.outputCapabilities, state.kind,
    ) || [];
    if (!definitions.length && !state.outputCapabilitiesLoaded) {
      return [{
        value: "__outputs_loading__",
        label: context.t("打开后读取可选输出…"),
        description: context.t("打开选择器后读取本次测试可用的结果与生成物"),
        disabled: true,
      }];
    }
    return definitions.map(definition => {
      const formats = (definition.formats || [])
        .map(value => String(value).toUpperCase());
      const sources = (definition.required_sources || []).map(value => (
        context.t(value?.label || value?.name || value)
      ));
      const sourceNote = sources.length
        ? `${context.t("需保留")}：${sources.join("、")}`
        : "";
      return {
        value: definition.name,
        label: context.t(definition.label || definition.name),
        description: [formats.join(" / "), sourceNote]
          .filter(Boolean).join(" · "),
      };
    });
  }

  function profileItems(context, state) {
    const items = [{
      value: "",
      label: context.t("用户本人（不绑定 Profile）"),
      description: context.t("以当前用户身份提交任务"),
    }];
    if (!state.profilesLoaded) {
      items.push({
        value: "__profiles_loading__",
        label: context.t("打开后读取其他提交身份…"),
        description: context.t("打开选择器后读取当前用户的研究身份"),
        disabled: true,
      });
    }
    (Array.isArray(state.profiles) ? state.profiles : []).forEach(profile => {
      const profileID = String(profile.profile_id || "").trim();
      if (!profileID) return;
      const displayName = String(profile.display_name || profileID);
      items.push({
        value: `profile:${profileID}`,
        label: `${displayName}（${profileID}）`,
        description: profile.description || profileID,
      });
    });
    return items;
  }

  function runtimeServerItems(context, state, item) {
    return [
      {
        value: "",
        label: context.t("选择提供运行代码的服务器…"),
        description: context.t("使用当前服务器的默认运行代码包"),
      },
      ...(Array.isArray(state.runtimeServers) ? state.runtimeServers : [])
        .filter(server => server && server.server_id)
        .map(server => ({
          value: String(server.server_id),
          label: `${server.server_id} · ${server.endpoint || ""}`,
          description: server.endpoint || server.server_id,
        })),
    ];
  }

  function runValueFor(item, state) {
    return item.placement === "outputs"
      ? (Array.isArray(state.outputRequests) ? state.outputRequests : [])
      : state.runValues?.[item.key];
  }

  function fieldOptions(context, state, item, refresh) {
    const editor = item.value_descriptor?.editor;
    if (editor === "output_picker") {
      return {
        choiceItems: outputItems(context, state),
        choiceOnOpen: () => window.FTTests?.ensureOutputCapabilities?.(
          context, state, refresh,
        ),
        choiceOnRefresh: () => window.FTTests?.ensureOutputCapabilities?.(
          context, state, refresh, {force: true},
        ),
      };
    }
    if (editor === "profile") {
      return {
        choiceItems: profileItems(context, state),
        choiceOnOpen: () => {
          window.FTTests?.ensureProfiles?.(context, state, refresh);
        },
      };
    }
    if (editor === "server_picker") {
      return {
        choiceItems: runtimeServerItems(context, state, item),
        choiceOnOpen: () => loadRuntimeServers(context, state, refresh),
      };
    }
    return {};
  }

  async function loadRuntimeServers(context, state, refresh) {
    if (state.runtimeServersLoaded || state.runtimeServersLoading) return;
    state.runtimeServersLoading = true;
    refresh?.();
    try {
      const value = await context.api("/api/federation/servers");
      state.runtimeServers = [
        ...(Array.isArray(value.servers) ? value.servers : []),
        ...(Array.isArray(value.local_targets) ? value.local_targets : []),
      ];
      state.runtimeServersLoaded = true;
    } catch (error) {
      context.showNotice?.(error.message, true);
    } finally {
      state.runtimeServersLoading = false;
      refresh?.();
    }
  }

  function row(context, state, item, refresh) {
    const label = context.t(item.label);
    const hint = window.FTTestFieldHelp?.forField
      ? FTTestFieldHelp.forField(state.manifest, item.key, context)
      : (item.help_text ? context.t(item.help_text) : "");
    const hintText = typeof hint === "object" ? hint.text || "" : hint;
    const fieldDefinition = controlField(item);
    const values = {
      ...(state.runValues || {}),
      ...(item.placement === "outputs"
        ? {[item.key]: runValueFor(item, state)} : {}),
    };
    const manifest = {defaults: {[item.key]: fieldDefinition}};
    const control = FTTestSettings.controlFor(
      item.key, fieldDefinition, manifest, values, context,
      {
        ...fieldOptions(context, state, item, refresh),
        onCommit: ({key, value}) => {
          if (item.placement === "outputs") {
            state.outputRequests = Array.isArray(value) ? [...value] : [];
            state.outputRequestsExplicit = true;
          } else {
            state.runValues[key] = value;
          }
        },
        refresh,
        ensureControl: field => window.FTTests?.ensureControl?.(
          context, state, field, refresh,
        ),
      },
      false,
    );
    const root = FTTestFieldRow.create(label, control, hint, {help: hint});
    if (hintText) root.setAttribute("aria-label", `${label}: ${hintText}`);
    return root;
  }

  function rows(context, state, items, refresh) {
    const root = document.createElement("div"); root.className = "test-setting-rows";
    items.forEach(item => {
      const field = controlField(item);
      const visible = FTSettingRules.isVisible(field, state.runValues || {});
      if (visible) root.append(row(context, state, item, refresh));
    });
    return root;
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
    const fields = definitions(state.manifest)
      .filter(item => item.placement !== "global_settings");
    if (fields.length) root.append(rows(context, state, fields, refresh));
    return root;
  }

  function selection(state) {
    return Array.isArray(state.outputRequests) ? [...state.outputRequests] : [];
  }

  window.FTTestRunFields = Object.freeze({
    definitions, field, forPlacement, initialValues, panel, render: panel,
    requestBody, selection,
  });
})();
