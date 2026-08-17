(() => {
  function create(context, options) {
    const pageSize = 10;
    let rows = [];
    let query = "";
    let page = 1;

    const root = document.createElement("div");
    root.className = "manager-access-table";
    const toolbar = document.createElement("div");
    toolbar.className = "manager-access-toolbar";
    const search = document.createElement("input");
    search.type = "search";
    search.className = "toolbar-search";
    search.placeholder = context.t(options.searchPlaceholder || "搜索…");
    search.addEventListener("input", () => {
      query = search.value.trim().toLocaleLowerCase();
      page = 1;
      render();
    });
    toolbar.append(search);

    const table = FTUI.table(options.headers.map(item => context.t(item)), []);
    table.shell.classList.add("manager-access-table-shell");
    const pagination = document.createElement("div");
    pagination.className = "manager-access-pagination";
    root.append(toolbar, table.shell, pagination);

    function filteredRows() {
      if (!query) return rows;
      return rows.filter(item => String(options.searchText(item) || "")
        .toLocaleLowerCase().includes(query));
    }

    function render() {
      const visible = filteredRows();
      const totalPages = Math.max(1, Math.ceil(visible.length / pageSize));
      page = Math.min(page, totalPages);
      const start = (page - 1) * pageSize;
      table.body.replaceChildren();
      visible.slice(start, start + pageSize).forEach(item => {
        FTUI.appendRow(
          table.body,
          options.cells(item).map(value => (
            typeof value === "function" ? value(context, item) : value
          )),
        );
      });
      if (!visible.length) {
        const row = table.body.insertRow();
        const cell = row.insertCell();
        cell.colSpan = options.headers.length;
        cell.textContent = context.t(options.empty || "暂无数据");
      }

      const previous = document.createElement("button");
      previous.className = "secondary";
      previous.textContent = context.t("上一页");
      previous.disabled = page <= 1;
      previous.onclick = () => { page -= 1; render(); };
      const next = document.createElement("button");
      next.className = "secondary";
      next.textContent = context.t("下一页");
      next.disabled = page >= totalPages;
      next.onclick = () => { page += 1; render(); };
      const label = document.createElement("span");
      label.className = "job-page-label";
      label.textContent = FTI18n.format("第 %lld 页", page);
      const count = document.createElement("span");
      count.className = "job-pagination-caption";
      count.textContent = `${visible.length} ${context.t("项")}`;
      pagination.replaceChildren(previous, next, label, count);
    }

    return {
      root,
      setRows(value) {
        rows = Array.isArray(value) ? value : [];
        page = 1;
        render();
      },
    };
  }

  window.FTManagerAccessTable = Object.freeze({create});
})();
