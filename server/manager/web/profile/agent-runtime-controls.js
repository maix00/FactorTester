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
    const root = document.createElement("section");
    root.className = "profile-agent-runtime-controls";
    const fields = document.createElement("div");
    fields.className = "profile-agent-runtime-fields";
    const status = document.createElement("p");
    status.className = "settings-muted profile-agent-runtime-status";
    status.setAttribute("aria-live", "polite");
    const usage = document.createElement("div");
    usage.className = "profile-agent-context-usage";
    const progress = document.createElement("progress");
    progress.max = 100;
    progress.value = 0;
    const usageText = document.createElement("span");
    usage.append(progress, usageText);
    root.append(fields, usage, status);

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
    let models = [];
    let catalogLoaded = false;
    let catalogPromise = null;
    let saveQueue = Promise.resolve();

    function option(select, value, label) {
      const item = document.createElement("option");
      item.value = value;
      item.textContent = label;
      select.append(item);
    }

    function selectedModel() {
      return models.find(item => String(item.id || "") === controls.model.value);
    }

    function renderDependentChoices() {
      const model = selectedModel() || {};
      const conversation = current?.conversation || {};
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
      controls.effort.value = String(conversation.reasoning_effort || "");
      controls.tier.value = String(conversation.service_tier || "");
      controls.effort.disabled = readOnly || !current;
      controls.tier.disabled = readOnly || !current;
    }

    function renderConversation() {
      const conversation = current?.conversation || {};
      const selected = String(conversation.model_id || "");
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
        if (selected && !models.some(item => String(item.id || "") === selected)) {
          option(controls.model, selected, selected);
        }
      }
      controls.model.value = selected;
      controls.model.disabled = readOnly || !current;
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
      const actual = String(conversation.actual_model || "");
      status.textContent = actual && selected && actual !== selected
        ? `${context.t("实际模型")}: ${actual} · ${context.t("已发生模型重路由")}`
        : actual ? `${context.t("实际模型")}: ${actual}` : "";
    }

    async function loadModels(refresh = false) {
      if (readOnly || catalogPromise || catalogLoaded && !refresh) {
        return catalogPromise;
      }
      const suffix = refresh ? "&refresh=1" : "";
      status.textContent = context.t("正在读取模型目录…");
      catalogPromise = context.api(
        `/api/client/profile-agent/models?profile_id=${
          encodeURIComponent(profile.profile_id)}${suffix}`,
      ).then(payload => {
        models = Array.isArray(payload.models) ? payload.models : [];
        catalogLoaded = true;
        status.textContent = payload.latency_ms
          ? `${context.t("Provider 延迟")}: ${payload.latency_ms} ms` : "";
        renderConversation();
      }).catch(error => {
        status.textContent = `${context.t("模型目录读取失败")}: ${error.message || ""}`;
      }).finally(() => { catalogPromise = null; });
      return catalogPromise;
    }

    function saveSettings() {
      if (readOnly || !current || !controls.model.value) return;
      const snapshot = {
        profile_id: profile.profile_id,
        conversation_id: current.conversationID,
        model_id: controls.model.value,
        reasoning_effort: controls.effort.value,
        service_tier: controls.tier.value,
      };
      status.textContent = context.t("正在保存会话模型设置…");
      saveQueue = saveQueue.then(() => context.api(
        "/api/client/profile-agent/conversations/settings",
        {method: "POST", body: JSON.stringify(snapshot)},
      )).then(payload => {
        if (payload.conversation && current) {
          current.conversation = {...current.conversation, ...payload.conversation};
        }
        status.textContent = context.t("会话模型设置已保存");
        renderConversation();
      }).catch(error => {
        status.textContent = `${context.t("会话模型设置保存失败")}: ${error.message || ""}`;
      });
    }

    controls.model.addEventListener("focus", () => loadModels());
    controls.model.addEventListener("pointerdown", () => loadModels());
    controls.model.addEventListener("change", () => {
      const model = selectedModel() || {};
      if (current) {
        current.conversation.model_id = controls.model.value;
        current.conversation.reasoning_effort = String(
          model.default_reasoning_effort || "",
        );
        current.conversation.service_tier = String(
          model.default_service_tier || "",
        );
      }
      renderDependentChoices();
      saveSettings();
    });
    controls.effort.addEventListener("change", saveSettings);
    controls.tier.addEventListener("change", saveSettings);

    function setConversation(state) {
      current = state || null;
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
      dispose() { current = null; },
    };
  }

  window.FTProfileAgentRuntimeControls = Object.freeze({
    contextUsage,
    create,
    runtimeEventPatch,
  });
})();
