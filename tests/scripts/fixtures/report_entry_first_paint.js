(() => {
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: {getItem: () => null, setItem: () => {}},
  });

  const samples = [];
  const contexts = [];
  window.__reportEntryHarness = {samples, contexts};
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
  window.FTResearchReportSettings = {applyReading: () => {}};
  window.FTReportRenderer = {
    render(value, mount) {
      const started = window.__reportEntryHarness.activeSample;
      mount.innerHTML = `<p class="report-test-body">${value.title}</p>`;
      started.bodyMountAt = performance.now();
      started.bodyMountCount = (started.bodyMountCount || 0) + 1;
      return {update: () => {}};
    },
  };
  window.FTReportSource = {
    create(publicationID, api) {
      const value = {
        title: `Report ${publicationID}`,
        publication_id: publicationID,
        report_id: "report-1",
        research_id: "research-1",
        branches: [{
          publication_id: publicationID,
          branch_ref: "main",
          label: "main",
          selected: true,
        }],
        access: {can_manage: false},
        related_objects: [],
        attachments: [],
        local_resources: [],
      };
      return {
        publicationID,
        value,
        isOwnerLocal: false,
        chapterLazy: false,
        componentLazy: false,
        localResourceIndex: new Map(),
        async load() { return value; },
        watch() { return () => {}; },
        loadChapter: async () => ({}),
        loadComponent: async () => ({}),
        setChapterMetadata() {},
        assetID: ref => ref,
      };
    },
  };

  function makeContext(sample, isCurrent = () => true) {
    let resolveCatalog;
    const catalog = new Promise(resolve => {
      resolveCatalog = () => resolve({reports: [{
        report_id: "report-1",
        branches: [
          {
            publication_id: sample.publicationID,
            branch_ref: "main",
            label: "main",
            selected: true,
          },
          {
            publication_id: "publication-sibling",
            branch_ref: "agent-work",
            label: "agent-work",
          },
        ],
      }]});
      setTimeout(resolveCatalog, 250);
    });
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
          sample.catalogStartedAt = performance.now();
          return catalog.then(value => {
            sample.catalogResolvedAt = performance.now();
            return value;
          });
        }
        return Promise.reject(new Error(`Unexpected request: ${path}`));
      },
      tabSession: () => session,
      pageState: {register() {}},
      activeNav() {},
      setHeading() {},
      updateActiveTab() {},
      saveActiveTabSession() {},
      captureScrollPosition() {},
      isRouteCurrent: isCurrent,
    };
    contexts.push({context, content, toolbar, session});
    return {
      context,
      content,
      toolbar,
      resolveCatalog,
      catalog,
    };
  }

  window.runReportEntryFirstPaint = async () => {
    const delays = [];
    for (let index = 0; index < 5; index += 1) {
      const publicationID = `publication-${index}`;
      const sample = {publicationID, bodyMountCount: 0};
      window.__reportEntryHarness.activeSample = sample;
      const mounted = makeContext(sample);
      const startedAt = performance.now();
      const rendering = window.FTReportEntry.render(publicationID, mounted.context);
      await rendering;
      sample.renderReturnAt = performance.now();
      sample.initialBranchOptions = mounted.toolbar.querySelectorAll(
        ".branch-picker option",
      ).length;
      sample.bodyBeforeCatalog = Boolean(
        mounted.content.querySelector(".report-test-body"),
      ) && !Number.isFinite(sample.catalogResolvedAt);
      await mounted.catalog;
      await new Promise(resolve => setTimeout(resolve, 0));
      sample.finalBranchOptions = mounted.toolbar.querySelectorAll(
        ".branch-picker option",
      ).length;
      sample.elapsedToBodyMs = sample.bodyMountAt - startedAt;
      sample.elapsedToCatalogMs = sample.catalogResolvedAt - sample.catalogStartedAt;
      delays.push(sample);
      mounted.content.remove();
      mounted.toolbar.remove();
    }

    let routeCurrent = true;
    const stale = {publicationID: "publication-stale", bodyMountCount: 0};
    window.__reportEntryHarness.activeSample = stale;
    const staleContext = makeContext(stale, () => routeCurrent);
    const rendering = window.FTReportEntry.render(stale.publicationID, staleContext.context);
    await rendering;
    routeCurrent = false;
    await staleContext.catalog;
    await new Promise(resolve => setTimeout(resolve, 0));
    stale.finalBranchOptions = staleContext.toolbar.querySelectorAll(
      ".branch-picker option",
    ).length;
    stale.bodyMountCount = window.__reportEntryHarness.activeSample.bodyMountCount;
    staleContext.content.remove();
    staleContext.toolbar.remove();
    return {samples: delays, stale};
  };
})();
