(() => {
  function number(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) && parsed > 0 ? Math.trunc(parsed) : 0;
  }

  function runtimeEventPatch(payload, previous = {}) {
    const method = String(payload?.method || payload?.type || "");
    const params = payload?.params || {};
    if (method === "thread/tokenUsage/updated") {
      const usage = params.tokenUsage || {};
      return {
        model_context_window: number(usage.modelContextWindow),
        last_tokens: number(usage.last?.totalTokens),
        total_tokens: number(usage.total?.totalTokens),
      };
    }
    if (method === "thread/settings/updated") {
      return {actual_model: String(params.threadSettings?.model || "")};
    }
    if (method === "model/rerouted") {
      return {actual_model: String(params.toModel || "")};
    }
    const itemType = String(params.item?.type || "").toLowerCase();
    if (method === "thread/compacted" || (
      method === "item/completed" && itemType === "contextcompaction"
    )) {
      return {compaction_count: number(previous.compaction_count) + 1};
    }
    return {};
  }

  function contextUsage(conversation = {}) {
    const used = number(conversation.last_tokens);
    const capacity = number(conversation.model_context_window);
    return {
      used,
      capacity,
      total: number(conversation.total_tokens),
      percent: capacity ? Math.min(100, Math.round(used * 100 / capacity)) : 0,
    };
  }

  function create(profile, context, options = {}) {
    const readOnly = Boolean(options.readOnly);
    const root = document.createElement("details");
    root.className = "profile-agent-runtime-controls";
    const summary = document.createElement("summary");
    summary.textContent = context.t("Agent 运行设置");
    const body = document.createElement("div");
    body.className = "profile-agent-runtime-body";
    const fields = document.createElement("div");
    fields.className = "profile-agent-runtime-fields";
    const actions = document.createElement("div");
    actions.className = "settings-inline-actions profile-agent-runtime-actions";
    const refresh = document.createElement("button");
    refresh.type = "button";
    refresh.className = "secondary profile-agent-runtime-refresh";
    refresh.textContent = context.t("重新读取模型");
    const apply = document.createElement("button");
    apply.type = "button";
    apply.className = "primary profile-agent-runtime-apply";
    apply.textContent = context.t("应用并验证");
    actions.append(refresh, apply);
    const catalogStatus = document.createElement("p");
    catalogStatus.className = "settings-muted profile-agent-catalog-status";
    const runtimeStatus = document.createElement("p");
    runtimeStatus.className = "settings-muted profile-agent-runtime-status";
    const notice = document.createElement("p");
    notice.className = "settings-muted profile-agent-runtime-notice";
    notice.setAttribute("aria-live", "polite");
    const usage = document.createElement("div");
    usage.className = "profile-agent-context-usage";
    const progress = document.createElement("progress");
    progress.max = 100;
    progress.value = 0;
    const usageText = document.createElement("span");
    usage.append(progress, usageText);
    body.append(fields, actions, catalogStatus, runtimeStatus, usage, notice);
    root.append(summary, body);

    const controls = {};
    for (const [key, label] of [
      ["model", "会话模型"],
      ["effort", "推理强度"],
      ["tier", "速度档位"],
    ]) {
      const field = document.createElement("label");
      field.className = "profile-agent-runtime-field";
      const title = document.createElement("span");
      title.textContent = context.t(label);
      const select = document.createElement("select");
      select.disabled = true;
      field.append(title, select);
      fields.append(field);
      controls[key] = select;
    }

    let current = null;
    let draft = null;
    let models = [];
    let catalogLoaded = false;
    let catalogValidated = false;
    let catalogPromise = null;
    let providerLatency = 0;
    let saving = false;

    function option(select, value, label) {
      const item = document.createElement("option");
      item.value = value;
      item.textContent = label;
      select.append(item);
    }

    function settingsOf(conversation = {}) {
      return {
        model_id: String(conversation.model_id || ""),
        reasoning_effort: String(conversation.reasoning_effort || ""),
        service_tier: String(conversation.service_tier || ""),
      };
    }

    function selectedModel() {
      return models.find(item => String(item.id || "") === controls.model.value);
    }

    function addSelectedFallback(control, selected) {
      if (selected && ![...control.children].some(item => item.value === selected)) {
        option(control, selected, selected);
      }
      control.value = selected;
    }

    function renderDependentChoices() {
      const model = selectedModel() || {};
      controls.effort.replaceChildren();
      controls.tier.replaceChildren();
      option(controls.effort, "", context.t("默认推理强度"));
      option(controls.tier, "", context.t("默认速度档位"));
      for (const item of model.reasoning_efforts || []) {
        option(controls.effort, String(item.id || ""), String(
          item.description || item.id || "",
        ));
      }
      for (const item of model.service_tiers || []) {
        option(controls.tier, String(item.id || ""), String(
          item.name || item.id || "",
        ));
      }
      addSelectedFallback(controls.effort, String(draft?.reasoning_effort || ""));
      addSelectedFallback(controls.tier, String(draft?.service_tier || ""));
      controls.effort.disabled = readOnly || !current || saving;
      controls.tier.disabled = readOnly || !current || saving;
    }

    function renderRuntimeStatus(conversation) {
      const selected = String(conversation.model_id || "");
      const actual = String(conversation.actual_model || "");
      let modelStatus = context.t("实际模型尚未由运行时确认");
      if (actual && selected && actual === selected) {
        modelStatus = `${context.t("运行时已确认实际模型")}: ${actual}`;
      } else if (actual) {
        modelStatus = `${context.t("实际模型")}: ${actual} · ${context.t("已发生模型重路由")}`;
      }
      const requested = [
        conversation.reasoning_effort
          ? `${context.t("请求推理强度")}: ${conversation.reasoning_effort}` : "",
        conversation.service_tier
          ? `${context.t("请求速度档位")}: ${conversation.service_tier}` : "",
      ].filter(Boolean).join(" · ");
      runtimeStatus.textContent = [modelStatus, requested].filter(Boolean).join(" · ");
    }

    function renderConversation() {
      const conversation = current?.conversation || {};
      const selected = String(draft?.model_id || conversation.model_id || "");
      controls.model.replaceChildren();
      if (!current) {
        option(controls.model, "", context.t("请先选择会话"));
      } else if (!catalogLoaded) {
        option(controls.model, selected, selected || context.t("点击读取模型目录"));
      } else {
        for (const item of models) {
          option(
            controls.model,
            String(item.id || ""),
            String(item.display_name || item.id || ""),
          );
        }
        addSelectedFallback(controls.model, selected);
      }
      controls.model.value = selected;
      controls.model.disabled = readOnly || !current || saving;
      refresh.disabled = readOnly || saving;
      apply.disabled = readOnly || !current || saving || !selected;
      renderDependentChoices();
      const measured = contextUsage(conversation);
      progress.value = measured.percent;
      progress.hidden = !measured.capacity;
      usageText.textContent = measured.capacity
        ? context.t("上下文 %@ / %@（%@%）；累计 %@；压缩 %@ 次")
          .replace("%@", measured.used.toLocaleString())
          .replace("%@", measured.capacity.toLocaleString())
          .replace("%@", String(measured.percent))
          .replace("%@", measured.total.toLocaleString())
          .replace("%@", number(conversation.compaction_count).toLocaleString())
        : context.t("上下文容量将在首次响应后显示");
      catalogStatus.textContent = catalogValidated
        ? `${context.t("模型目录已验证")}${providerLatency
          ? ` · ${context.t("Provider 延迟")}: ${providerLatency} ms` : ""}`
        : context.t("模型目录尚未验证");
      renderRuntimeStatus(conversation);
    }

    function showNotice(message, kind = "info") {
      notice.textContent = message;
      notice.dataset.kind = message ? kind : "";
    }

    async function loadModels(refreshCatalog = false) {
      if (readOnly) return null;
      if (catalogPromise) return catalogPromise;
      if (catalogLoaded && !refreshCatalog) return models;
      showNotice(context.t("正在读取模型目录…"));
      const suffix = refreshCatalog ? "&refresh=1" : "";
      catalogPromise = context.api(
        `/api/client/profile-agent/models?profile_id=${
          encodeURIComponent(profile.profile_id)}${suffix}`,
      ).then(payload => {
        models = Array.isArray(payload.models) ? payload.models : [];
        catalogLoaded = true;
        catalogValidated = true;
        providerLatency = Number(payload.latency_ms) || 0;
        showNotice("");
        renderConversation();
        return models;
      }).catch(error => {
        showNotice(
          `${context.t("模型目录读取失败")}: ${error.message || ""}`,
          "error",
        );
        throw error;
      }).finally(() => { catalogPromise = null; });
      return catalogPromise;
    }

    async function applySettings() {
      if (readOnly || saving || !current || !draft?.model_id) return;
      const conversationID = current.conversationID;
      saving = true;
      showNotice(context.t("正在刷新目录并验证会话模型设置…"));
      renderConversation();
      try {
        const payload = await context.api(
          "/api/client/profile-agent/conversations/settings",
          {
            method: "POST",
            body: JSON.stringify({
              profile_id: profile.profile_id,
              conversation_id: conversationID,
              ...draft,
              refresh_catalog: true,
            }),
          },
        );
        if (payload.conversation && current?.conversationID === conversationID) {
          current.conversation = {...current.conversation, ...payload.conversation};
          draft = settingsOf(current.conversation);
        }
        catalogValidated = true;
        showNotice(
          context.t("目录验证通过，设置已保存；将在下一次提问时确认实际模型"),
          "success",
        );
      } catch (error) {
        if (current?.conversationID === conversationID) {
          draft = settingsOf(current.conversation);
        }
        showNotice(
          `${context.t("会话模型设置保存失败")}: ${error.message || ""}`,
          "error",
        );
      } finally {
        saving = false;
        renderConversation();
      }
    }

    controls.model.addEventListener("focus", () => loadModels().catch(() => {}));
    controls.model.addEventListener("pointerdown", () => loadModels().catch(() => {}));
    controls.model.addEventListener("change", () => {
      if (!draft) return;
      const model = selectedModel() || {};
      draft = {
        model_id: controls.model.value,
        reasoning_effort: String(model.default_reasoning_effort || ""),
        service_tier: String(model.default_service_tier || ""),
      };
      renderDependentChoices();
      showNotice(context.t("设置尚未应用"));
    });
    controls.effort.addEventListener("change", () => {
      if (!draft) return;
      draft.reasoning_effort = controls.effort.value;
      showNotice(context.t("设置尚未应用"));
    });
    controls.tier.addEventListener("change", () => {
      if (!draft) return;
      draft.service_tier = controls.tier.value;
      showNotice(context.t("设置尚未应用"));
    });
    refresh.addEventListener("click", () => loadModels(true).catch(() => {}));
    apply.addEventListener("click", applySettings);

    function setConversation(state) {
      current = state || null;
      draft = current ? settingsOf(current.conversation) : null;
      showNotice("");
      renderConversation();
    }

    function observeEvent(payload) {
      if (!current) return;
      const patch = runtimeEventPatch(payload, current.conversation);
      if (!Object.keys(patch).length) return;
      current.conversation = {...current.conversation, ...patch};
      renderConversation();
    }

    renderConversation();
    return {
      element: root,
      loadModels,
      observeEvent,
      setConversation,
      currentConversation: () => current?.conversation || null,
      dispose() { current = null; draft = null; },
    };
  }

  window.FTProfileAgentRuntimeControls = Object.freeze({
    contextUsage,
    create,
    runtimeEventPatch,
  });
})();
