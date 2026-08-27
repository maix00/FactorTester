(() => {
  let modelListSequence = 0;

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

  function providerPayload(view) {
    return {
      provider_id: view.providerID,
      label: view.label.value.trim(),
      runtime_kind: view.runtime.value,
      agent_runtime: view.agentRuntime.value,
      protocol: view.protocol.value,
      base_url: view.baseURL.value.trim(),
      default_model: view.model.value.trim(),
      network_route: view.runtime.value === "client" ? "direct" : view.networkRoute.value,
      token: view.token.value,
    };
  }

  function open(context, item, capabilities, refresh) {
    const dialog = document.createElement("dialog");
    dialog.dataset.ftTabID = context.tabID || "";
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
    const networkRouteDetails = Array.isArray(capabilities[0]?.network_route_details)
      ? capabilities[0].network_route_details : [];
    const networkRoute = select(context, networkRouteDetails.map(detail => ({
      value: detail.network_route,
      label: detail.label,
    })));
    networkRoute.value = item?.network_route || "direct";
    const updateNetworkRoute = () => {
      const clientRuntime = runtime.value === "client";
      if (clientRuntime) networkRoute.value = "direct";
      networkRoute.disabled = clientRuntime;
    };
    runtime.addEventListener("change", updateNetworkRoute);
    updateNetworkRoute();
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
      baseURL, model, networkRoute, token,
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
        if (Number.isFinite(result?.test?.latency_ms)) {
          status.textContent += ` · ${result.test.latency_ms} ms`;
        }
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
      field(context, "网络访问", networkRoute, "选择使用 Manager 网络代理时，Mihomo 不可用会明确报错，不会自动改为直连。"),
      field(context, "默认模型", modelControl, "聚焦时按需读取模型候选，也可以手动填写模型名称。"),
      field(context, "令牌", token, "令牌只写入当前运行时的本地加密存储，不会显示或同步到 PostgreSQL。"),
      actions, status,
    );
    dialog.append(card);
    dialog.addEventListener("close", () => dialog.remove(), {once: true});
    document.body.append(dialog);
    dialog.showModal();
  }

  window.FTAgentModelEditor = Object.freeze({open});
})();
