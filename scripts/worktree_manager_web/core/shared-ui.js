(() => {
  const text = value => value == null ? "" : String(value);

  function table(headers, rows = []) {
    const shell = document.createElement("div"); shell.className = "table-shell";
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

  function code(value) {
    const pre = document.createElement("pre");
    pre.className = "json-code";
    pre.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
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

  window.FTUI = {appendRow, code, empty, fieldRows, formatDate, loading, table, text};
})();
