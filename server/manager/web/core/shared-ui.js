(() => {
  const text = value => value == null ? "" : String(value);

  function table(headers, rows = []) {
    const shell = document.createElement("div"); shell.className = "table-shell";
    if (shell.dataset) shell.dataset.ftScrollState = "shared-table";
    const element = document.createElement("table");
    const head = element.createTHead().insertRow();
    headers.forEach(label => {
      const cell = document.createElement("th"); cell.textContent = label; head.append(cell);
    });
    const body = element.createTBody();
    rows.forEach(values => appendRow(body, values));
    shell.append(element);
    return {shell, table: element, body};
  }

  function pagedTable(headers, rows = [], options = {}) {
    const pageSize = Math.max(1, Number(options.pageSize) || 20);
    const remote = options.remote === true;
    const total = remote
      ? Math.max(rows.length, Number(options.total) || 0)
      : rows.length;
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    const page = Math.min(totalPages, Math.max(1, Number(options.page) || 1));
    const start = (page - 1) * pageSize;
    const view = table(headers, remote ? rows : rows.slice(start, start + pageSize));
    const pagination = document.createElement("div");
    pagination.className = "product-list-pagination shared-table-pagination";
    const previous = actionButton(options.previousLabel || "上一页", () => {
      if (page > 1) options.onPageChange?.(page - 1);
    });
    previous.disabled = page <= 1;
    const next = actionButton(options.nextLabel || "下一页", () => {
      if (page < totalPages) options.onPageChange?.(page + 1);
    });
    next.disabled = page >= totalPages;
    pagination.append(
      previous,
      Object.assign(document.createElement("span"), {
        className: "product-list-page-label",
        textContent: String(options.pageLabel?.(page, totalPages)
          || `${page} / ${totalPages}`),
      }),
      next,
      Object.assign(document.createElement("span"), {
        className: "product-list-total",
        textContent: String(options.totalLabel?.(total) || total),
      }),
    );
    // Keep the table's vertical scroll container separate from the pager.  A
    // paged table is commonly embedded in a long page; the pager must remain
    // visible immediately below the viewport instead of being part of the
    // scrollable table body.
    const shell = document.createElement("div");
    shell.className = "shared-paged-table";
    shell.append(view.shell, pagination);
    return {
      ...view,
      shell,
      tableShell: view.shell,
      pagination,
      page,
      pageSize,
      total,
      totalPages,
      start,
    };
  }

  function appendRow(body, values) {
    const row = body.insertRow();
    values.forEach(value => {
      const cell = row.insertCell();
      if (value instanceof Node) cell.append(value); else cell.textContent = text(value);
    });
    return row;
  }

  function empty(title, description) {
    const root = document.createElement("div"); root.className = "empty";
    const heading = document.createElement("h2"); heading.textContent = title;
    const copy = document.createElement("p"); copy.textContent = description;
    root.append(heading, copy); return root;
  }

  function loading(label) {
    const root = document.createElement("div"); root.className = "empty";
    const copy = document.createElement("p"); copy.textContent = label; root.append(copy);
    return root;
  }

  function fieldRows(value) {
    return Object.entries(value || {}).filter(([, item]) => (
      item == null || ["string", "number", "boolean"].includes(typeof item)
    ));
  }

  function code(value, options = {}) {
    const source = typeof value === "string"
      ? value : JSON.stringify(value, null, 2);
    const language = String(
      options.language || (typeof value === "string" ? "" : "json"),
    ).trim().toLowerCase();
    const pre = document.createElement("pre");
    pre.className = ["json-code", "code-viewer", options.className || ""]
      .filter(Boolean).join(" ");
    if (language) pre.dataset.language = language;
    const body = document.createElement("code");
    body.textContent = source;
    if (language) body.className = `language-${language}`;
    pre.append(body);
    if (
      language && window.hljs?.getLanguage?.(language)
      && typeof window.hljs.highlightElement === "function"
    ) {
      window.hljs.highlightElement(body);
    }
    return pre;
  }

  function formatDate(value) {
    if (!value) return "";
    const numeric = Number(value);
    const date = Number.isFinite(numeric)
      ? new Date(numeric < 10 ** 12 ? numeric * 1000 : numeric)
      : new Date(value);
    return Number.isNaN(date.valueOf()) ? text(value) : date.toLocaleString();
  }

  function actionButton(label, action, options = {}) {
    const button = document.createElement("button");
    const variant = options.variant === "primary" ? "primary" : "secondary";
    button.type = "button";
    button.className = `action-button ${variant}`;
    button.textContent = text(label);
    button.title = text(options.help || label);
    if (typeof action === "function") button.addEventListener("click", action);
    return button;
  }

  function helpIcon(help, options = {}) {
    if (window.FTHelp?.create) return window.FTHelp.create(help, options);
    const label = help && typeof help === "object"
      ? text(help.text || help.description || help.desc || help.body).trim()
      : text(help).trim();
    const icon = document.createElement("button");
    icon.type = "button";
    icon.className = "ft-help-icon";
    icon.textContent = "?";
    icon.setAttribute("aria-label", options.ariaLabel || label);
    return icon;
  }

  window.FTUI = {
    actionButton, appendRow, code, empty, fieldRows, formatDate, helpIcon, loading,
    pagedTable, table, text,
  };
})();
