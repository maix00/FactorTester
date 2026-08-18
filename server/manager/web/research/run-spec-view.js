(() => {
  const object = value => value && typeof value === "object" && !Array.isArray(value)
    ? value : {};

  function model(value) {
    const record = object(value);
    const contract = object(record.run_spec);
    const configuration = object(contract.configuration);
    const identity = {
      run_spec_hash: record.run_spec_hash || "",
      run_spec_version: record.run_spec_version ?? contract.run_spec_version ?? "",
      configuration_id: record.configuration_id || contract.configuration_id || "",
      configuration_revision: record.configuration_revision
        ?? contract.configuration_revision ?? "",
      workspace_id: contract.workspace_id || "",
      configuration_fingerprint: contract.configuration_fingerprint || "",
    };
    const execution = Object.fromEntries(Object.entries(contract).filter(([key]) => ![
      "configuration", "configuration_id", "configuration_revision",
      "configuration_fingerprint", "run_spec_version", "workspace_id",
    ].includes(key)));
    return {
      identity,
      title: String(record.alias_zh || ""),
      summary: String(record.summary_zh || ""),
      configuration,
      execution,
    };
  }

  function nonEmptyEntries(value) {
    return Object.entries(value || {}).filter(([, item]) => (
      item !== "" && item != null
    ));
  }

  function identityTable(context, identity) {
    const labels = {
      run_spec_hash: "运行配置哈希",
      run_spec_version: "运行配置版本",
      configuration_id: "来源配置 ID",
      configuration_revision: "来源配置版本",
      workspace_id: "工作区",
      configuration_fingerprint: "配置指纹",
    };
    const rows = nonEmptyEntries(identity).map(([key, value]) => [
      context.t(labels[key] || key), String(value),
    ]);
    return FTUI.table([context.t("字段"), context.t("值")], rows).shell;
  }

  function objectSection(context, title, value, open = true) {
    const details = document.createElement("details");
    details.className = "run-spec-section";
    details.open = open;
    const summary = document.createElement("summary");
    summary.textContent = context.t(title);
    const body = document.createElement("div");
    body.className = "run-spec-section-body";
    body.append(FTUI.code(value));
    details.append(summary, body);
    return details;
  }

  function render(context, value) {
    const view = model(value);
    const root = document.createElement("div");
    root.className = "run-spec-view";
    if (view.summary || view.title) {
      const intro = document.createElement("div");
      intro.className = "run-spec-summary";
      if (view.title) {
        const title = document.createElement("strong");
        title.textContent = view.title;
        intro.append(title);
      }
      if (view.summary) {
        const copy = document.createElement("p");
        copy.textContent = view.summary;
        intro.append(copy);
      }
      root.append(intro);
    }
    const identity = document.createElement("section");
    identity.className = "run-spec-identity";
    const heading = document.createElement("h3");
    heading.textContent = context.t("配置身份");
    identity.append(heading, identityTable(context, view.identity));
    root.append(identity);
    root.append(
      objectSection(context, "冻结配置内容", view.configuration),
      objectSection(context, "执行合同", view.execution),
    );
    return root;
  }

  function digest(target) {
    const value = String(target || "");
    const prefixes = ["runspec:sha256:", "run-spec:sha256:", "run_spec:sha256:"];
    const prefix = prefixes.find(item => value.startsWith(item));
    const result = prefix ? value.slice(prefix.length) : value.replace(/^sha256:/, "");
    return /^[a-f0-9]{64}$/i.test(result) ? result.toLowerCase() : "";
  }

  async function load(context, target, serverID = "") {
    const hash = digest(target);
    if (!hash) throw new Error(context.t("运行配置引用无效"));
    const suffix = serverID
      ? `?server_id=${encodeURIComponent(serverID)}` : "";
    const payload = await context.api(
      `/api/run-specs/${encodeURIComponent(hash)}${suffix}`,
    );
    return payload?.run_spec || payload;
  }

  function open(context, target, serverID = "") {
    const dialog = document.createElement("dialog");
    dialog.className = "run-spec-dialog";
    const card = document.createElement("article");
    card.className = "dialog-card run-spec-dialog-card";
    const close = document.createElement("button");
    close.type = "button";
    close.className = "dialog-close";
    close.textContent = "×";
    close.title = context.t("关闭");
    const header = document.createElement("div");
    header.className = "section-heading run-spec-dialog-heading";
    const copy = document.createElement("div");
    const title = document.createElement("h2");
    title.textContent = context.t("运行配置");
    const description = document.createElement("p");
    description.textContent = context.t("查看来源配置身份与冻结执行合同");
    copy.append(title, description);
    const independent = FTUI.actionButton(context.t("在独立页面打开"), () => {
      dialog.close();
      context.navigate(FTReferencePage.routeFor(
        "run-spec", target, context.t("运行配置"), serverID,
      ));
    });
    header.append(copy, independent);
    const body = document.createElement("div");
    body.className = "run-spec-dialog-body";
    body.append(FTUI.loading(context.t("正在读取运行配置…")));
    close.addEventListener("click", () => dialog.close());
    dialog.addEventListener("close", () => dialog.remove());
    dialog.addEventListener("cancel", event => {
      event.preventDefault();
      dialog.close();
    });
    card.append(close, header, body);
    dialog.append(card);
    document.body.append(dialog);
    dialog.showModal();
    load(context, target, serverID).then(value => {
      body.replaceChildren(render(context, value));
    }).catch(error => {
      body.replaceChildren(FTUI.empty(
        context.t("无法读取运行配置"), error.message || String(error),
      ));
    });
    return dialog;
  }

  window.FTRunSpecView = Object.freeze({digest, load, model, open, render});
})();
