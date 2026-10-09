(() => {
  const sample = {bodyMountCount: 0};
  let resolveCatalog;
  const catalog = new Promise(resolve => { resolveCatalog = resolve; });
  window.__reportSourceFirstPaint = {sample, catalog, resolveCatalog};
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: {getItem: () => null, setItem: () => {}},
  });
  window.FTUI = {
    reportBranchLabel: branch => branch.label || branch.branch_ref,
    iconButton: (_context, _icon, label, action) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.addEventListener("click", action);
      return button;
    },
  };
  window.FTResearchReportSettings = {applyReading() {}};
  window.FTReportRenderer = {
    render(value, mount) {
      mount.innerHTML = `<p class="real-source-report-body">${value.title}</p>`;
      sample.bodyMountAt = performance.now();
      sample.bodyMountedBeforeCatalog = !Number.isFinite(sample.catalogResolvedAt);
      sample.bodyMountCount += 1;
      return {update: async () => {}};
    },
  };

  window.startReportEntryWithRealSource = () => {
    const content = document.createElement("main");
    const toolbar = document.createElement("header");
    document.body.append(content, toolbar);
    const session = {durable: {}};
    const context = {
      state: {referenceSnapshots: new Map()},
      session: null,
      content,
      toolbar,
      t: value => value,
      api: path => {
        if (path === "/api/research/research-1/reports") {
          sample.catalogStartedAt ??= performance.now();
          return catalog.then(value => {
            sample.catalogResolvedAt = performance.now();
            return value;
          });
        }
        if (path === "/api/public-research/research%3Av1%3Apublished-report/index") {
          sample.indexStartedAt = performance.now();
          return Promise.resolve({
            title: "报告首屏",
            publication_id: "research:v1:published-report",
            report_id: "report-1",
            research_id: "research-1",
            branches: [{
              publication_id: "research:v1:published-report",
              branch_ref: "main",
              label: "main",
              selected: true,
            }],
            assets: [], local_resources: [], related_objects: [], attachments: [],
            access: {can_manage: false},
          });
        }
        throw new Error(`Unexpected request: ${path}`);
      },
      tabSession: () => session,
      pageState: {register() {}},
      activeNav() {},
      setHeading() {},
      updateActiveTab() {},
      saveActiveTabSession() {},
      captureScrollPosition() {},
      isRouteCurrent: () => true,
    };
    const startedAt = performance.now();
    window.__reportSourceFirstPaint.rendering = window.FTReportEntry.render(
      "research:v1:published-report", context,
    );
    sample.startedAt = startedAt;
    setTimeout(() => resolveCatalog({reports: [{
      report_id: "report-1",
      branches: [{
        publication_id: "research:v1:published-report",
        branch_ref: "main",
        label: "main",
        selected: true,
      }],
    }]}), 250);
    return sample;
  };
})();
