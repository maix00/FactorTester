(() => {
  function artifactPath(jobID, artifact, portQuery) {
    return `/api/jobs/${encodeURIComponent(jobID)}/artifacts/${encodeURIComponent(artifact.name)}${portQuery}`;
  }

  async function mount(context, target, options) {
    target.replaceChildren(message(context.t("正在读取生成物…")));
    const response = await context.raw(artifactPath(options.jobID, options.artifact, options.portQuery));
    const type = String(options.artifact.content_type || response.headers.get("Content-Type") || "").toLowerCase();
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
    // Keep artifact tables on the same table primitive as job fields and
    // report tables.  Each preview gets its own shell so a wide result cannot
    // change the width of the artifact list below it.
    const result = FTUI.table(headers, []);
    result.shell.classList.add("artifact-table-shell");
    rows.slice(0, 500).forEach(item => {
      const row = result.body.insertRow(); headers.forEach(key => {
        const cell = row.insertCell();
        const value = item[key];
        if (value && typeof value === "object") {
          const pre = document.createElement("pre");
          pre.className = "json-code";
          pre.textContent = JSON.stringify(value, null, 2);
          cell.append(pre);
        } else {
          cell.append(FTRichText.inline(String(value ?? ""), context));
        }
      });
    });
    target.replaceChildren(result.shell);
    if (rows.length > 500) target.append(message(`${context.t("显示前 500 行")} · ${rows.length}`));
  }

  function priceChart(context, target, source) {
    const rows = findRows(JSON.parse(source)).map(normalizeBar).filter(Boolean);
    if (!rows.length) return target.replaceChildren(message(context.t("未找到可绘制的 OHLCV 数据")));
    const canvas = document.createElement("canvas"); canvas.className = "artifact-price-chart";
    canvas.width = 1200; canvas.height = 520; target.replaceChildren(canvas);
    drawBars(canvas, sample(rows, 800));
  }

  function normalizeBar(row) {
    const normalized = Object.fromEntries(Object.entries(row).map(([key, value]) => [key.toLowerCase(), value]));
    const number = key => Number(normalized[key]);
    const bar = {open: number("open"), high: number("high"), low: number("low"), close: number("close"), volume: number("volume") || 0};
    return Object.values(bar).every(Number.isFinite) ? bar : null;
  }

  function sample(rows, maximum) {
    if (rows.length <= maximum) return rows;
    const step = rows.length / maximum;
    return Array.from({length: maximum}, (_, index) => rows[Math.floor(index * step)]);
  }

  function drawBars(canvas, rows) {
    const context = canvas.getContext("2d"); const width = canvas.width; const height = canvas.height;
    context.clearRect(0, 0, width, height); context.fillStyle = "#fff"; context.fillRect(0, 0, width, height);
    const high = Math.max(...rows.map(item => item.high)); const low = Math.min(...rows.map(item => item.low));
    const maxVolume = Math.max(1, ...rows.map(item => item.volume)); const priceHeight = height * .76;
    const y = value => 18 + (high - value) / Math.max(high - low, Number.EPSILON) * (priceHeight - 36);
    const slot = width / rows.length;
    rows.forEach((bar, index) => {
      const x = (index + .5) * slot; const up = bar.close >= bar.open;
      context.strokeStyle = up ? "#18a572" : "#e14d5b"; context.fillStyle = context.strokeStyle;
      context.beginPath(); context.moveTo(x, y(bar.high)); context.lineTo(x, y(bar.low)); context.stroke();
      const top = Math.min(y(bar.open), y(bar.close)); const candleHeight = Math.max(1, Math.abs(y(bar.open) - y(bar.close)));
      context.fillRect(x - Math.max(1, slot * .3), top, Math.max(1, slot * .6), candleHeight);
      const volumeHeight = bar.volume / maxVolume * (height - priceHeight - 18);
      context.globalAlpha = .45; context.fillRect(x - Math.max(1, slot * .3), height - volumeHeight, Math.max(1, slot * .6), volumeHeight); context.globalAlpha = 1;
    });
  }

  window.FTJobArtifactViewers = {mount, priceChart};
})();
