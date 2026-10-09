(() => {
  window.reportRouteHarness = {routes: [], sources: []};
  window.FTUI = {
    loading: label => Object.assign(document.createElement("p"), {textContent: label}),
    empty: (title, message) => Object.assign(document.createElement("p"), {
      textContent: `${title}: ${message}`,
    }),
    iconButton: (_context, _icon, label, action) => {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.label = label;
      button.textContent = label;
      button.addEventListener("click", action);
      return button;
    },
    reportBranchLabel: branch => branch.branch_ref,
    formatDate: value => String(value || ""),
  };
  window.FTResearchReportSettings = {applyReading() {}, open() {}};
  window.FTStaticLoader = {loadGroups: async () => {}};
  window.FTReportRenderer = {render: () => ({update: async () => {}})};
  window.FTReportSource = {
    create(publicationID, _api, options) {
      window.reportRouteHarness.sources.push({publicationID, options});
      return {
        isOwnerLocal: true,
        chapterLazy: false,
        componentLazy: false,
        localResourceIndex: new Map(),
        load: async () => ({
          title: "报告", report_id: "report-1", research_id: "research-1",
          access: {can_manage: false}, related_objects: [], attachments: [],
          local_resources: [],
        }),
        watch: () => () => {},
        setChapterMetadata() {},
        localResourcePath: () => "",
        reportAssetPath: () => "",
        assetID: value => value,
      };
    },
  };

  window.runReportRouteSourceHint = async () => {
    const mount = document.createElement("main");
    document.body.append(mount);
    const context = {
      api: async path => {
        if (path === "/api/research/research-1/reports") return {reports: [{
          report_id: "report-1",
          title: "报告",
          build_source: "client",
          source_ref: "stale-client-ref",
          owner_ref: "owner-1",
          branches: [{
            source_kind: "server_agent",
            branch_ref: "agent-work",
            publication_id: "agent-report-ref",
            selected: true,
          }],
        }]};
        throw new Error(`Unexpected API call: ${path}`);
      },
      t: value => value,
      tabSession: {},
      pageState: {register() {}},
      navigate: path => window.reportRouteHarness.routes.push(path),
      session: null,
      isRouteCurrent: () => true,
    };
    await window.FTResearchReports.renderForResearch(
      context, mount, "research-1",
    );
    mount.querySelector('button[data-label="在独立页面打开"]').click();
    const route = window.reportRouteHarness.routes[0];
    const query = new URLSearchParams(route.split("?")[1]);
    const source = window.reportRouteHarness.sources[0];
    mount.remove();
    return {
      route,
      sourceKind: query.get("report_source_kind"),
      reference: decodeURIComponent(route.split("/research/")[1].split("?")[0]),
      renderedSource: source.publicationID,
    };
  };
})();
