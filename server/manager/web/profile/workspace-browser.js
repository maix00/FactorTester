(() => {
  function formatBytes(value) {
    const size = Number(value || 0);
    if (size < 1024) return `${size} B`;
    if (size < 1024 ** 2) return `${(size / 1024).toFixed(1)} KiB`;
    if (size < 1024 ** 3) return `${(size / 1024 ** 2).toFixed(1)} MiB`;
    return `${(size / 1024 ** 3).toFixed(1)} GiB`;
  }

  function pathQuery(profileID, path) {
    const query = new URLSearchParams({profile_id: profileID});
    if (path) query.set("path", path);
    return `/api/client/profile-workspace?${query.toString()}`;
  }

  // A bare icon button (no surrounding pill/ring), fixed height, so rows stay
  // the same height whether or not an action column is present.
  function iconButton(context, symbol, label, action) {
    const button = FTUI.iconButton(context, symbol, label, async event => {
      event?.stopPropagation?.();
      if (button.disabled) return;
      button.disabled = true;
      try { await action(); }
      catch (error) { context.showNotice?.(error.message || String(error), true); }
      finally { button.disabled = false; }
    });
    return button;
  }

  async function download(context, profileID, path, filename) {
    const issued = await context.api("/api/transfers/objects/download-access", {
      method: "POST",
      body: JSON.stringify({
        object_kind: "profile_workspace",
        profile_id: profileID,
        path,
      }),
    });
    const access = issued?.access || {};
    if (!access.url || !access.bearer) {
      throw new Error(context.t("下载授权无效"));
    }
    const response = await fetch(access.url, {
      credentials: "omit",
      redirect: "error",
      headers: {Authorization: `Bearer ${access.bearer}`},
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || context.t("文件下载失败"));
    }
    const url = URL.createObjectURL(await response.blob());
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename || path.split("/").at(-1) || "workspace-file";
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function upload(context, profileID, reload) {
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    input.addEventListener("change", async () => {
      const files = Array.from(input.files || []);
      if (!files.length) return;
      try {
        for (const file of files) {
          const query = new URLSearchParams({
            profile_id: profileID,
            path: "uploads",
            filename: file.name,
          });
          await context.api(`/api/client/profile-workspace/upload?${query}`, {
            method: "POST",
            body: file,
            headers: {"Content-Type": "application/octet-stream"},
          });
        }
        context.showNotice?.(context.t("已上传到 uploads/"), false);
      } catch (error) {
        context.showNotice?.(error.message || String(error), true);
      } finally {
        await reload("uploads");
      }
    });
    input.click();
  }

  function render(context, profile) {
    const root = document.createElement("section");
    root.className = "job-section profile-workspace-browser";
    const header = document.createElement("div");
    header.className = "profile-workspace-header";
    const heading = document.createElement("h2");
    heading.textContent = context.t("工作区文件");
    header.append(heading);
    const uploadButton = iconButton(context, "arrow.up.circle", context.t("上传到 uploads"), () => {
      void upload(context, profile.profile_id, path => { currentPath = path; return load(); });
    });
    uploadButton.classList.add("workspace-upload-btn");
    const actions = document.createElement("div");
    actions.className = "profile-workspace-actions";
    actions.append(iconButton(context, "arrow.clockwise", context.t("刷新"), () => load()), uploadButton);
    header.append(actions);
    root.append(header);

    const body = document.createElement("div");
    root.append(body);

    const runtime = profile.runtime || {};
    if (runtime.runtime_kind !== "server" || runtime.configured === false) {
      uploadButton.disabled = true;
      body.append(FTUI.empty(
        context.t("工作区尚未创建"),
        context.t("请先在运行绑定中绑定服务器运行位置。"),
      ));
      return root;
    }

    let currentPath = "";
    let revision = 0;
    let lastListing = "";
    let pending = 0;
    let disposed = false;
    const load = async (quiet = false) => {
      if (disposed || (quiet && pending)) return;
      pending += 1;
      const request = ++revision;
      const path = currentPath;
      if (!quiet) body.replaceChildren(FTUI.loading(context.t("正在读取工作区…")));
      try {
        const payload = await context.api(pathQuery(profile.profile_id, currentPath));
        if (disposed || request !== revision || path !== currentPath) return;
        const signature = JSON.stringify(payload);
        if (quiet && signature === lastListing) return;
        lastListing = signature;
        heading.textContent = `${context.t("工作区文件")} /${path}`;
        const shell = FTUI.table([
          context.t("名称"), context.t("类型"), context.t("大小"), context.t("操作"),
        ], []);
        if (currentPath) {
          const parent = currentPath.split("/").slice(0, -1).join("/");
          const row = shell.body.insertRow();
          row.className = "workspace-row";
          row.insertCell().textContent = "..";
          row.insertCell().textContent = context.t("上级目录");
          row.insertCell();
          const action = row.insertCell();
          action.append(iconButton(context, "chevron.left", context.t("返回上级"), () => {
            currentPath = parent; load();
          }));
        }
        (payload.entries || []).forEach(item => {
          const row = shell.body.insertRow();
          row.className = "workspace-row";
          const isDir = item.kind === "directory";
          const name = row.insertCell();
          const icon = window.FTIcons?.node?.(isDir ? "folder.fill" : "doc.text");
          if (icon) name.append(icon);
          const nameSpan = document.createElement(isDir ? "button" : "span");
          if (isDir) {
            nameSpan.type = "button";
            nameSpan.className = "table-link";
            nameSpan.onclick = () => { currentPath = item.path; void load(); };
          }
          nameSpan.textContent = item.name;
          name.append(nameSpan);
          row.insertCell().textContent = isDir ? context.t("文件夹") : context.t("文件");
          row.insertCell().textContent = isDir ? "—" : formatBytes(item.size_bytes);
          const action = row.insertCell();
          if (isDir) {
            const openBtn = iconButton(context, "folder", context.t("打开"), () => {
              currentPath = item.path; load();
            });
            action.append(openBtn);
          } else {
            const downloadBtn = iconButton(context, "arrow.down.circle", context.t("下载"), async () => {
              try { await download(context, profile.profile_id, item.path, item.name); }
              catch (error) { context.showNotice?.(error.message || String(error), true); }
            });
            action.append(downloadBtn);
            const deleteButton = iconButton(context, "trash", context.t("删除"), async () => {
              if (!window.confirm(context.t(`确定删除 ${item.name}？此操作无法恢复。`))) return;
              try {
                await context.api("/api/client/profile-workspace", {
                  method: "DELETE",
                  body: JSON.stringify({profile_id: profile.profile_id, path: item.path}),
                });
                await load();
              } catch (error) {
                context.showNotice(error.message || String(error), true);
              }
            });
            action.append(deleteButton);
          }
        });
        body.replaceChildren(shell.shell);
      } catch (error) {
        if (disposed || request !== revision) return;
        if (quiet) return;
        body.replaceChildren(FTUI.empty(
          context.t("无法读取工作区"), error.message || String(error),
        ));
      } finally { pending -= 1; }
    };
    void load();
    // One visible directory per mounted browser; stop when the view is removed.
    // No recursive scan or new synchronization channel is needed.
    const timer = setInterval(() => {
      if (!root.isConnected || context.isRouteCurrent?.() === false || document.hidden) return;
      void load(true);
    }, 5000);
    context.pageState?.register?.(`profile-workspace:${profile.profile_id}`, {
      dispose() { disposed = true; revision += 1; clearInterval(timer); },
    });
    return root;
  }

  window.FTProfileWorkspace = Object.freeze({render});
})();
