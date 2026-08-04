(() => {
  async function list(context) {
    context.activeNav("research");
    context.setHeading(context.t("研究"), context.t("共享研究报告"));
    context.content.replaceChildren(FTUI.loading(context.t("正在读取共享报告…")));
    context.toolbar.append(context.button("↻", () => list(context), context.t("刷新")));
    const [releaseResult, publicResult] = await Promise.allSettled([
      context.api(context.servicePath("/api/client/releases/beta.json")),
      context.api("/api/public-research"),
    ]);
    const publications = publicResult.status === "fulfilled"
      ? publicResult.value.reports || []
      : [];
    const root = document.createElement("div");
    root.className = "detail-stack";
    root.append(clientDownload(context, releaseResult));
    if (publications.length) root.append(publicationSection(context, publications));
    else root.append(FTUI.empty(
      context.t("暂无共享研究报告"),
      context.t("报告所有者在 FTClient 中开启共享后会显示在这里"),
    ));
    context.content.replaceChildren(root);
  }

  function clientDownload(context, releaseResult) {
    const section = document.createElement("section");
    section.className = "job-section";
    const heading = document.createElement("h2");
    heading.textContent = "FTClient";
    section.append(heading);
    const description = document.createElement("p");
    description.className = "secondary";
    description.textContent = context.t(
      "本地研究、研究图与报告编辑由 macOS FTClient 提供；Web 端只展示已共享的研究报告"
    );
    section.append(description);
    const value = releaseResult.status === "fulfilled" ? releaseResult.value : null;
    if (value?.url) {
      const link = document.createElement("a");
      link.className = "button-link primary";
      link.href = value.url;
      link.textContent = `${context.t("下载 FTClient")} ${value.version || value.short_version || "Beta"}`;
      section.append(link);
    } else {
      const note = document.createElement("p");
      note.className = "secondary";
      note.textContent = context.t("当前服务暂未提供可下载的客户端安装包");
      section.append(note);
    }
    return section;
  }

  function publicationSection(context, reports) {
    const section = document.createElement("section");
    section.className = "job-section";
    const heading = document.createElement("h2");
    heading.textContent = context.t("共享研究报告");
    section.append(heading);
    const table = FTUI.table(
      [context.t("报告"), "Generation", context.t("访问范围"), context.t("同步时间")],
      reports.map(item => [
        item.title,
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

  function visibilityTitle(context, value) {
    const title = {private: "仅自己", authorized: "授权用户", public: "公开"}[value];
    return title ? context.t(title) : value || "";
  }

  window.FTResearch = {list};
})();
