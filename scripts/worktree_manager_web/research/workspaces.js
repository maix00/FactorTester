(() => {
  const sections = [
    ["local", "本地研究"],
    ["shared", "共享研究"],
    ["graph", "研究图"],
  ];

  async function list(context) {
    const isCurrent = () => context.isRouteCurrent?.() !== false;
    if (!isCurrent()) return;
    const selected = new URLSearchParams(location.search).get("section") || "shared";
    const embedded = new URLSearchParams(location.search).get("presentation") === "embedded";
    context.activeNav("research");
    context.setHeading(context.t("研究"), context.t(labelFor(selected)));
    context.content.replaceChildren(FTUI.loading(context.t("正在读取研究…")));
    // The Web page is the single owner of the research section switcher in
    // both standalone Web and embedded Swift presentation.  Swift owns the
    // surrounding tab and WebView session, but must not duplicate this
    // control with a second native picker.
    context.toolbar.append(tabBar(context, selected));
    context.toolbar.append(context.button("↻", () => list(context), context.t("刷新")));
    const body = document.createElement("div");
    body.className = "research-workspace-page";
    body.append(FTUI.loading(context.t("正在读取研究…")));
    context.content.replaceChildren(body);
    try {
      // Keep an explicit loading state visible until the selected page has
      // finished its first request. Clearing the container before the async
      // branch used to leave a blank research page during cold start.
      body.replaceChildren();
      if (selected === "local") await renderLocal(context, body, embedded);
      else if (selected === "graph") await FTResearchGraph.render(context, body);
      else await renderShared(context, body, embedded);
      if (!isCurrent()) return;
    } catch (error) {
      if (!isCurrent()) return;
      body.replaceChildren(FTUI.empty(context.t("无法读取"), error.message));
    }
  }

  function labelFor(section) {
    return sections.find(item => item[0] === section)?.[1] || "共享研究";
  }

  function tabBar(context, selected) {
    const nav = document.createElement("nav");
    nav.className = "research-section-tabs";
    nav.setAttribute("aria-label", context.t("研究页面"));
    sections.forEach(([id, label]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `research-section-tab${id === selected ? " active" : ""}`;
      button.textContent = context.t(label);
      button.setAttribute("aria-current", id === selected ? "page" : "false");
      button.addEventListener("click", () => {
        const url = new URL(location.href);
        url.searchParams.set("section", id);
        history.pushState({}, "", `${url.pathname}?${url.searchParams.toString()}`);
        window.dispatchEvent(new PopStateEvent("popstate"));
      });
      nav.append(button);
    });
    return nav;
  }

  async function renderShared(context, mount, embedded) {
    const [publicResult, localResult] = await Promise.allSettled([
      context.api("/api/public-research"),
      embedded && context.session
        ? context.api("/api/client/research")
        : Promise.reject(new Error("local source is available only in the Swift client")),
    ]);
    if (context.isRouteCurrent?.() === false) return;
    const publications = publicResult.status === "fulfilled"
      ? publicResult.value.reports || [] : [];
    const localByReportID = new Map(
      localResult.status === "fulfilled"
        ? (localResult.value.research || [])
            .filter(item => item.report_id && item.local_ref)
            .map(item => [String(item.report_id), item])
        : [],
    );
    const visiblePublications = publications.map(item => {
      // Only the server's explicit ownership fact may select the local
      // projection. A matching title, profile label, or report id alone is
      // not sufficient to show another user's snapshot as local content.
      const local = embedded && item.is_owned === true
        ? localByReportID.get(String(item.report_id || ""))
        : null;
      return local
        ? {...item, href: `/research/${encodeURIComponent(`local:${local.local_ref}`)}`, local_source: true}
        : item;
    });
    mount.append(visiblePublications.length
      ? publicationSection(context, visiblePublications)
      : FTUI.empty(context.t("暂无共享研究报告"), context.t("报告所有者在 FTClient 中开启共享后会显示在这里")));
  }

  async function renderLocal(context, mount, embedded) {
    const releaseResult = await Promise.allSettled([
      context.api(context.servicePath("/api/client/releases/beta.json")),
    ]).then(results => results[0]);
    if (context.isRouteCurrent?.() === false) return;
    mount.append(clientDownload(context, releaseResult));
    // A standalone browser cannot read the user's local filesystem.  The
    // embedded Swift client is the owner of that local report projection and
    // may request it through the authenticated client endpoint.
    if (!embedded || !context.session) return;
    const researchResult = await context.api("/api/client/research");
    if (context.isRouteCurrent?.() === false) return;
    const rows = researchResult.research || [];
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
        [context.t("研究"), context.t("Profile"), context.t("分支"), context.t("更新时间")],
        rows.map(item => [
          item.title,
          item.profile_name || item.profile_id,
          item.branch_id,
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

  function clientDownload(context, releaseResult) {
    const section = document.createElement("section");
    section.className = "job-section client-download";
    const header = document.createElement("div");
    header.className = "client-download-header";
    const icon = document.createElement("span");
    icon.className = "client-download-icon";
    icon.append(FTIcons.node("arrow.down.circle"));
    const title = document.createElement("div");
    const heading = document.createElement("h2");
    heading.textContent = context.t("客户端下载");
    const subtitle = document.createElement("p");
    subtitle.className = "secondary";
    subtitle.textContent = context.t("下载桌面客户端，直接读取本机研究工作区");
    title.append(heading, subtitle);
    header.append(icon, title);
    section.append(header);
    const description = document.createElement("p");
    description.className = "client-download-note";
    description.textContent = context.t("当前提供 macOS 客户端；其他平台准备中");
    section.append(description);
    const value = releaseResult.status === "fulfilled" ? releaseResult.value : null;
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
    section.append(downloads);
    return section;
  }

  function publicationSection(context, reports) {
    const section = document.createElement("section");
    section.className = "job-section";
    const heading = document.createElement("h2");
    heading.textContent = context.t("共享研究报告");
    section.append(heading);
    const table = FTUI.table(
      [context.t("报告"), context.t("用户（Profile）"), "Generation", context.t("访问范围"), context.t("同步时间")],
      reports.map(item => [item.title, ownerDisplay(item, context), item.generation, visibilityTitle(context, item.visibility), FTUI.formatDate(item.updated_at)]),
    );
    [...table.body.rows].forEach((row, index) => {
      row.dataset.href = "true";
      row.addEventListener("click", () => context.navigate(reports[index].href));
    });
    section.append(table.shell);
    return section;
  }

  function ownerDisplay(item, context) {
    const owner = String(item.owner_ref || item.owner_username || "").trim();
    const profile = String(item.profile_ref || item.profile_id || "").trim();
    if (owner && profile) return `${owner}（${profile}）`;
    return owner || profile || context.t("未知");
  }

  function visibilityTitle(context, value) {
    const title = {private: "仅自己", authorized: "授权用户", public: "公开"}[value];
    return title ? context.t(title) : value || "";
  }

  window.FTResearch = {list};
})();
