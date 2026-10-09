(() => {
  const deferred = () => {
    let resolve;
    let reject;
    const promise = new Promise((resolvePromise, rejectPromise) => {
      resolve = resolvePromise;
      reject = rejectPromise;
    });
    return {promise, resolve, reject};
  };

  const element = (tag = "div") => document.createElement(tag);
  window.FTUI = {
    loading: label => Object.assign(element(), {textContent: label}),
    empty: (title, body = "") => Object.assign(element(), {
      textContent: `${title} ${body}`,
    }),
    actionButton: (label, action) => {
      const button = element("button");
      button.textContent = label;
      button.addEventListener("click", action);
      return button;
    },
    refreshButton: (_context, action) => {
      const button = element("button");
      button.addEventListener("click", action);
      return button;
    },
    table: (headers, rows = []) => {
      const shell = element("table");
      const head = element("thead");
      const headerRow = element("tr");
      const body = element("tbody");
      headers.forEach(label => {
        const cell = element("th");
        cell.textContent = label;
        headerRow.append(cell);
      });
      head.append(headerRow);
      shell.append(head, body);
      rows.forEach(values => window.FTUI.appendRow(body, values));
      return {shell, body};
    },
    appendRow: (body, values) => {
      const row = element("tr");
      values.forEach(value => {
        const cell = element("td");
        if (value instanceof Node) cell.append(value);
        else cell.textContent = String(value ?? "");
        row.append(cell);
      });
      body.append(row);
    },
    userLabel: () => "owner",
    userDisplay: (_owner, alias) => alias || "owner",
  };

  window.context = {
    activeNav() {},
    setHeading() {},
    t: value => value,
    session: null,
    toolbar: document.querySelector("header"),
    content: document.querySelector("main"),
    navigate() {},
    showNotice() {},
    isRouteCurrent: () => true,
  };

  window.newProductCategoriesRequests = () => ({
    categories: deferred(),
    sources: deferred(),
  });

  window.productCategoriesHelpers = requests => ({
    sourceOf: () => "server",
    catalogSwitch() {},
    sourceSummary: () => element(),
    isCurrent: () => true,
    pathFor: path => path,
    sourceFamilyPath: id => `/products/sources/${encodeURIComponent(id)}`,
    loadCategories: () => requests.categories.promise,
    loadSources: () => requests.sources.promise,
  });
})();
