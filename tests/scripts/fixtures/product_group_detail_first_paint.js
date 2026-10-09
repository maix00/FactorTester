window.startProductGroupDetailFirstPaint = async function() {
  window.__productGroupFirstPaint = {
    categoriesStarted: false,
    pathEditorRenders: 0,
    save: null,
    resolveCategories: null,
    rejectCategories: null,
    routeCurrent: true,
    writeCalls: 0,
    groupReadStarted: false,
    groupResolved: false,
    resolveGroup: null,
  };
  window.__productGroupCategories = new Promise((resolve, reject) => {
    window.__productGroupFirstPaint.resolveCategories = resolve;
    window.__productGroupFirstPaint.rejectCategories = reject;
  });
  window.__productGroupGroup = new Promise(resolve => {
    window.__productGroupFirstPaint.resolveGroup = resolve;
  });

  window.FTUI = {
    loading(label) {
      const node = document.createElement("div");
      node.className = "test-loading";
      node.textContent = label;
      return node;
    },
    empty(title, detail) {
      const node = document.createElement("div");
      node.className = "test-empty";
      node.textContent = [title, detail].filter(Boolean).join(" ");
      return node;
    },
    table(_headers, rows) {
      const shell = document.createElement("table");
      const body = shell.createTBody();
      for (const row of rows) {
        const tr = body.insertRow();
        for (const value of row) tr.insertCell().textContent = value;
      }
      return {shell};
    },
  };
  window.FTMultiSelectFilter = {
    create(_context, options) {
      const element = document.createElement("select");
      element.className = "test-category-picker";
      for (const item of options.items) {
        const option = document.createElement("option");
        option.value = item.value;
        option.textContent = item.label;
        element.append(option);
      }
      return {element};
    },
  };
  window.FTObjectModeActions = {
    mount() {
      const save = document.createElement("button");
      save.textContent = "保存";
      window.__productGroupFirstPaint.save = save;
      return [save];
    },
  };
  window.FTCatalogDetailUI = {
    header(_context, options) {
      const root = document.createElement("header");
      root.textContent = options.title;
      return {root, save: null};
    },
    action(_context, label) {
      const button = document.createElement("button");
      button.textContent = label;
      return button;
    },
  };
  window.FTProductGroupPathEditor = {
    render() {
      window.__productGroupFirstPaint.pathEditorRenders += 1;
      const root = document.createElement("div");
      root.className = "test-path-editor";
      return {
        root,
        paths: () => ["AP.CZC"],
        dispose() {},
      };
    },
  };

  const content = document.querySelector("main");
  const context = {
    content,
    session: {username: "test"},
    tabID: "product-group-1",
    t: value => value,
    activeNav() {},
    setHeading() {},
    updateActiveTab() {},
    closeTab() {},
    navigate() {},
    api: async (_url, options = {}) => {
      if (options.method === "POST" || options.method === "PUT") {
        window.__productGroupFirstPaint.writeCalls += 1;
        return {};
      }
      window.__productGroupFirstPaint.groupReadStarted = true;
      return window.__productGroupGroup;
    },
    groupValue: {
        id: "group-1",
        group_ref: "group-1",
        name: "快速显示的产品组",
        category_ids: ["category-1"],
        category_bindings: [{id: "category-1"}],
        selection_paths: ["AP.CZC"],
        products: [{display_name: "产品一", available: true}],
    },
    showNotice() {},
    testObjectOverlay: false,
    testObjectViewOnly: false,
    isCurrent: () => window.__productGroupFirstPaint.routeCurrent,
    toolbar: document.querySelector("header"),
    testState: {values: {category_candidates: [{
      id: "temporary-category", title_zh: "临时分类",
    }]}},
  };
  const helpers = {
    sourceOf: () => "server",
    catalogSwitch() {},
    sourceSummary: () => document.createElement("p"),
    pathFor: value => value,
    loadCategories: () => {
      window.__productGroupFirstPaint.categoriesStarted = true;
      return window.__productGroupCategories;
    },
  };
  const rendering = FTProductGroupDetail.render(context, "group-1", helpers, "edit");
  await Promise.resolve();
  const categoriesStartedBeforeGroup = window.__productGroupFirstPaint.categoriesStarted
    && !window.__productGroupFirstPaint.groupResolved;
  const bodyWaitedForGroup = !content.querySelector(".product-group-detail-page");
  window.__productGroupFirstPaint.resolveGroup({group: context.groupValue});
  window.__productGroupFirstPaint.groupResolved = true;
  await rendering;
  return {
    categoriesStarted: window.__productGroupFirstPaint.categoriesStarted,
    categoriesStartedBeforeGroup,
    bodyWaitedForGroup,
    bodyMounted: Boolean(content.querySelector(".product-group-detail-page")),
    productVisible: content.textContent.includes("产品一"),
    categoryLoadingVisible: content.textContent.includes("正在读取产品分类…"),
    pathEditorRenders: window.__productGroupFirstPaint.pathEditorRenders,
    saveDisabled: window.__productGroupFirstPaint.save.disabled,
    writeCalls: window.__productGroupFirstPaint.writeCalls,
  };
};
