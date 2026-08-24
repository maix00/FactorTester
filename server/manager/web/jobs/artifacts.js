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
    url.pathname = url.pathname.replace(/\/$/, "") + "/access";
    return url.pathname + url.search;
  }

  const artifactRetryDelays = [250, 750];

  function artifactRequestKey(path) {
    const random = window.crypto?.randomUUID?.()
      || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    return `artifact-read:${String(path)}:${random}`;
  }

  function retryableArtifactError(error, signal) {
    if (signal?.aborted) return false;
    if ([502, 503, 504].includes(Number(error?.status))) return true;
    return error?.name === "TypeError" || error?.name === "NetworkError";
  }

  function waitForArtifactRetry(attempt) {
    return new Promise(resolve => setTimeout(
      resolve, artifactRetryDelays[attempt] || artifactRetryDelays.at(-1),
    ));
  }

  async function fetchArtifactOnce(context, path, options, idempotencyKey) {
    const issued = await context.api(accessPath(path), {
      method: "POST",
      headers: {"Idempotency-Key": idempotencyKey},
    });
    const access = issued?.access || {};
    if (!access.url || !access.bearer) {
      throw new Error(context.t("生成物传输授权无效"));
    }
    const headers = new Headers(options.headers || {});
    headers.set("Authorization", `Bearer ${access.bearer}`);
    const response = await fetch(access.url, {
      ...options,
      credentials: "omit",
      redirect: "error",
      headers,
    });
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

  async function fetchArtifact(context, path, options = {}) {
    const idempotencyKey = artifactRequestKey(path);
    for (let attempt = 0; ; attempt += 1) {
      try {
        return await fetchArtifactOnce(
          context, path, options, idempotencyKey,
        );
      } catch (error) {
        if (attempt >= artifactRetryDelays.length
            || !retryableArtifactError(error, options.signal)) {
          throw error;
        }
        await waitForArtifactRetry(attempt);
      }
    }
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

  function artifactRows(context, artifacts, onOpen, options = {}) {
    const canUpload = typeof options.onUpload === "function"
      && artifacts.some(item => item.state === "local_only");
    const canDelete = typeof options.onDelete === "function"
      && artifacts.some(item => item.state === "active");
    const headers = [context.t("中文说明"), context.t("原文件名"), context.t("文件大小")];
    if (canUpload || canDelete) headers.push(context.t("操作"));
    const result = FTUI.table(headers, []);
    artifacts.filter(item => item.state === "active"
      || (options.includeLocalOnly && item.state === "local_only")).forEach(item => {
      const row = result.body.insertRow();
      const description = row.insertCell();
      description.textContent = item.description || item.name;
      const file = row.insertCell();
      if (item.state === "active" && typeof onOpen === "function") {
        const link = document.createElement("a");
        link.href = "#";
        link.textContent = item.file_name || item.name;
        link.addEventListener("click", async event => {
          event.preventDefault();
          try {
            await onOpen(item);
          } catch (error) {
            context.showNotice?.(
              error?.message || String(error), true,
            );
          }
        });
        file.append(link);
      } else {
        file.textContent = item.file_name || item.name;
      }
      const size = row.insertCell();
      size.textContent = formatBytes(item.size_bytes || 0);
      if (canUpload || canDelete) {
        const action = row.insertCell();
        if (item.state === "local_only") {
          const upload = document.createElement("button");
          upload.type = "button";
          upload.className = "secondary-button";
          upload.textContent = context.t("上传到服务器");
          upload.addEventListener("click", async event => {
            event.stopPropagation();
            upload.disabled = true;
            try {
              await options.onUpload(item);
              upload.textContent = context.t("已提交上传");
            } catch (error) {
              upload.disabled = false;
              context.showNotice?.(error.message || String(error), true);
            }
          });
          action.append(upload);
        } else {
          if (canDelete) {
            const remove = document.createElement("button");
            remove.type = "button";
            remove.className = "secondary-button danger-button";
            remove.textContent = context.t("删除");
            remove.addEventListener("click", async event => {
              event.stopPropagation();
              remove.disabled = true;
              try {
                await options.onDelete(item);
              } catch (error) {
                remove.disabled = false;
                context.showNotice?.(error.message || String(error), true);
              }
            });
            action.append(remove);
          } else {
            action.textContent = context.t("已上传");
          }
        }
      }
    });
    return result.shell;
  }

  async function clearArtifacts(context, artifactQuery, jobID) {
   await context.api(`/api/jobs/${encodeURIComponent(jobID)}/artifacts${artifactQuery}`, {method: "DELETE"});
    const params = new URLSearchParams(artifactQuery.slice(1));
    return window.FTJobs.detail(
      context, 0, jobID, params.get("server_id") || "",
    );
  }

  async function deleteArtifact(context, artifactQuery, jobID, name) {
    return context.api(
      `/api/jobs/${encodeURIComponent(jobID)}/artifacts/${encodeURIComponent(name)}${artifactQuery}`,
      {method: "DELETE"},
    );
  }

  async function downloadAllArtifacts(context, artifacts, jobID, artifactQuery) {
    let directory = null;
    if (window.showDirectoryPicker) {
      directory = await window.showDirectoryPicker({mode: "readwrite"});
    }
    for (const artifact of artifacts) {
      const fileName = artifact.file_name || artifact.name;
      const path = `/api/jobs/${encodeURIComponent(jobID)}/artifacts/${encodeURIComponent(artifact.name)}${artifactQuery}`;
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
    const named = names.map(name => artifactReference(artifacts, name)).filter(Boolean);
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
      ? artifacts.find(item => item !== primary && [...names].some(name => (
        artifactReference([item], name)
      ))
        && isImageArtifact(item)) : null;
    return fallback ? [primary, fallback] : [primary];
  }

  function artifactReference(artifacts, reference) {
    const target = String(reference || "");
    return (artifacts || []).find(item => (
      String(item?.name || "") === target
      || String(item?.file_name || "") === target
    )) || null;
  }

  function effectiveDeclarations(declarations, artifacts, context) {
    const result = [...declarations];
    const declared = new Set(result.flatMap(item => item.artifacts || []).map(reference => (
      artifactReference(artifacts, reference)?.name || reference
    )));
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

  function lazyArtifactPreview(context, declaration, artifacts, jobID, artifactQuery) {
    const target = document.createElement("div");
    target.className = "artifact-preview";
    const details = collapsible(declaration.label || declaration.name, target);
    let loaded = false;
    let loading = false;
    details.addEventListener("toggle", async () => {
      if (!details.open || loaded || loading) return;
      loading = true;
      try {
        // Artifact viewers are intentionally outside the core job-detail
        // group.  Configuration/status pages must not execute chart, table,
        // or price-viewer code until a user expands this declaration.
        await window.FTStaticLoader?.loadGroups?.(["job-detail-previews"]);
        if (!window.FTJobArtifactViewers) {
          throw new Error(context.t("生成物查看器不可用"));
        }
        for (let index = 0; index < artifacts.length; index += 1) {
          try {
            await FTJobArtifactViewers.mount(context, target, {
              declaration, artifact: artifacts[index], jobID, artifactQuery,
            });
            loaded = true;
            return;
          } catch (error) {
            const canFallback = index + 1 < artifacts.length
              && [404, 410].includes(Number(error.status));
            if (!canFallback) throw error;
          }
        }
      } catch (error) {
        target.textContent = error.message;
      } finally {
        loading = false;
      }
    });
    return details;
  }

  window.FTJobArtifacts = {
    artifactRows,
    artifactDownloadParts,
    clearArtifacts,
    deleteArtifact,
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
