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
      throw new Error(context.t("工作区下载授权无效"));
    }
    const response = await fetch(access.url, {
      credentials: "omit",
      redirect: "error",
      headers: {Authorization: `Bearer ${access.bearer}`},
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || context.t("工作区文件下载失败"));
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

  function render(context, profile) {
    const root = document.createElement("section");
    root.className = "job-section profile-workspace-browser";
    const heading = document.createElement("h2");
    heading.textContent = context.t("服务器工作区");
    const note = document.createElement("p");
    note.className = "settings-muted";
    note.textContent = context.t(
      "敏感文件不会显示；文件通过 7997 数据通道下载，可由用户显式删除。",
    );
    const body = document.createElement("div");
    root.append(heading, note, body);

    const runtime = profile.runtime || {};
    if (runtime.runtime_kind !== "server" || runtime.configured === false) {
      body.append(FTUI.empty(
        context.t("工作区尚未创建"),
        context.t("请先在运行绑定中绑定服务器运行位置。"),
      ));
      return root;
    }

    let currentPath = "";
    const load = async () => {
      body.replaceChildren(FTUI.loading(context.t("正在读取工作区…")));
      try {
        const payload = await context.api(pathQuery(profile.profile_id, currentPath));
        const shell = FTUI.table([
          context.t("名称"), context.t("类型"), context.t("大小"), context.t("操作"),
        ], []);
        if (currentPath) {
          const parent = currentPath.split("/").slice(0, -1).join("/");
          const row = shell.body.insertRow();
          row.insertCell().textContent = "..";
          row.insertCell().textContent = context.t("上级目录");
          row.insertCell();
          const action = row.insertCell();
          const button = document.createElement("button");
          button.type = "button";
          button.className = "secondary";
          button.textContent = context.t("返回");
          button.onclick = () => { currentPath = parent; load(); };
          action.append(button);
        }
        (payload.entries || []).forEach(item => {
          const row = shell.body.insertRow();
          const name = row.insertCell();
          const link = document.createElement("button");
          link.type = "button";
          link.className = "table-link";
          link.textContent = item.name;
          if (item.kind === "directory") {
            link.onclick = () => { currentPath = item.path; load(); };
          } else {
            link.onclick = async () => {
              link.disabled = true;
              try {
                await download(context, profile.profile_id, item.path, item.name);
              } catch (error) {
                context.showNotice(error.message || String(error), true);
              } finally {
                link.disabled = false;
              }
            };
          }
          name.append(link);
          row.insertCell().textContent = item.kind === "directory"
            ? context.t("文件夹") : context.t("文件");
          row.insertCell().textContent = item.kind === "directory"
            ? "—" : formatBytes(item.size_bytes);
          const action = row.insertCell();
          if (item.kind === "file") {
            const actionButton = document.createElement("button");
            actionButton.type = "button";
            actionButton.className = "secondary";
            actionButton.textContent = context.t("下载");
            actionButton.onclick = () => link.click();
            action.append(actionButton);
            const deleteButton = document.createElement("button");
            deleteButton.type = "button";
            deleteButton.className = "danger";
            deleteButton.textContent = context.t("删除");
            deleteButton.onclick = async () => {
              if (!window.confirm(context.t(`确定删除 ${item.name}？此操作无法恢复。`))) return;
              deleteButton.disabled = true;
              try {
                await context.api("/api/client/profile-workspace", {
                  method: "DELETE",
                  body: JSON.stringify({profile_id: profile.profile_id, path: item.path}),
                });
                await load();
              } catch (error) {
                context.showNotice(error.message || String(error), true);
                deleteButton.disabled = false;
              }
            };
            action.append(deleteButton);
          } else {
            action.textContent = context.t("打开");
          }
        });
        body.replaceChildren(shell.shell);
      } catch (error) {
        body.replaceChildren(FTUI.empty(
          context.t("无法读取工作区"), error.message || String(error),
        ));
      }
    };
    load();
    return root;
  }

  window.FTProfileWorkspace = Object.freeze({render});
})();
