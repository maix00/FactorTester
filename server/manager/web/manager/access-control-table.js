(() => {
  // Search is local; pagination and row rendering belong to the shared table.
  function create(context, options) {
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
    search.setAttribute("aria-label", search.placeholder);
    search.addEventListener("input", () => {
      query = search.value.trim().toLocaleLowerCase();
      page = 1;
      render();
    });
    toolbar.append(search);
    if (options.refresh) toolbar.append(FTUI.refreshButton(context, options.refresh));
    const content = document.createElement("div");
    root.append(toolbar, content);
    function render() {
      const visible = query ? rows.filter(item => String(options.searchText(item) || "")
        .toLocaleLowerCase().includes(query)) : rows;
      const view = FTUI.pagedTable(options.headers.map(item => context.t(item)), visible, {
        page, pageSize: 10,
        onPageChange(value) { page = value; render(); },
        renderRow: item => options.cells(item).map(value => (
          typeof value === "function" ? value(context, item) : value
        )),
        totalLabel: total => `${total} ${context.t("项")}`,
      });
      page = view.page;
      view.tableShell.classList.add("manager-access-table-shell");
      // Reuse the shared pager's handlers and disabled state, with icon labels.
      const buttons = view.pagination.querySelectorAll("button");
      [["chevron.left", "上一页"], ["chevron.right", "下一页"]].forEach(([icon, label], index) => {
        const button = buttons[index];
        button.className = "icon-action-button";
        button.title = context.t(label);
        button.setAttribute("aria-label", button.title);
        button.replaceChildren(FTIcons.node(icon));
      });
      if (!visible.length) {
        const row = view.body.insertRow();
        const cell = row.insertCell();
        cell.colSpan = options.headers.length;
        cell.textContent = context.t(options.empty || "暂无数据");
      }
      content.replaceChildren(view.shell);
    }
    return {root, setRows(value) {
      rows = Array.isArray(value) ? value : [];
      render(); // Retain search/page after a mutation; pagedTable clamps the page.
    }};
  }
  window.FTManagerAccessTable = Object.freeze({create});
})();
