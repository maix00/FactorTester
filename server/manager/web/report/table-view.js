(() => {
  const CHUNK_SIZE = 80;

  function schedule(context, callback) {
    if (typeof requestIdleCallback === "function") {
      requestIdleCallback(callback, {timeout: 80});
    } else {
      setTimeout(callback, 0);
    }
  }

  function render({columns, rows, context, renderHeader, renderCell, values, className = "table-shell"}) {
    const shell = document.createElement("div");
    shell.className = className;
    if (shell.dataset) shell.dataset.ftScrollState = `report-table:${className}`;
    const element = document.createElement("table");
    const head = element.createTHead().insertRow();
    columns.forEach(column => {
      const cell = document.createElement("th");
      cell.append(renderHeader(column));
      head.append(cell);
    });
    const body = element.createTBody();
    const renderGeneration = Number(context?.renderGeneration || 0);
    const isCurrent = () => !context?.lazyDisposed
      && Number(context?.renderGeneration || 0) === renderGeneration;
    let cursor = 0;
    const appendChunk = () => {
      if (!isCurrent()) return;
      const end = Math.min(rows.length, cursor + CHUNK_SIZE);
      for (; cursor < end; cursor += 1) {
        const row = body.insertRow();
        const sourceRow = rows[cursor];
        values(sourceRow).forEach((item, columnIndex) => {
          const cell = row.insertCell();
          cell.append(renderCell(item, sourceRow, columns[columnIndex], cursor));
        });
      }
      if (cursor < rows.length) schedule(context, appendChunk);
    };
    if (rows.length > CHUNK_SIZE && context?.tableRenderSync !== true) appendChunk();
    else {
      while (cursor < rows.length) appendChunk();
    }
    shell.append(element);
    return shell;
  }

  window.FTReportTables = Object.freeze({render});
})();
