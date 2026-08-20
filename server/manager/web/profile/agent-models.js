(() => {
  const pageSize = 20;

  function current(context) {
    return context.isRouteCurrent?.() !== false;
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

  async function testExisting(context, item, status) {
    status.className = "agent-model-test-status checking";
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
      if (Number.isFinite(result?.test?.latency_ms)) {
        status.textContent += ` · ${result.test.latency_ms} ms`;
      }
      status.className = "agent-model-test-status success";
    } catch (error) {
      status.textContent = error.message || context.t("连接测试失败");
      status.className = "agent-model-test-status failure";
    }
  }

  function table(context, providers, capabilities, page, onPageChange, refresh) {
    const details = protocolDetails(capabilities);
    const rows = providers.map(item => {
      const status = document.createElement("span");
      status.className = "agent-model-test-status";
      status.textContent = context.t("未测试");
      const actions = document.createElement("span");
      actions.className = "agent-model-actions";
      actions.append(
        iconButton(context, "play.circle", "测试连接", () => void testExisting(context, item, status)),
        iconButton(context, "square.and.pencil", "编辑", () => (
          FTAgentModelEditor.open(context, item, capabilities, refresh)
        )),
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
        onPageChange,
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
      const state = {page: requestedPage, query: "", renderFrame: 0};
      const intro = document.createElement("p");
      intro.className = "settings-muted";
      intro.textContent = context.t("模型服务只显示当前账户的配置；令牌不会同步到其他用户。");
      const add = context.button(
        context.t("新增模型服务"),
        () => FTAgentModelEditor.open(
          context, null, capabilities, () => list(context, requestedPage),
        ),
        context.t("新增模型服务"),
      );
      add.className = "primary agent-model-add";
      const header = document.createElement("div");
      header.className = "agent-model-header";
      header.append(intro, add);
      root.append(header);
      if (providers.length) {
        const toolbar = document.createElement("div");
        toolbar.className = "agent-model-list-toolbar";
        const search = document.createElement("input");
        search.type = "search";
        search.className = "inline-setting agent-model-search";
        search.placeholder = context.t("搜索服务、协议、地址或模型");
        search.setAttribute("aria-label", context.t("搜索模型服务"));
        const count = document.createElement("span");
        count.className = "agent-model-result-count settings-muted";
        const tableHost = document.createElement("div");
        tableHost.className = "agent-model-table-host";
        const filteredProviders = () => {
          const query = state.query.toLocaleLowerCase();
          if (!query) return providers;
          return providers.filter(item => [
            item.label, item.runtime_kind, item.agent_runtime, item.protocol,
            item.base_url, item.default_model,
          ].some(value => String(value || "").toLocaleLowerCase().includes(query)));
        };
        const renderTable = () => {
          const visible = filteredProviders();
          const pages = Math.max(1, Math.ceil(visible.length / pageSize));
          state.page = Math.min(state.page, pages);
          count.textContent = context.t("显示 %lld / %total 个")
            .replace("%lld", String(visible.length))
            .replace("%total", String(providers.length));
          if (!visible.length) {
            tableHost.replaceChildren(FTUI.empty(
              context.t("没有匹配的模型服务"),
              context.t("清除搜索条件后可查看全部模型服务。"),
            ));
            return;
          }
          tableHost.replaceChildren(table(
            context, visible, capabilities, state.page,
            next => { state.page = next; renderTable(); },
            () => list(context, state.page),
          ));
        };
        search.addEventListener("input", () => {
          state.query = search.value.trim();
          state.page = 1;
          if (state.renderFrame) cancelAnimationFrame(state.renderFrame);
          state.renderFrame = requestAnimationFrame(() => {
            state.renderFrame = 0;
            renderTable();
          });
        });
        toolbar.append(search, count);
        root.append(toolbar, tableHost);
        renderTable();
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
