(() => {
  const DEFAULT_PAGE_SIZE = 20;

  // Report/job tables now reuse the shared pageable table primitive
  // (``FTUI.pagedTable``) instead of a bespoke scroll+chunk renderer.  The
  // rich hooks are preserved: ``renderHeader``/``renderCell`` may return any
  // node (links, inline math, inline code, header buttons), and the table
  // still exposes its own scroll boundary via ``.table-shell``.
  function render({
    columns,
    rows,
    context = {},
    renderHeader,
    renderCell,
    values,
    className = "table-shell",
    pageSize = DEFAULT_PAGE_SIZE,
  }) {
    const headers = columns.map(column => renderHeader(column));
    const rowValues = rows.map(row => values(row));
    const size = Math.max(1, Number(pageSize) || DEFAULT_PAGE_SIZE);
    const t = key => (typeof context.t === "function" ? context.t(key) : key);
    let page = 1;

    const shell = document.createElement("div");
    shell.className = "report-paged-table";

    const draw = () => {
      const view = window.FTUI.pagedTable(headers, rowValues, {
        page,
        pageSize: size,
        previousLabel: t("上一页"),
        nextLabel: t("下一页"),
        renderRow: (cells, indexInPage) => {
          const rowIndex = (page - 1) * size + indexInPage;
          return cells.map((item, columnIndex) => renderCell(
            item,
            rows[rowIndex],
            columns[columnIndex],
            rowIndex,
          ));
        },
        onPageChange: next => {
          page = next;
          draw();
        },
      });
      view.tableShell.className = className;
      if (view.tableShell.dataset) {
        view.tableShell.dataset.ftScrollState = `report-table:${className}`;
      }
      // A single page does not need a pager; keep the table's own scroll box.
      view.pagination.hidden = view.totalPages <= 1;
      shell.replaceChildren(view.shell);
    };
    draw();
    return shell;
  }

  window.FTReportTables = Object.freeze({render});
})();
