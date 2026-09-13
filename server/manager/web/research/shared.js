(() => {
  async function render(context, mount, embedded) {
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
    const visiblePublications = publications.map(item =>
      FTResearch.resolvePublicationSource(item, localByReportID, embedded),
    );
    mount.append(visiblePublications.length
      ? publicationSection(context, visiblePublications)
      : FTUI.empty(
        context.t("暂无共享研究报告"),
        context.t("报告所有者在 FTClient 中开启共享后会显示在这里"),
      ));
  }

  function publicationSection(context, reports) {
    const section = document.createElement("section");
    section.className = "job-section";
    const heading = document.createElement("h2");
    heading.textContent = context.t("共享研究报告");
    section.append(heading);
    const table = FTUI.table(
      [
        context.t("报告"), context.t("用户（Profile）"), context.t("构建来源"),
        context.t("共享状态"), "Generation", context.t("访问范围"),
        context.t("同步时间"),
      ],
      reports.map(item => [
        item.title,
        ownerDisplay(item, context),
        buildSource(context, item),
        sharing(context, item),
        item.generation,
        visibilityTitle(context, item.visibility),
        FTUI.formatDate(item.updated_at),
      ]),
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
    const label = FTUI.userLabel(owner, item.owner_alias);
    return FTUI.userDisplay(owner, (label && profile ? `${label}（${profile}）` : label || profile || context.t("未知")));
  }

  function visibilityTitle(context, value) {
    const title = {
      private: "仅自己", superiors: "分享给上级",
      authorized: "指定用户可见", public: "全体用户共享",
    }[value];
    return title ? context.t(title) : value || "";
  }

  function buildSource(context, item) {
    return context.t(
      item.build_source === "server_agent"
        ? "服务器 Agent 构建" : "客户端构建",
    );
  }

  function sharing(context, item) {
    return context.t(
      item.sharing_state === "shared" || item.is_shared === true
        ? "共享" : "非共享",
    );
  }

  window.FTResearchShared = Object.freeze({
    render,
    resolvePublicationSource: (...args) => FTResearch.resolvePublicationSource(...args),
  });
})();
