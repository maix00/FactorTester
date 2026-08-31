(() => {
  const pageSize = 20;
  const detailTabs = [
    ["overview", "概览"],
    ["fragments", "摘选与来源"],
    ["relationships", "引用关系"],
  ];

  function catalogState(context) {
    const state = context.tabSession.researchEvidence || {page: 1, text: ""};
    context.tabSession.researchEvidence = state;
    return state;
  }

  async function render(context, mount) {
    const state = catalogState(context);
    mount.replaceChildren(FTUI.loading(context.t("正在读取证据目录…")));
    const query = new URLSearchParams({
      page: String(state.page || 1), page_size: String(pageSize),
    });
    if (state.text) query.set("text", state.text);
    try {
      const value = await context.api(`/api/research-evidence/catalog?${query}`);
      if (context.isRouteCurrent?.() === false) return;
      const catalog = value.catalog || {};
      const root = document.createElement("section");
      root.className = "research-evidence-catalog";
      const search = document.createElement("input");
      search.type = "search";
      search.value = state.text || "";
      search.placeholder = context.t("搜索证据标题或摘要");
      search.setAttribute("aria-label", context.t("搜索证据"));
      search.addEventListener("change", () => {
        state.text = search.value.trim();
        state.page = 1;
        void render(context, mount);
      });
      root.append(search);
      const items = catalog.items || [];
      if (!items.length) {
        root.append(FTUI.empty(
          context.t("暂无证据"), context.t("Job、本地文件和服务器来源登记的 Evidence 会显示在这里"),
        ));
      } else {
        const view = FTUI.pagedTable([
          context.t("证据"), context.t("类型"), context.t("来源"),
          context.t("适用对象"), context.t("适用环境"),
          context.t("位置"), context.t("状态"), context.t("登记时间"),
        ], items.map(item => [
          item.title_zh || item.evidence_ref,
          item.evidence_kind || "—",
          (item.source_kinds || []).join("、") || "—",
          scopeSummary(item.applicable_objects),
          environmentSummary(item.applicable_environment),
          (item.source_locations || []).join("、") || context.t("当前服务器"),
          item.lifecycle_status || "active",
          FTUI.formatDate(item.created_at),
        ]), {
          remote: true,
          page: catalog.page,
          pageSize: catalog.page_size,
          total: catalog.total,
          pageLabel: (page, total) => `${page} / ${total}`,
          totalLabel: total => `${context.t("共")} ${total} ${context.t("条")}`,
          onPageChange: page => {
            state.page = page;
            void render(context, mount);
          },
        });
        [...view.body.rows].forEach((row, index) => {
          const item = items[index];
          row.dataset.href = "true";
          row.addEventListener("click", () => context.navigate(
            `/evidence/${encodeURIComponent(item.evidence_ref)}`,
            {
              id: `evidence-detail:${encodeURIComponent(item.evidence_ref)}`,
              title: item.title_zh || context.t("证据"),
              closable: true,
              parentFolder: "research",
            },
          ));
        });
        root.append(view.shell);
      }
      mount.replaceChildren(root);
    } catch (error) {
      mount.replaceChildren(FTUI.empty(context.t("无法读取证据"), error.message));
    }
  }

  async function detail(context, mount, evidenceRef) {
    const key = `evidence:${evidenceRef}`;
    const state = context.tabSession[key] || {
      activeTab: "overview", full: null, relationshipPage: 1,
    };
    context.tabSession[key] = state;
    mount.replaceChildren(FTUI.loading(context.t("正在读取证据…")));
    try {
      const value = await context.api(
        `/api/research-evidence/catalog/${encodeURIComponent(evidenceRef)}/summary`,
      );
      if (context.isRouteCurrent?.() === false) return;
      const evidence = value.evidence || {};
      context.setHeading(evidence.title_zh || context.t("证据"), context.t("证据详情"));
      const root = document.createElement("section");
      root.className = "research-evidence-detail";
      const nav = document.createElement("nav");
      nav.className = "research-section-tabs";
      const content = document.createElement("div");
      for (const [id, label] of detailTabs) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = `research-section-tab${state.activeTab === id ? " active" : ""}`;
        button.textContent = context.t(label);
        button.addEventListener("click", async () => {
          state.activeTab = id;
          await detail(context, mount, evidenceRef);
        });
        nav.append(button);
      }
      root.append(nav, content);
      if (state.activeTab === "overview") {
        content.append(FTUI.table([
          context.t("字段"), context.t("值"),
        ], [
          [context.t("证据标识"), evidence.evidence_ref],
          [context.t("类型"), evidence.evidence_kind],
          [context.t("摘要"), evidence.claim_summary || evidence.description_zh],
          [context.t("来源"), (evidence.source_kinds || []).join("、")],
          [context.t("位置"), (evidence.source_locations || []).join("、")],
          [context.t("来源 Job"), (evidence.job_refs || []).join("、") || "—"],
          [context.t("适用对象"), scopeDetail(evidence.applicable_objects)],
          [context.t("适用环境"), environmentDetail(evidence.applicable_environment)],
          [context.t("状态"), evidence.lifecycle_status],
          [context.t("登记时间"), FTUI.formatDate(evidence.created_at)],
        ]).shell);
      } else if (state.activeTab === "fragments") {
        if (!state.full) {
          const full = await context.api(
            `/api/research-evidence/${encodeURIComponent(evidenceRef)}`,
          );
          state.full = full.evidence || {};
        }
        const rows = (state.full.fragments || []).map(fragment => [
          fragment.title_zh || fragment.fragment_ref,
          fragment.source?.source_kind || "—",
          JSON.stringify(fragment.selector || {}),
          fragment.summary_zh || "—",
        ]);
        content.append(rows.length ? FTUI.pagedTable([
          context.t("摘选"), context.t("来源类型"), context.t("选择器"), context.t("说明"),
        ], rows, {pageSize: 20}).shell : FTUI.empty(
          context.t("暂无摘选"), context.t("该 Evidence 尚未登记 fragment"),
        ));
      } else {
        const relationshipValue = await context.api(
          `/api/research-evidence/catalog/${encodeURIComponent(evidenceRef)}/relationships`
          + `?page=${state.relationshipPage || 1}&page_size=${pageSize}`,
        );
        const relationships = relationshipValue.relationships || {};
        const items = relationships.items || [];
        if (!items.length) {
          content.append(FTUI.empty(
            context.t("暂无引用关系"),
            context.t("该 Evidence 尚未被研究报告引用"),
          ));
        } else {
          const table = FTUI.pagedTable([
            context.t("研究报告"), context.t("所属研究"), context.t("用途"),
            context.t("引用 Profile"), context.t("引用时间"),
          ], items.map(item => [
            item.report_title || item.report_id || "—",
            item.research_title || item.research_id,
            item.purpose || "—", item.profile_ref || "—",
            FTUI.formatDate(item.created_at),
          ]), {
            remote: true,
            page: relationships.page,
            pageSize: relationships.page_size,
            total: relationships.total,
            onPageChange: page => {
              state.relationshipPage = page;
              void detail(context, mount, evidenceRef);
            },
          });
          [...table.body.rows].forEach((row, index) => {
            const item = items[index];
            row.dataset.href = "true";
            row.addEventListener("click", () => context.navigate(
              `/researches/${encodeURIComponent(item.research_id)}`,
              {title: item.research_title || context.t("研究")},
            ));
          });
          content.append(table.shell);
        }
      }
      mount.replaceChildren(root);
    } catch (error) {
      mount.replaceChildren(FTUI.empty(context.t("无法读取证据"), error.message));
    }
  }

  function scopeSummary(value) {
    const parts = [];
    const labels = {factor_refs: "因子", product_refs: "产品", sample_refs: "样本"};
    Object.entries(labels).forEach(([field, label]) => {
      const items = value?.[field] || [];
      if (items.length) parts.push(`${label} ${items.length}`);
    });
    return parts.join(" · ") || "—";
  }

  function environmentSummary(value) {
    const parts = [];
    const labels = {
      product_group_refs: "产品组", data_source_refs: "数据源",
      environment_refs: "环境", source_refs: "来源范围",
    };
    Object.entries(labels).forEach(([field, label]) => {
      const items = value?.[field] || [];
      if (items.length) parts.push(`${label} ${items.length}`);
    });
    const window = value?.time_window;
    if (window?.start || window?.end) {
      parts.push(`${window.start || "…"}–${window.end || "…"}`);
    }
    return parts.join(" · ") || "—";
  }

  function scopeDetail(value) {
    return [
      ...(value?.factor_refs || []),
      ...(value?.product_refs || []),
      ...(value?.sample_refs || []),
    ].join("、") || "—";
  }

  function environmentDetail(value) {
    const refs = [
      ...(value?.product_group_refs || []),
      ...(value?.data_source_refs || []),
      ...(value?.environment_refs || []),
      ...(value?.source_refs || []),
    ];
    const window = value?.time_window;
    if (window?.start || window?.end) {
      refs.push(`${window.start || "…"}–${window.end || "…"}`);
    }
    return refs.join("、") || "—";
  }

  window.FTResearchEvidence = Object.freeze({render, detail});
})();
