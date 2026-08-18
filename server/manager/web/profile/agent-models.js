(() => {
  let providers = [];
  let editingID = "";

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

  function input(type, value = "") {
    const control = document.createElement("input");
    control.className = "inline-setting";
    control.type = type;
    control.value = value;
    return control;
  }

  function select(values) {
    const control = document.createElement("select");
    control.className = "inline-setting";
    values.forEach(item => {
      const option = document.createElement("option");
      option.value = item.value;
      option.textContent = item.label;
      control.append(option);
    });
    return control;
  }

  function resetForm(view) {
    editingID = "";
    view.label.value = "";
    view.protocol.value = "openai_compatible";
    view.runtime.value = "server";
    view.baseURL.value = "";
    view.model.value = "";
    view.token.value = "";
    view.token.placeholder = "";
    view.heading.textContent = view.context.t("新增模型服务");
    view.save.textContent = view.context.t("保存模型服务");
    view.cancel.hidden = true;
  }

  function form(context, refresh) {
    const section = document.createElement("section");
    section.className = "settings-section agent-model-form";
    const heading = document.createElement("h3");
    heading.textContent = context.t("新增模型服务");
    const status = document.createElement("p");
    status.className = "settings-muted";

    const label = input("text");
    label.required = true;
    const runtime = select([
      {value: "server", label: context.t("服务器运行")},
      {value: "client", label: context.t("客户端运行")},
    ]);
    const protocol = select([
      {value: "openai_compatible", label: "OpenAI-compatible"},
      {value: "codex", label: "Codex"},
    ]);
    const baseURL = input("url");
    baseURL.required = true;
    baseURL.placeholder = "https://api.example.com/v1";
    const model = input("text");
    model.required = true;
    const token = input("password");
    token.autocomplete = "new-password";
    const save = document.createElement("button");
    save.className = "primary";
    save.type = "button";
    save.textContent = context.t("保存模型服务");
    const cancel = document.createElement("button");
    cancel.className = "secondary";
    cancel.classList.add("agent-model-cancel");
    cancel.type = "button";
    cancel.textContent = context.t("取消编辑");
    cancel.hidden = true;
    cancel.onclick = () => resetForm(view);
    const actions = document.createElement("div");
    actions.className = "settings-inline-actions";
    actions.append(save, cancel);
    section.append(
      heading,
      field(context, "服务名称", label),
      field(context, "运行方式", runtime, "服务器凭证只保存在当前 Manager；客户端凭证由本地客户端管理。"),
      field(context, "协议", protocol),
      field(context, "API 地址", baseURL, "服务器运行的模型服务必须使用 HTTPS。"),
      field(context, "默认模型", model),
      field(context, "令牌", token, "令牌只写入当前运行时的本地加密存储，不会显示或同步到 PostgreSQL。"),
      actions,
      status,
    );

    const view = {
      context, heading, label, runtime, protocol, baseURL, model, token,
      save, cancel,
    };
    save.onclick = async () => {
      if (!label.value.trim() || !baseURL.value.trim() || !model.value.trim()) {
        status.textContent = context.t("请填写服务名称、API 地址和默认模型");
        return;
      }
      save.disabled = true;
      status.textContent = context.t("正在保存…");
      try {
        await context.api("/api/client/agent-models", {
          method: "POST",
          body: JSON.stringify({
            provider_id: editingID,
            label: label.value.trim(),
            runtime_kind: runtime.value,
            protocol: protocol.value,
            base_url: baseURL.value.trim(),
            default_model: model.value.trim(),
            token: token.value,
          }),
        });
        resetForm(view);
        context.showNotice(context.t("模型服务已保存"));
        await refresh();
      } catch (error) {
        status.textContent = error.message || context.t("保存失败");
      } finally {
        save.disabled = false;
      }
    };
    return {section, view};
  }

  function table(context, refresh, view) {
    const table = FTUI.table([
      "服务名称", "运行方式", "协议", "API 地址", "默认模型", "令牌", "操作",
    ], []);
    table.shell.classList.add("agent-model-table");
    providers.forEach(item => {
      const edit = document.createElement("button");
      edit.className = "secondary";
      edit.textContent = context.t("编辑");
      edit.onclick = () => {
        editingID = item.provider_id;
        view.label.value = item.label || "";
        view.runtime.value = item.runtime_kind || "server";
        view.protocol.value = item.protocol || "openai_compatible";
        view.baseURL.value = item.base_url || "";
        view.model.value = item.default_model || "";
        view.token.value = "";
        view.token.placeholder = item.token_configured
          ? context.t("已配置 · 留空保持不变") : "";
        view.heading.textContent = context.t("编辑模型服务");
        view.cancel.hidden = false;
      };
      const remove = document.createElement("button");
      remove.className = "secondary";
      remove.textContent = context.t("删除");
      remove.onclick = async () => {
        try {
          await context.api(`/api/client/agent-models/${encodeURIComponent(item.provider_id)}`, {method: "DELETE"});
          await refresh();
        } catch (error) {
          context.showNotice(error.message, true);
        }
      };
      const actions = document.createElement("span");
      actions.append(edit, remove);
      FTUI.appendRow(table.body, [
        item.label || "", item.runtime_kind === "client" ? context.t("客户端运行") : context.t("服务器运行"),
        item.protocol || "", item.base_url || "", item.default_model || "",
        item.token_configured ? context.t("已配置") : context.t("未配置"), actions,
      ]);
    });
    return table.shell;
  }

  async function list(context) {
    if (!current(context)) return;
    context.content.replaceChildren(FTUI.loading(context.t("正在读取模型服务…")));
    let payload;
    try {
      payload = await context.api("/api/client/agent-models");
    } catch (error) {
      context.content.replaceChildren(FTUI.empty(context.t("无法读取"), error.message));
      return;
    }
    if (!current(context)) return;
    providers = Array.isArray(payload.providers) ? payload.providers : [];
    const root = document.createElement("div");
    root.className = "agent-models-page";
    const intro = document.createElement("p");
    intro.className = "settings-muted";
    intro.textContent = context.t("模型服务只用于当前客户端或当前服务器上的 Agent；FactorTester 不会代替用户保存或转发令牌。");
    root.append(intro);
    const formView = form(context, () => list(context));
    root.append(formView.section);
    if (providers.length) {
      const heading = document.createElement("h3");
      heading.textContent = context.t("已保存的模型服务");
      root.append(heading, table(context, () => list(context), formView.view));
    } else {
      root.append(FTUI.empty(context.t("尚无已保存模型服务"), context.t("请先添加一个模型服务。")));
    }
    context.content.replaceChildren(root);
  }

  window.FTAgentModels = {list};
})();
