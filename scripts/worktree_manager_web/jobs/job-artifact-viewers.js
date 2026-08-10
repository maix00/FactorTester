(() => {
  function artifactPath(jobID, artifact, portQuery) {
    return `/api/jobs/${encodeURIComponent(jobID)}/artifacts/${encodeURIComponent(artifact.name)}/preview${portQuery}`;
  }

  async function mount(context, target, options) {
    target.replaceChildren(message(context.t("正在读取生成物…")));
    const response = await context.raw(artifactPath(options.jobID, options.artifact, options.portQuery));
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
    if (type.includes("csv")) return dataTable(context, target, parseCSV(body));
    if (type.includes("json") || viewer.includes("table") || viewer.includes("order")) {
      const value = JSON.parse(body);
      const rows = findRows(value);
      if (rows.length) return dataTable(context, target, rows);
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

  function findRows(value) {
    if (Array.isArray(value) && value.every(item => item && typeof item === "object" && !Array.isArray(item))) return value;
    if (!value || typeof value !== "object") return [];
    for (const item of Object.values(value)) {
      const rows = findRows(item); if (rows.length) return rows;
    }
    return [];
  }

  function dataTable(context, target, rows) {
    if (!rows.length) return target.replaceChildren(message(context.t("生成物不是可识别的表格数据")));
    const headers = [...new Set(rows.slice(0, 500).flatMap(row => Object.keys(row)))];
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
      renderCell: value => {
        if (value && typeof value === "object") {
          const pre = document.createElement("pre");
          pre.className = "json-code";
          pre.textContent = JSON.stringify(value, null, 2);
          return pre;
        }
        return FTRichText.inline(String(value ?? ""), context);
      },
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
      ? value : {...value, data: findRows(value)};
    return FTPriceChart.render(context, target, payload);
  }

  window.FTJobArtifactViewers = {mount, priceChart};
})();
