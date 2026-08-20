(() => {
  const pageSize = 20;
  let modelListSequence = 0;

  function current(context) {
    return context.isRouteCurrent?.() !== false;
  }

  function field(context, label, control, description = "") {
    const row = document.createElement("div");
    row.className = "settings-row";
    const copy = document.createElement("div");
    const title = document.createElement("b");
    title.textContent = context.t(label);
    copy.append(title);
    if (description) {
      const note = document.createElement("small");
      note.textContent = context.t(description);
      copy.append(note);
    }
    const value = document.createElement("div");
    value.className = "settings-value";
    value.append(control);
    row.append(copy, value);
    return row;
  }

  function control(type, value = "") {
    const input = document.createElement("input");
    input.className = "inline-setting";
    input.type = type;
    input.value = value;
    return input;
  }

  function select(context, values) {
    const input = document.createElement("select");
    input.className = "inline-setting";
    values.forEach(item => {
      const option = document.createElement("option");
      option.value = item.value;
      option.textContent = context.t(item.label);
      input.append(option);
    });
    return input;
  }

  function protocolDetails(capabilities) {
    const result = new Map();
    capabilities.forEach(capability => {
      (Array.isArray(capability.protocol_details)
        ? capability.protocol_details : []).forEach(item => {
        if (item?.protocol) result.set(item.protocol, item);
      });
    });
    return result;
  }

  function badge(context, label, kind = "") {
    const value = document.createElement("span");
    value.className = `agent-model-badge ${kind}`.trim();
    value.textContent = context.t(label);
    return value;
  }

  function iconButton(context, symbol, label, action) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "agent-model-icon-action";
    button.title = context.t(label);
    button.setAttribute("aria-label", context.t(label));
    button.append(FTIcons.node(symbol));
    button.addEventListener("click", event => {
      event.stopPropagation();
      action(event);
    });
    return button;
  }

  function providerPayload(view) {
    return {
      provider_id: view.providerID,
      label: view.label.value.trim(),
      runtime_kind: view.runtime.value,
      agent_runtime: view.agentRuntime.value,
      protocol: view.protocol.value,
      base_url: view.baseURL.value.trim(),
      default_model: view.model.value.trim(),
      token: view.token.value,
    };
  }

  function openEditor(context, item, capabilities, refresh) {
    const dialog = document.createElement("dialog");
    dialog.className = "ft-dialog agent-model-dialog";
    const card = document.createElement("div");
    card.className = "dialog-card wide";
    const heading = document.createElement("h2");
    heading.textContent = context.t(item ? "编辑模型服务" : "新增模型服务");
    const close = context.button(context.t("关闭"), () => dialog.close(), context.t("关闭"));
    close.className = "dialog-close";
    card.append(heading, close);

    const label = control("text", item?.label || "");
    label.required = true;
    const runtime = select(context, [
      {value: "server", label: "服务器运行"},
      {value: "client", label: "客户端运行"},
    ]);
    runtime.value = item?.runtime_kind || "server";
    const agentRuntime = select(context, capabilities.map(capability => ({
      value: capability.runtime,
      label: capability.executable_label || capability.runtime,
    })));
    agentRuntime.value = item?.agent_runtime || "codex";
    const protocol = select(context, []);
    const details = protocolDetails(capabilities);
    let updateProtocolHint = () => {};
    const updateProtocols = preferred => {
      const capability = capabilities.find(entry => entry.runtime === agentRuntime.value);
      const protocols = Array.isArray(capability?.protocols) ? capability.protocols : [];
      protocol.replaceChildren();
      protocols.forEach(value => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = context.t(details.get(value)?.label || value);
        protocol.append(option);
      });
      protocol.value = protocols.includes(preferred) ? preferred : (protocols[0] || "");
      updateProtocolHint();
    };
    updateProtocols(item?.protocol || "openai_responses");
    agentRuntime.addEventListener("change", () => updateProtocols(""));
    const baseURL = control("url", item?.base_url || "");
    baseURL.required = true;
    baseURL.placeholder = "https://api.example.com/v1";
    const model = control("text", item?.default_model || "");
    model.required = true;
    const modelList = document.createElement("datalist");
    modelList.id = `agent-model-options-${++modelListSequence}`;
    model.setAttribute("list", modelList.id);
    const modelControl = document.createElement("div");
    modelControl.className = "agent-model-model-control";
    modelControl.append(model, modelList);
    let modelCatalogLoaded = false;
    const applyModelCatalog = result => {
      const models = Array.isArray(result?.test?.available_models)
        ? result.test.available_models : [];
      modelList.replaceChildren(...models.map(value => Object.assign(
        document.createElement("option"), {value: String(value)},
      )));
      modelCatalogLoaded = true;
    };
    const token = control("password");
    token.autocomplete = "new-password";
    token.placeholder = item?.token_configured
      ? context.t("已配置 · 留空保持不变") : "";
    const status = document.createElement("p");
    status.className = "agent-model-test-status settings-muted";
    const test = context.button(context.t("测试连接"), () => {}, context.t("测试连接"));
    test.className = "secondary";
    const save = context.button(context.t("保存模型服务"), () => {}, context.t("保存模型服务"));
    save.className = "primary";
    const actions = document.createElement("div");
    actions.className = "settings-inline-actions";
    actions.append(test, save);
    const view = {
      providerID: item?.provider_id || "", label, runtime, agentRuntime, protocol,
      baseURL, model, token,
    };
    const validate = () => {
      if (!label.value.trim() || !baseURL.value.trim() || !model.value.trim()) {
        status.textContent = context.t("请填写服务名称、API 地址和默认模型");
        return false;
      }
      return true;
    };
    test.onclick = async () => {
      if (!validate()) return;
      test.disabled = true; save.disabled = true;
      status.textContent = context.t("正在测试连接…");
      try {
        const result = await context.api("/api/client/agent-models/test", {
          method: "POST", body: JSON.stringify(providerPayload(view)),
        });
        applyModelCatalog(result);
        status.textContent = context.t("连接成功：模型可用");
        if (result?.test?.default_model) status.textContent += ` · ${result.test.default_model}`;
      } catch (error) {
        status.textContent = error.message || context.t("连接测试失败");
      } finally {
        test.disabled = false; save.disabled = false;
      }
    };
    model.addEventListener("focus", () => {
      if (!item?.provider_id || modelCatalogLoaded || test.disabled) return;
      void test.onclick();
    });
    save.onclick = async () => {
      if (!validate()) return;
      test.disabled = true; save.disabled = true;
      status.textContent = context.t("正在保存…");
      try {
        await context.api("/api/client/agent-models", {
          method: "POST", body: JSON.stringify(providerPayload(view)),
        });
        context.showNotice(context.t("模型服务已保存"));
        dialog.close();
        await refresh();
      } catch (error) {
        status.textContent = error.message || context.t("保存失败");
        test.disabled = false; save.disabled = false;
      }
    };
    const protocolHint = document.createElement("small");
    updateProtocolHint = () => {
      const detail = details.get(protocol.value);
      protocolHint.textContent = detail
        ? context.t(detail.transport_label || detail.transport || "") : "";
    };
    protocol.addEventListener("change", updateProtocolHint);
    updateProtocolHint();
    const protocolControl = document.createElement("div");
    protocolControl.className = "agent-model-protocol-control";
    protocolControl.append(protocol, protocolHint);
    card.append(
      field(context, "服务名称", label),
      field(context, "运行方式", runtime, "服务器凭证只保存在当前 Manager；客户端凭证由本地客户端管理。"),
      field(context, "智能体运行", agentRuntime),
      field(context, "协议", protocolControl),
      field(context, "API 地址", baseURL, "服务器运行的模型服务必须使用 HTTPS。"),
      field(context, "默认模型", modelControl, "聚焦时按需读取模型候选，也可以手动填写模型名称。"),
      field(context, "令牌", token, "令牌只写入当前运行时的本地加密存储，不会显示或同步到 PostgreSQL。"),
      actions, status,
    );
    dialog.append(card);
    dialog.addEventListener("close", () => dialog.remove(), {once: true});
    document.body.append(dialog);
    dialog.showModal();
  }

  async function testExisting(context, item, status) {
    status.textContent = context.t("正在测试…");
    try {
      const result = await context.api("/api/client/agent-models/test", {
        method: "POST",
        body: JSON.stringify({
          provider_id: item.provider_id,
          label: item.label,
          runtime_kind: item.runtime_kind,
          agent_runtime: item.agent_runtime,
          protocol: item.protocol,
          base_url: item.base_url,
          default_model: item.default_model,
          token: "",
        }),
      });
      status.textContent = result?.test?.default_model
        ? `${context.t("连接成功")} · ${result.test.default_model}`
        : context.t("连接成功");
    } catch (error) {
      status.textContent = error.message || context.t("连接测试失败");
    }
  }

  function table(context, providers, capabilities, page, refresh) {
    const details = protocolDetails(capabilities);
    const rows = providers.map(item => {
      const status = document.createElement("span");
      status.className = "agent-model-test-status";
      status.textContent = context.t("未测试");
      const actions = document.createElement("span");
      actions.className = "agent-model-actions";
      actions.append(
        iconButton(context, "play.circle", "测试连接", () => void testExisting(context, item, status)),
        iconButton(context, "square.and.pencil", "编辑", () => openEditor(context, item, capabilities, refresh)),
        iconButton(context, "trash", "删除", async () => {
          if (!window.confirm(context.t("确定删除这个模型服务吗？"))) return;
          try {
            await context.api(`/api/client/agent-models/${encodeURIComponent(item.provider_id)}`, {method: "DELETE"});
            await refresh();
          } catch (error) {
            context.showNotice(error.message || String(error), true);
          }
        }),
      );
      const protocol = document.createElement("span");
      protocol.className = "agent-model-protocol-cell";
      const detail = details.get(item.protocol);
      protocol.append(
        document.createTextNode(context.t(detail?.label || item.protocol || "")),
        badge(
          context,
          detail?.transport_label || detail?.transport || "",
          detail?.transport || "",
        ),
      );
      return [
        item.label || "",
        item.runtime_kind === "client" ? context.t("客户端运行") : context.t("服务器运行"),
        item.agent_runtime || "codex", protocol, item.base_url || "", item.default_model || "",
        item.token_configured ? context.t("已配置") : context.t("未配置"),
        status, actions,
      ];
    });
    const view = FTUI.pagedTable(
      ["服务名称", "运行方式", "智能体运行", "协议", "API 地址", "默认模型", "令牌", "连接状态", "操作"].map(
        label => context.t(label),
      ),
      rows,
      {
        page, pageSize,
        totalLabel: total => context.t("共 %lld 个").replace("%lld", String(total)),
        onPageChange: next => refresh(next),
      },
    );
    view.shell.classList.add("agent-model-table");
    return view.shell;
  }

  async function list(context, requestedPage = 1) {
    if (!current(context)) return;
    context.content.replaceChildren(FTUI.loading(context.t("正在读取模型服务…")));
    try {
      const payload = await context.api("/api/client/agent-models");
      if (!current(context)) return;
      const providers = Array.isArray(payload.providers) ? payload.providers : [];
      const capabilities = Array.isArray(payload.runtime_capabilities)
        ? payload.runtime_capabilities : [];
      const root = document.createElement("div");
      root.className = "agent-models-page";
      const intro = document.createElement("p");
      intro.className = "settings-muted";
      intro.textContent = context.t("模型服务只显示当前账户的配置；令牌不会同步到其他用户。");
      const add = context.button(
        context.t("新增模型服务"),
        () => openEditor(context, null, capabilities, () => list(context, requestedPage)),
        context.t("新增模型服务"),
      );
      add.className = "primary agent-model-add";
      const header = document.createElement("div");
      header.className = "agent-model-header";
      header.append(intro, add);
      root.append(header);
      if (providers.length) {
        root.append(table(context, providers, capabilities, requestedPage, page => list(context, page)));
      } else {
        root.append(FTUI.empty(context.t("尚无已保存模型服务"), context.t("请先添加一个模型服务。")));
      }
      context.content.replaceChildren(root);
    } catch (error) {
      context.content.replaceChildren(FTUI.empty(context.t("无法读取"), error.message));
    }
  }

  window.FTAgentModels = Object.freeze({list});
})();
