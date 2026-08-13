(() => {
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

  function accessPath(path) {
    const url = new URL(path, window.location.origin);
    url.pathname = url.pathname.replace(/\/preview$/, "") + "/access";
    return url.pathname + url.search;
  }

  async function fetchArtifact(context, path, options = {}) {
    const issued = await context.api(accessPath(path), {method: "POST"});
    const access = issued?.access || {};
    if (!access.url || !access.bearer) {
      throw new Error(context.t("生成物传输授权无效"));
    }
    const headers = new Headers(options.headers || {});
    headers.set("Authorization", `Bearer ${access.bearer}`);
    const response = await fetch(access.url, {...options, headers});
    if (!response.ok) {
      const value = await response.json().catch(() => ({}));
      const error = value?.error;
      throw Object.assign(new Error(
        typeof error === "object" ? error.message : error
          || `${context.t("读取生成物失败")} (HTTP ${response.status})`,
      ), {status: response.status});
    }
    return response;
  }

  async function saveBlob(context, path, fileName) {
    const response = await fetchArtifact(context, path);
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
    const result = FTUI.table([context.t("中文说明"), context.t("原文件名"), context.t("文件大小")], []);
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
    const params = new URLSearchParams(portQuery.slice(1));
    const port = Number(params.get("port") || 0);
    return window.FTJobs.detail(context, port, jobID, params.get("server_id") || "");
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
      const response = await fetchArtifact(context, path);
      const relative = artifactDownloadParts(artifact);
      let target = directory;
      for (const part of relative.slice(0, -1)) {
        target = await target.getDirectoryHandle(part, {create: true});
      }
      const handle = await target.getFileHandle(relative.at(-1), {create: true});
      const writable = await handle.createWritable();
      await writable.write(await response.blob());
      await writable.close();
    }
  }

  function artifactDownloadParts(artifact) {
    const fileName = safePathParts(artifact.file_name || artifact.name).at(-1)
      || "artifact";
    if (String(artifact.role || "output") !== "input") return [fileName];
    const kind = String(artifact.artifact_kind || "input")
      .replace(/[^A-Za-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "") || "input";
    const logical = safePathParts(artifact.logical_path);
    return ["inputs", kind, ...(logical.length ? logical : [fileName])];
  }

  function safePathParts(value) {
    const raw = String(value || "").replaceAll("\\", "/");
    if (!raw || raw.startsWith("/") || raw.includes("\0")) return [];
    const parts = raw.split("/").filter(part => part && part !== ".");
    return parts.includes("..") ? [] : parts;
  }

  function declarationArtifact(declaration, artifacts) {
    const names = declaration.artifacts || [];
    const named = names.map(name => artifacts.find(item => item.name === name)).filter(Boolean);
    const viewer = String(declaration.viewer || "").toLowerCase();
    const interactiveChart = declaration.presentation === "chart"
      && window.FTJobHighcharts?.supports(declaration);
    if (interactiveChart) {
      const dataName = `${String(declaration.name || declaration.id)}_data`;
      const data = named.find(item => item.name === dataName
        && artifactContentType(item).includes("json"));
      if (data) return data;
    }
    const reportImage = declaration.presentation === "chart"
      ? named.find(item => isImageArtifact(item)) : null;
    return reportImage || named[0]
      || artifacts.find(item => {
        const type = String(item.content_type || "").toLowerCase();
        if (viewer.includes("image")) return type.startsWith("image/");
        if (viewer.includes("table") || viewer.includes("order")) {
          return type.includes("csv") || type.includes("json");
        }
        if (viewer.includes("price") || viewer.includes("kline")) {
          return type.includes("json");
        }
        return false;
      });
  }

  function declarationArtifacts(declaration, artifacts) {
    const primary = declarationArtifact(declaration, artifacts);
    if (!primary) return [];
    const names = new Set(declaration.artifacts || []);
    const fallback = declaration.presentation === "chart"
      ? artifacts.find(item => item !== primary && names.has(item.name)
        && isImageArtifact(item)) : null;
    return fallback ? [primary, fallback] : [primary];
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

  function lazyArtifactPreview(context, declaration, artifacts, jobID, portQuery) {
    const target = document.createElement("div");
    target.className = "artifact-preview";
    const details = collapsible(declaration.label || declaration.name, target);
    let loaded = false;
    details.addEventListener("toggle", async () => {
      if (!details.open || loaded) return;
      loaded = true;
      try {
        for (let index = 0; index < artifacts.length; index += 1) {
          try {
            await FTJobArtifactViewers.mount(context, target, {
              declaration, artifact: artifacts[index], jobID, portQuery,
            });
            return;
          } catch (error) {
            const canFallback = index + 1 < artifacts.length
              && [404, 410].includes(Number(error.status));
            if (!canFallback) throw error;
          }
        }
      } catch (error) {
        target.textContent = error.message;
      }
    });
    return details;
  }

  window.FTJobArtifacts = {
    artifactRows,
    artifactDownloadParts,
    clearArtifacts,
    collapsible,
    declarationArtifact,
    declarationArtifacts,
    downloadAllArtifacts,
    effectiveDeclarations,
    fetch: fetchArtifact,
    lazyArtifactPreview,
    saveBlob,
  };
})();
