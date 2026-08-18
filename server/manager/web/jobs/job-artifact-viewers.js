(() => {
  function artifactPath(jobID, artifact, artifactQuery) {
    return `/api/jobs/${encodeURIComponent(jobID)}/artifacts/${encodeURIComponent(artifact.name)}${artifactQuery}`;
  }

  async function mount(context, target, options) {
    target.replaceChildren(message(context.t("正在读取生成物…")));
    const response = await FTJobArtifacts.fetch(
      context,
      artifactPath(
        options.jobID,
        options.artifact,
        options.artifactQuery || "",
      ),
    );
    const type = String(options.artifact.content_type || options.artifact.media_type
      || response.headers.get("Content-Type") || "").toLowerCase();
    const filename = String(options.artifact.file_name || options.artifact.name || "").toLowerCase();
    const viewer = String(options.declaration?.viewer || "").toLowerCase();
    if (type.startsWith("image/") || /\.(png|jpe?g|gif|webp|svg)$/.test(filename)) {
      return image(context, target, await response.blob(), type || "image/*");
    }
    const body = await response.text();
    if (viewer.includes("price") || viewer.includes("kline") || viewer.includes("ohlcv")) {
      return priceChart(context, target, body);
    }
    if (type.includes("json") && window.FTJobHighcharts) {
      const value = JSON.parse(body);
      if (FTJobHighcharts.supports(options.declaration)) {
        return FTJobHighcharts.mount(context, target, value, viewer);
      }
    }
    if (type.includes("csv")) return dataTable(context, target, tableModel(parseCSV(body)));
    if (type.includes("json") || viewer.includes("table") || viewer.includes("order")) {
      const value = JSON.parse(body);
      const model = tableModel(value);
      if (model.rows.length) return dataTable(context, target, model);
      const pre = document.createElement("pre"); pre.className = "json-code"; pre.textContent = JSON.stringify(value, null, 2);
      return target.replaceChildren(pre);
    }
    const pre = document.createElement("pre"); pre.className = "json-code"; pre.textContent = body;
    target.replaceChildren(pre);
  }

  function message(value) {
    const element = document.createElement("p"); element.className = "artifact-message";
    element.textContent = value; return element;
  }

  function image(context, target, blob, type) {
    const url = URL.createObjectURL(blob);
    const element = document.createElement("img"); element.className = "artifact-image";
    element.alt = ""; element.src = url; element.dataset.contentType = type || "";
    element.onerror = () => {
      target.replaceChildren(message(context.t("无法读取")));
      URL.revokeObjectURL(url);
    };
    element.onload = () => URL.revokeObjectURL(url);
    target.replaceChildren(element);
  }

  function parseCSV(source) {
    const output = []; let row = []; let field = ""; let quoted = false;
    for (let index = 0; index < source.length; index += 1) {
      const char = source[index];
      if (char === '"' && quoted && source[index + 1] === '"') { field += '"'; index += 1; }
      else if (char === '"') quoted = !quoted;
      else if (char === "," && !quoted) { row.push(field); field = ""; }
      else if ((char === "\n" || char === "\r") && !quoted) {
        if (char === "\r" && source[index + 1] === "\n") index += 1;
        row.push(field); if (row.some(value => value !== "")) output.push(row);
        row = []; field = "";
      } else field += char;
    }
    row.push(field); if (row.some(value => value !== "")) output.push(row);
    if (!output.length) return [];
    const headers = output[0].map((value, index) => value || `column_${index + 1}`);
    return output.slice(1).map(values => Object.fromEntries(headers.map((key, index) => [key, values[index] || ""])));
  }

  function objectRows(value) {
    return Array.isArray(value)
      && value.length > 0
      && value.every(item => item && typeof item === "object" && !Array.isArray(item));
  }

  function tableModel(value) {
    if (objectRows(value)) {
      return {columns: columnsFor(value), rows: value, presentations: {}};
    }
    if (!value || typeof value !== "object") {
      return {columns: [], rows: [], presentations: {}};
    }
    const declaredColumns = Array.isArray(value.columns)
      ? value.columns.map(String) : [];
    const presentations = value.column_presentations
      && typeof value.column_presentations === "object"
      ? value.column_presentations : {};
    if (objectRows(value.rows)) {
      return {
        columns: columnsFor(value.rows, declaredColumns),
        rows: value.rows,
        presentations,
      };
    }
    if (declaredColumns.length && Array.isArray(value.rows)
        && value.rows.every(row => Array.isArray(row))) {
      return {
        columns: declaredColumns,
        rows: value.rows.map(row => Object.fromEntries(
          declaredColumns.map((column, index) => [column, row[index]]),
        )),
        presentations,
      };
    }
    for (const item of Object.values(value)) {
      const model = tableModel(item);
      if (model.rows.length) return model;
    }
    return {columns: [], rows: [], presentations: {}};
  }

  function columnsFor(rows, preferred = []) {
    const discovered = [...new Set(rows.slice(0, 500).flatMap(row => Object.keys(row)))];
    // An explicit server column list is the display contract. Fields such as
    // factor_ref may remain in each row solely to resolve a visible alias and
    // must not leak into the table as an extra technical column.
    return preferred.length ? [...new Set(preferred)] : discovered;
  }

  function renderedCell(context, value, row, key, presentations) {
    if (value && typeof value === "object") {
      const pre = document.createElement("pre");
      pre.className = "json-code";
      pre.textContent = JSON.stringify(value, null, 2);
      return pre;
    }
    const presentation = presentations[key];
    if (presentation?.presentation === "reference") {
      const target = row[presentation.target_ref_field];
      const url = FTJobListFormat.referenceURL(presentation.kind, target);
      if (url) return FTRichText.inline(`[${String(value ?? target)}](${url})`, context);
    }
    return FTRichText.inline(String(value ?? ""), context);
  }

  function dataTable(context, target, model) {
    const {columns: headers, rows, presentations} = model;
    if (!rows.length) return target.replaceChildren(message(context.t("生成物不是可识别的表格数据")));
    // Reuse the report table primitive so result previews get the same
    // bounded idle-chunk rendering as report tables.  Creating hundreds of
    // rich-text cells synchronously here used to block the job detail page;
    // the shared primitive mounts only the first chunk and schedules the rest
    // while keeping the table's own horizontal scroll boundary.
    const result = FTReportTables.render({
      columns: headers,
      rows: rows.slice(0, 500),
      context,
      className: "artifact-table-shell",
      renderHeader: key => FTRichText.inline(String(key), context),
      renderCell: (value, row, key) => renderedCell(
        context, value, row, key, presentations,
      ),
      values: item => headers.map(key => item[key]),
    });
    target.replaceChildren(result);
    if (rows.length > 500) target.append(message(`${context.t("显示前 500 行")} · ${rows.length}`));
  }

  function priceChart(context, target, source) {
    const value = JSON.parse(source);
    if (!window.FTPriceChart?.render) {
      return target.replaceChildren(message(context.t("交互式行情图组件未加载")));
    }
    const payload = Array.isArray(value)
      ? value : {...value, data: tableModel(value).rows};
    return FTPriceChart.render(context, target, payload);
  }

  window.FTJobArtifactViewers = {
    mount, priceChart, tableModel,
    referenceURL: FTJobListFormat.referenceURL,
  };
})();
