(() => {
  const PAGE_SIZE = 20;

  const text = value => value == null ? "" : String(value);

  function endpoint({page, query, application, role, client}) {
    const params = new URLSearchParams({
      page: String(page), page_size: String(PAGE_SIZE),
      client: client || "web",
    });
    if (query) params.set("query", query);
    if (application) params.set("application", application);
    if (role) params.set("role", role);
    return `/api/docs/test-fields?${params}`;
  }

  function displayDefault(value) {
    if (value === null || value === undefined) return "省略 / null";
    if (typeof value === "object") {
      try { return JSON.stringify(value); } catch (_) { return "对象"; }
    }
    return text(value);
  }

  function render(context, mount) {
    const root = document.createElement("section");
    root.className = "technical-docs-field-catalog";
    const controls = document.createElement("div");
    controls.className = "technical-docs-field-controls";
    const search = document.createElement("input");
    search.type = "search";
    search.placeholder = context.t("按字段名、标签或测试类型搜索");
    search.setAttribute("aria-label", context.t("搜索测试字段"));
    const application = document.createElement("select");
    application.setAttribute("aria-label", context.t("筛选测试类型"));
    const role = document.createElement("select");
    role.setAttribute("aria-label", context.t("筛选字段角色"));
    const client = document.createElement("select");
    client.setAttribute("aria-label", context.t("筛选客户端契约"));
    controls.append(search, application, role, client);
    const body = document.createElement("div");
    body.className = "technical-docs-field-table";
    root.append(controls, body);
    mount.append(root);

    let page = 1;
    let selectedClient = "web";
    let debounce = null;
    let requestToken = 0;

    function setOptions(select, values, emptyLabel) {
      const current = select.value;
      select.replaceChildren(new Option(emptyLabel, ""));
      for (const value of values || []) select.append(new Option(text(value), text(value)));
      if ([...select.options].some(item => item.value === current)) select.value = current;
    }

    async function load(nextPage = page) {
      const token = ++requestToken;
      page = nextPage;
      body.replaceChildren(FTUI.loading(context.t("正在加载测试字段…")));
      try {
        const payload = await context.api(endpoint({
          page,
          query: search.value.trim(),
          application: application.value,
          role: role.value,
          client: selectedClient,
        }));
        if (token !== requestToken) return;
        setOptions(application, payload.applications, context.t("全部测试类型"));
        setOptions(role, payload.roles, context.t("全部字段角色"));
        setOptions(client, payload.clients, context.t("Web 客户端契约"));
        client.value = payload.client || selectedClient;
        const fields = Array.isArray(payload.fields) ? payload.fields : [];
        const view = FTUI.pagedTable(
          [
            context.t("测试类型"), context.t("角色"), context.t("字段路径"),
            context.t("字段"), context.t("模块"),
            context.t("值类型"), context.t("基数"), context.t("作用域"),
            context.t("注册默认值"),
          ],
          fields.map(field => [
            field.application,
            field.role,
            field.field_path || field.key,
            `${text(field.label)} (${text(field.key)})`,
            field.module || "—",
            field.value_type,
            field.cardinality,
            field.scope_policy || field.placement,
            displayDefault(field.default),
          ]),
          {
            remote: true,
            page: payload.page,
            pageSize: payload.page_size,
            total: payload.total,
            previousLabel: context.t("上一页"),
            nextLabel: context.t("下一页"),
            pageLabel: (current, total) => `${current} / ${total}`,
            totalLabel: total => `${context.t("共")} ${total} ${context.t("个字段")}`,
            onPageChange: next => load(next),
          },
        );
        view.shell.classList.add("technical-docs-field-paged-table");
        body.replaceChildren(view.shell);
      } catch (error) {
        if (token !== requestToken) return;
        body.replaceChildren(FTUI.empty(
          context.t("测试字段暂时不可用"),
          text(error?.message || error),
        ));
      }
    }

    function restart() {
      page = 1;
      load(1);
    }
    search.addEventListener("input", () => {
      clearTimeout(debounce);
      debounce = setTimeout(restart, 180);
    });
    application.addEventListener("change", restart);
    role.addEventListener("change", restart);
    client.addEventListener("change", () => {
      selectedClient = client.value || "web";
      restart();
    });
    load();
  }

  window.FTDocsFieldCatalog = Object.freeze({render});
})();
