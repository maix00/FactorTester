(() => {
  function text(value) {
    return value == null ? "" : String(value);
  }

  function table(headers, rows) {
    return FTUI.table(headers, rows);
  }

  function collapsible(title, content, open = false) {
    const details = document.createElement("details");
    details.className = "result-section";
    details.open = open;
    const summary = document.createElement("summary");
    summary.textContent = title;
    details.append(summary, content);
    return details;
  }

  function formatBytes(value) {
    if (value < 1024) return `${value} B`;
    if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KiB`;
    return `${(value / 1024 ** 2).toFixed(1)} MiB`;
  }

  async function saveBlob(context, path, fileName) {
    const response = await context.raw(path);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = fileName;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function artifactRows(context, artifacts, onOpen) {
    const result = table([context.t("中文说明"), context.t("原文件名"), context.t("文件大小")], []);
    artifacts.filter(item => item.state === "active").forEach(item => {
      const row = result.body.insertRow();
      const description = row.insertCell();
      description.textContent = item.description || item.name;
      const file = row.insertCell();
      const link = document.createElement("a");
      link.href = "#";
      link.textContent = item.file_name || item.name;
      link.addEventListener("click", event => {
        event.preventDefault();
        onOpen(item);
      });
      file.append(link);
      const size = row.insertCell();
      size.textContent = formatBytes(item.size_bytes || 0);
    });
    return result.shell;
  }

  async function clearArtifacts(context, portQuery, jobID) {
    await context.api(`/api/jobs/${encodeURIComponent(jobID)}/artifacts${portQuery}`, {method: "DELETE"});
    const port = Number(new URLSearchParams(portQuery.slice(1)).get("port") || 0);
    return window.FTJobs.detail(context, port, jobID);
  }

  async function downloadAllArtifacts(context, artifacts, jobID, portQuery) {
    let directory = null;
    if (window.showDirectoryPicker) {
      directory = await window.showDirectoryPicker({mode: "readwrite"});
    }
    for (const artifact of artifacts) {
      const fileName = artifact.file_name || artifact.name;
      const path = `/api/jobs/${encodeURIComponent(jobID)}/artifacts/${encodeURIComponent(artifact.name)}${portQuery}`;
      if (!directory) {
        await saveBlob(context, path, fileName);
        continue;
      }
      const response = await context.raw(path);
      const handle = await directory.getFileHandle(fileName, {create: true});
      const writable = await handle.createWritable();
      await writable.write(await response.blob());
      await writable.close();
    }
  }

  function declarationArtifact(declaration, artifacts) {
    const names = declaration.artifacts || [];
    return artifacts.find(item => names.includes(item.name)) || artifacts.find(item => {
      const viewer = String(declaration.viewer || "").toLowerCase();
      const type = String(item.content_type || "").toLowerCase();
      return viewer.includes("image") ? type.startsWith("image/")
        : viewer.includes("table") || viewer.includes("order") ? type.includes("csv") || type.includes("json")
        : viewer.includes("price") || viewer.includes("kline") ? type.includes("json") : false;
    });
  }

  function effectiveDeclarations(declarations, artifacts, context) {
    const result = [...declarations];
    const declared = new Set(result.flatMap(item => item.artifacts || []));
    artifacts.filter(item => item.state === "active").forEach(item => {
      const type = artifactContentType(item);
      if (!isImageArtifact(item, type) || declared.has(item.name)) return;
      const name = String(item.name || item.file_name || "").toLowerCase();
      const label = name.includes("equity_curve")
        ? context.t("净值曲线") : name.includes("ic_series")
          ? context.t("IC 序列图") : item.description || item.name;
      result.push({
        id: `implicit:${item.name}`,
        name: item.name,
        label,
        presentation: "chart",
        viewer: "image",
        formats: [String(item.file_name || "").split(".").pop() || ""],
        artifacts: [item.name],
      });
    });
    return result;
  }

  function artifactContentType(item) {
    return String(item.content_type || item.media_type || "").toLowerCase();
  }

  function isImageArtifact(item, type = artifactContentType(item)) {
    const filename = String(item.file_name || item.name || "").toLowerCase();
    return type.startsWith("image/") || /\.(png|jpe?g|gif|webp|svg)$/.test(filename);
  }

  function lazyArtifactPreview(context, declaration, artifact, jobID, portQuery) {
    const target = document.createElement("div");
    target.className = "artifact-preview";
    const details = collapsible(declaration.label || declaration.name, target);
    let loaded = false;
    details.addEventListener("toggle", async () => {
      if (!details.open || loaded) return;
      loaded = true;
      try {
        await FTJobArtifactViewers.mount(context, target, {declaration, artifact, jobID, portQuery});
      } catch (error) {
        target.textContent = error.message;
      }
    });
    return details;
  }

  window.FTJobArtifacts = {
    artifactRows,
    clearArtifacts,
    collapsible,
    declarationArtifact,
    downloadAllArtifacts,
    effectiveDeclarations,
    lazyArtifactPreview,
    saveBlob,
  };
})();
