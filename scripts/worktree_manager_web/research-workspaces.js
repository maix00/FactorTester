(() => {
  const sections = [
    ["local", "本地研究"],
    ["shared", "共享研究"],
    ["graph", "研究图"],
  ];

  async function list(context) {
    const selected = new URLSearchParams(location.search).get("section") || "shared";
    const embedded = new URLSearchParams(location.search).get("presentation") === "embedded";
    context.activeNav("research");
    context.setHeading(context.t("研究"), context.t(labelFor(selected)));
    context.content.replaceChildren(FTUI.loading(context.t("正在读取研究…")));
    // Keep the section switcher in the page toolbar, alongside the native
    // Swift picker.  Placing it in the content column made the switcher and
    // the "shared reports" heading compete for the same top-of-page space.
    // Swift owns the picker when embedded, so the WebView must not add a
    // second control in that presentation.
    if (!embedded) context.toolbar.append(tabBar(context, selected));
    context.toolbar.append(context.button("↻", () => list(context), context.t("刷新")));
    context.content.replaceChildren();
    const body = document.createElement("div");
    body.className = "research-workspace-page";
    context.content.append(body);
    try {
      if (selected === "local") await renderLocal(context, body, embedded);
      else if (selected === "graph") await renderGraph(context, body);
      else await renderShared(context, body, embedded);
    } catch (error) {
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
      const local = embedded && item.is_owned
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
    mount.append(clientDownload(context, releaseResult));
    // A standalone browser cannot read the user's local filesystem.  The
    // embedded Swift client is the owner of that local report projection and
    // may request it through the authenticated client endpoint.
    if (!embedded || !context.session) return;
    const researchResult = await context.api("/api/client/research");
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

  async function renderGraph(context, mount) {
    const graphID = "factor-research";
    const [versionsResult, activeResult] = await Promise.allSettled([
      context.api(context.servicePath(`/api/research-graphs/${graphID}/versions`)),
      context.api(context.servicePath(`/api/research-graphs/${graphID}/active`)),
    ]);
    if (versionsResult.status !== "fulfilled") throw versionsResult.reason;
    const versions = versionsResult.value.versions || [];
    const active = activeResult.status === "fulfilled" ? activeResult.value.graph : null;
    const currentVersion = Number(new URLSearchParams(location.search).get("version"));
    const graph = versions.find(item => item.version === currentVersion) || active || versions.at(-1);
    if (!graph) {
      mount.append(FTUI.empty(context.t("暂无研究图"), context.t("服务器尚未提供可浏览的研究图版本")));
      return;
    }
    const section = document.createElement("section");
    section.className = "job-section";
    const header = document.createElement("div");
    header.className = "research-graph-toolbar";
    const title = document.createElement("h2");
    title.textContent = `${context.t("研究图")} ${graph.graph_id || graphID}@v${graph.version}`;
    header.append(title);
    const picker = document.createElement("select");
    picker.className = "graph-version-picker";
    versions.forEach(item => {
      const option = document.createElement("option");
      option.value = item.version;
      option.textContent = `v${item.version} · ${item.lifecycle || ""}`;
      option.selected = item.version === graph.version;
      picker.append(option);
    });
      picker.addEventListener("change", () => {
        const url = new URL(location.href);
        url.searchParams.set("section", "graph");
        url.searchParams.set("version", picker.value);
        history.pushState({}, "", `${url.pathname}?${url.searchParams.toString()}`);
        window.dispatchEvent(new PopStateEvent("popstate"));
    });
    header.append(picker);
    section.append(header);
    const meta = document.createElement("p");
    meta.className = "secondary";
    meta.textContent = `${context.t("当前激活版本")}: v${active?.version || "—"} · ${graph.content_hash || ""}`;
    section.append(meta);
    const browser = document.createElement("div");
    browser.className = "graph-browser";
    browser.append(graphNodeList(context, graph), graphEdgeList(context, graph));
    section.append(browser);
    mount.append(section);
  }

  function graphNodeList(context, graph) {
    const section = document.createElement("section");
    section.className = "graph-node-list";
    const heading = document.createElement("h3");
    heading.textContent = `${context.t("节点")}（${(graph.nodes || []).length}）`;
    section.append(heading);
    (graph.nodes || []).forEach((node, index) => {
      const item = document.createElement("article");
      item.className = "graph-node graph-node-static";
      item.innerHTML = `<span class="graph-node-index">${index + 1}</span><span><b></b><small></small></span>`;
      item.querySelector("b").textContent = node.title || node.label || node.node_id || node.id;
      item.querySelector("small").textContent = node.node_id || node.id || "";
      section.append(item);
    });
    return section;
  }

  function graphEdgeList(context, graph) {
    const section = document.createElement("section");
    section.className = "graph-detail graph-edge-list";
    const heading = document.createElement("h3");
    heading.textContent = `${context.t("边与义务")}（${(graph.edges || []).length}）`;
    section.append(heading);
    (graph.edges || []).forEach(edge => {
      const item = document.createElement("article");
      item.className = "graph-edge";
      const title = document.createElement("b");
      title.textContent = `${edge.source || edge.from || edge.from_node || ""} → ${edge.target || edge.to || edge.to_node || ""}`;
      item.append(title);
      const requirements = edge.requirements || edge.edge_requirements || edge.obligations || [];
      if (requirements.length) {
        const list = document.createElement("div");
        list.className = "requirement-list";
        requirements.forEach(requirement => {
          const row = document.createElement("div");
          row.className = "requirement-row";
          row.innerHTML = "<b></b><small></small>";
          row.querySelector("b").textContent = requirement.title_zh || requirement.title || requirement.requirement_id || requirement.id || "";
          row.querySelector("small").textContent = requirement.requirement_id || requirement.id || "";
          list.append(row);
        });
        item.append(list);
      }
      section.append(item);
    });
    return section;
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
