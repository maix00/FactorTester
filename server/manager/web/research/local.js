(() => {
  async function render(context, mount, embedded) {
    const release = await loadClientRelease(context);
    if (context.isRouteCurrent?.() === false) return;
    mount.append(clientDownload(context, release));
    // A standalone browser cannot read the user's local filesystem.  The
    // embedded Swift client owns that projection and requests it explicitly.
    if (!embedded || !context.session) return;
    const [researchResult, publicationResult] = await Promise.all([
      context.api("/api/client/research"),
      context.api("/api/research-publications/settings").catch(() => ({reports: []})),
    ]);
    if (context.isRouteCurrent?.() === false) return;
    const rows = researchResult.research || [];
    const publications = new Map(
      (publicationResult.reports || [])
        .filter(item => item?.report_id)
        .map(item => [String(item.report_id), item]),
    );
    const section = document.createElement("section");
    section.className = "job-section";
    const heading = document.createElement("h2");
    heading.textContent = context.t("本地研究");
    section.append(heading);
    section.append(Object.assign(document.createElement("p"), {
      className: "secondary",
      textContent: context.t("读取当前账户本机工作区中的报告；报告内容只在本机渲染"),
    }));
    if (!rows.length) {
      section.append(FTUI.empty(
        context.t("暂无本地研究"),
        context.t("先在 FTClient 中创建或打开研究"),
      ));
    } else {
      const table = FTUI.table(
        [
          context.t("研究"), context.t("Profile"), context.t("分支"),
          context.t("构建来源"), context.t("共享状态"), context.t("更新时间"),
        ],
        rows.map(item => [
          item.title,
          item.profile_name || item.profile_id,
          item.branch_id,
          context.t("客户端构建"),
          context.t(
            sharingState(item, publications.get(String(item.report_id || "")))
              === "shared" ? "共享" : "非共享",
          ),
          FTUI.formatDate(item.updated_at),
        ]),
      );
      [...table.body.rows].forEach((row, index) => {
        row.dataset.href = "true";
        row.addEventListener("click", () => context.navigate(
          `/research/${encodeURIComponent(`local:${rows[index].local_ref}`)}`,
        ));
      });
      section.append(table.shell);
    }
    mount.append(section);
  }

  function sharingState(item, publication) {
    const value = item?.sharing_state || publication?.sharing_state;
    if (value === "shared" || value === "not_shared") return value;
    if (item?.is_shared === true || publication?.is_shared === true) return "shared";
    const visibility = item?.visibility || publication?.visibility;
    return ["authorized", "public"].includes(visibility)
      ? "shared" : "not_shared";
  }

  function clientDownload(context, value) {
    const section = document.createElement("section");
    section.className = "research-client-download-action";
    section.append(clientDownloadButton(context, value));
    return section;
  }

  function clientDownloadButton(context, value) {
    const open = context.button(
      context.t("客户端下载"),
      () => showDownloadOverlay(context, value),
      context.t("打开客户端下载"),
    );
    open.prepend(FTIcons.node("arrow.down.circle"));
    return open;
  }

  async function loadClientRelease(context) {
    try {
      return await context.api(context.servicePath("/api/client/releases/beta.json"));
    } catch (_) {
      return null;
    }
  }

  function downloadChoices(context, value) {
    const downloads = document.createElement("div");
    downloads.className = "client-download-grid";
    const mac = document.createElement("div");
    mac.className = "client-download-item";
    const macHeader = document.createElement("div");
    macHeader.className = "client-platform-header";
    const macTitle = document.createElement("b");
    macTitle.textContent = "macOS";
    const macStatus = document.createElement("span");
    macStatus.className = `client-platform-status${value ? " available" : ""}`;
    macStatus.textContent = value ? context.t("可下载") : context.t("暂不可用");
    macHeader.append(macTitle, macStatus);
    const macDescription = document.createElement("p");
    macDescription.textContent = context.t("原生 Swift 客户端，包含本地研究与研究图浏览");
    mac.append(macHeader, macDescription);
    const macMeta = document.createElement("small");
    macMeta.className = "client-platform-meta";
    macMeta.textContent = value?.version
      ? `${context.t("最新版本")} ${value.version}`
      : context.t("暂未发现可用版本");
    mac.append(macMeta);
    const link = document.createElement("a");
    link.className = "button-link primary";
    link.textContent = context.t("下载 macOS 客户端");
    link.href = value?.dmg_url || value?.url || "#";
    link.target = "_blank";
    link.rel = "noopener";
    if (!value?.dmg_url && !value?.url) {
      link.classList.add("disabled");
      link.setAttribute("aria-disabled", "true");
      link.addEventListener("click", event => event.preventDefault());
    }
    mac.append(link);
    downloads.append(mac);
    ["Windows", "Linux"].forEach(platform => {
      const item = document.createElement("div");
      item.className = "client-download-item unavailable";
      const platformHeader = document.createElement("div");
      platformHeader.className = "client-platform-header";
      const platformTitle = document.createElement("b");
      platformTitle.textContent = platform;
      const platformStatus = document.createElement("span");
      platformStatus.className = "client-platform-status";
      platformStatus.textContent = context.t("准备中");
      platformHeader.append(platformTitle, platformStatus);
      const platformDescription = document.createElement("p");
      platformDescription.textContent = context.t("跨平台客户端尚未提供");
      item.append(platformHeader, platformDescription);
      downloads.append(item);
    });
    return downloads;
  }

  function showDownloadOverlay(context, value) {
    const dialog = document.createElement("dialog");
    dialog.dataset.ftTabID = context.tabID || "";
    dialog.className = "ft-dialog client-download-dialog";
    const card = document.createElement("div");
    card.className = "dialog-card wide";
    const heading = document.createElement("h2");
    heading.textContent = context.t("客户端下载");
    const close = context.button(context.t("关闭"), () => dialog.close(), context.t("关闭"));
    close.className = "dialog-close";
    card.append(heading, close);
    const note = document.createElement("p");
    note.className = "secondary";
    note.textContent = context.t(
      "下载桌面客户端安装包；当前提供 macOS，其他平台准备中",
    );
    card.append(note, downloadChoices(context, value));
    dialog.append(card);
    dialog.addEventListener("close", () => dialog.remove(), {once: true});
    document.body.append(dialog);
    dialog.showModal();
  }

  window.FTResearchLocal = Object.freeze({
    render, clientDownload, clientDownloadButton, loadClientRelease,
  });
})();
