(() => {
  function modulePath(module) {
    return module.path || `/${module.id === "home" ? "" : module.id}`;
  }

  function moduleForPath(path, modules) {
    const pathname = String(path || "").split(/[?#]/, 1)[0];
    const id = pathname.split("/").filter(Boolean)[0] || "home";
    if (id === "researches") {
      return modules.find(item => item.id === "research")
        || {id: "research", title: "研究台", icon: "chart"};
    }
    return modules.find(item =>
      item.id === id || modulePath(item).split("/").filter(Boolean)[0] === id
    ) || {id, title: id, icon: ""};
  }

  function isPinnedPath(path) {
    const rawPath = String(path || "");
    const pathname = rawPath.split(/[?#]/, 1)[0];
    const parts = pathname.split("/").filter(Boolean);
    // Typed references are detail pages even though they share one top-level
    // route. They belong in closable tabs rather than the feature-entry area.
    if (parts[0] === "reference") {
      try {
        return !new URL(rawPath, "http://factortester.invalid")
          .searchParams.get("target");
      } catch (_) {
        return true;
      }
    }
    if (parts[0] === "products" && ["sources", "categories", "groups"].includes(parts[1])) {
      return parts.length === 2;
    }
    if (parts[0] === "factors" && ["families", "sets"].includes(parts[1])) {
      return parts.length === 2;
    }
    return parts.length <= 1
      && !["factor-series", "ic-test", "backtest"].includes(parts[0]);
  }

  function titleForPath(path, modules, t) {
    const parts = String(path || "").split(/[?#]/, 1)[0].split("/").filter(Boolean);
    const module = moduleForPath(path, modules);
    if (parts.length <= 1) return t(module.title_key || module.title);
    const labels = {
      research: "研究报告", researches: "研究", "research-graphs": "研究图", jobs: "测试", factors: "因子详情",
      evidence: "证据", products: "产品详情", profiles: "研究身份", strategies: "策略详情", "test-templates": "测试模板",
    };
    if (parts[0] === "products" && parts[1] === "categories") {
      return t("产品分类");
    }
    if (parts[0] === "products" && parts[1] === "sources") {
      return t("数据源族");
    }
    return t(labels[parts[0]] || module.title || parts[0]);
  }

  function tabIcon(path, modules) {
    return FTIcons.module(moduleForPath(path, modules));
  }

  function referenceDetails(raw) {
    if (!raw) return [];
    try {
      const value = JSON.parse(raw);
      if (!Array.isArray(value)) return [];
      return value.filter(item => item && typeof item.name === "string"
        && typeof item.value === "string").slice(0, 16);
    } catch (_) {
      return [];
    }
  }

  function serverSelector(search) {
    const serverID = new URLSearchParams(search).get("server_id") || "";
    return serverID ? {serverID} : {};
  }

  function restoredTestState(search) {
    const params = new URLSearchParams(search);
    const workspaceID = params.get("workspace_id") || "";
    const jobID = params.get("job_id") || "";
    if (!workspaceID) return {};
    return {
      workspaceID,
      restoredJob: jobID ? {
        jobID,
        runID: params.get("run_id") || "",
        runSpecHash: params.get("run_spec_hash") || "",
        phase: params.get("status") || "succeeded",
        port: Number(params.get("port") || 0),
        serverID: params.get("server_id") || "",
        groupID: params.get("group_id") || "",
      } : null,
    };
  }

  // Display-only fallback for a temporary Manager/API outage.  It mirrors the
  // stable public entries and the research child tabs, but never replaces the
  // server-side filtering performed by /api/modules when that endpoint works.
  const fallbackModuleDefinitions = [
    {id: "home", title: "主页", title_key: "主页", path: "/", requiresAuth: false, sidebarVisible: true, homeVisible: false, pinned: true},
    {
      id: "research", title: "研究台", title_key: "研究台",
      description_key: "查看各 Profile 的实时步骤、义务与报告",
      icon: "chart", sfSymbol: "chart.xyaxis.line",
      path: "/research?section=researches", requiresAuth: true,
      sidebarVisible: true, homeVisible: true, pinned: true,
      children: [
        {id: "research.evidence", title: "证据", title_key: "证据", path: "/research?section=evidence", requiresAuth: true},
        {id: "research.graph", title: "研究图", title_key: "研究图", path: "/research?section=graph", requiresAuth: true},
        {id: "research.profiles", title: "研究身份", title_key: "研究身份", path: "/research?section=profiles", requiresAuth: true},
        {id: "research.agent-models", title: "智能体模型", title_key: "智能体模型", path: "/research?section=agent-models", requiresAuth: true},
      ],
    },
    {id: "ic-test", title: "IC 测试", title_key: "IC 测试", description_key: "配置并运行因子 IC 测试", sfSymbol: "chart.xyaxis.line", path: "/ic-test", requiresAuth: false, sidebarVisible: false, homeVisible: false, pinned: false, tab_behavior: "new"},
    {id: "backtest", title: "回测", title_key: "回测", description_key: "配置并运行分组回测", sfSymbol: "chart.line.uptrend.xyaxis", path: "/backtest", requiresAuth: false, sidebarVisible: false, homeVisible: false, pinned: false, tab_behavior: "new"},
    {
      id: "jobs", title: "测试台", title_key: "测试台",
      description_key: "选择测试类型或查看测试任务", sfSymbol: "checklist",
      path: "/jobs?section=types", requiresAuth: false,
      sidebarVisible: true, homeVisible: true, pinned: true,
      children: [
        {
          id: "jobs.types", title: "测试类型", title_key: "测试类型",
          description_key: "选择要运行的测试类型", path: "/jobs?section=types",
          requiresAuth: false, sidebarVisible: false, homeVisible: false,
          pinned: false,
          children: [
            {id: "ic-test", title: "IC 测试", title_key: "IC 测试", description_key: "配置并运行因子 IC 测试", sfSymbol: "chart.xyaxis.line", path: "/ic-test", requiresAuth: false, sidebarVisible: false, homeVisible: false, pinned: false, tab_behavior: "new"},
            {id: "backtest", title: "回测", title_key: "回测", description_key: "配置并运行分组回测", sfSymbol: "chart.line.uptrend.xyaxis", path: "/backtest", requiresAuth: false, sidebarVisible: false, homeVisible: false, pinned: false, tab_behavior: "new"},
          ],
        },
        {
          id: "jobs.list", title: "测试任务", title_key: "测试任务",
          description_key: "查看测试任务、进度、结果与生成物",
          path: "/jobs?section=tasks", requiresAuth: false,
          sidebarVisible: false, homeVisible: false, pinned: false,
        },
      ],
    },
    {id: "factors", title: "因子库", title_key: "因子库", description_key: "浏览 canonical 与自定义因子", sfSymbol: "function", path: "/factors", requiresAuth: false, sidebarVisible: true, homeVisible: true, pinned: true},
    {id: "products", title: "产品库", title_key: "产品库", description_key: "查询产品、合约与市场资料", sfSymbol: "shippingbox", path: "/products", requiresAuth: false, sidebarVisible: true, homeVisible: true, pinned: true},
    {id: "strategies", title: "策略库", title_key: "策略库", description_key: "管理可复用策略、源码版本与共享范围", sfSymbol: "arrow.triangle.branch", path: "/strategies?scope=mine", requiresAuth: true, sidebarVisible: true, homeVisible: true, pinned: true},
    {id: "manager", title: "服务器管理", title_key: "服务器管理", description_key: "查看端口状态并控制本机服务", sfSymbol: "server.rack", path: "/manager", requiresAuth: true, roles: ["super_admin"], sidebarVisible: false, homeVisible: true, pinned: false, tab_behavior: "new"},
    {id: "mihomo", title: "Mihomo Dashboard", title_key: "Mihomo Dashboard", description_key: "打开官方 Mihomo Dashboard", sfSymbol: "network", path: "/mihomo", requiresAuth: true, roles: ["super_admin"], sidebarVisible: false, homeVisible: true, pinned: false, tab_behavior: "new"},
    {id: "sqlite_web", title: "数据库", title_key: "数据库", description_key: "浏览统一 SQLite 数据库", sfSymbol: "cylinder.split.1x2", path: "/sqlite-web/", requiresAuth: true, roles: ["super_admin"], sidebarVisible: false, homeVisible: true, pinned: false, tab_behavior: "new"},
    {id: "docs", title: "技术文档", title_key: "技术文档", description_key: "阅读 FactorTester 技术文档", sfSymbol: "book", path: "/docs", requiresAuth: false, sidebarVisible: false, homeVisible: true, pinned: false, tab_behavior: "new"},
    {id: "settings", title: "设置", title_key: "设置", path: "/settings/account", requiresAuth: false, sidebarVisible: false, homeVisible: false, pinned: true},
  ];

  function visibleFallbackModule(module, session) {
    const authenticated = Boolean(session);
    if (module.requiresAuth !== false && !authenticated) return null;
    if (Array.isArray(module.roles) && module.roles.length
        && !module.roles.includes(session?.role)) return null;
    const children = Array.isArray(module.children)
      ? module.children.map(child => visibleFallbackModule(child, session)).filter(Boolean)
      : undefined;
    return {...module, ...(children ? {children} : {})};
  }

  function fallbackModulesForSession(session) {
    return fallbackModuleDefinitions
      .map(module => visibleFallbackModule(module, session))
      .filter(Boolean);
  }

  // Keep URL classification separate from route rendering.  The shell owns
  // authentication and handlers; this seam only turns a path into a stable,
  // testable value so new modules do not grow another branch in app/coordinator.js.
  function matchRoute(pathname = location.pathname, search = location.search) {
    const parts = pathname.split("/").filter(Boolean);
    if (!parts.length) return {kind: "home"};
    if (parts[0] === "reference" && parts[1]) {
      return {kind: "public-reference", id: decodeURIComponent(parts.slice(1).join("/"))};
    }
    if (parts[0] === "reference") {
      const params = new URLSearchParams(search);
      return {
        kind: "reference",
        referenceKind: params.get("kind") || "reference",
        target: params.get("target") || "",
        label: params.get("label") || "",
        componentID: params.get("component_id") || "",
        detailFields: referenceDetails(params.get("details")),
      };
    }
    if (parts[0] === "research" && parts[1]) {
      return {kind: "report", id: parts.slice(1).join("/")};
    }
    if (parts[0] === "researches" && parts[1]) {
      return {kind: "research-detail", id: decodeURIComponent(parts.slice(1).join("/"))};
    }
    if (parts[0] === "evidence" && parts[1]) {
      return {kind: "evidence-detail", id: decodeURIComponent(parts.slice(1).join("/"))};
    }
    if (parts[0] === "research-graphs" && parts[1]) {
      return {kind: "research-graph", id: decodeURIComponent(parts.slice(1).join("/"))};
    }
    if (parts[0] === "research") return {kind: "research"};
    if (parts[0] === "strategies" && parts[1]) {
      const id = decodeURIComponent(parts.slice(1).join("/"));
      const params = new URLSearchParams(search);
      return {
        kind: "strategy",
        id: id === "new" ? "" : id,
        mode: params.get("mode") || (id === "new" ? "create" : "view"),
      };
    }
    if (parts[0] === "strategies") {
      const scope = new URLSearchParams(search).get("scope") || "mine";
      return {
        kind: "strategy-library",
        scope: ["mine", "subordinates", "shared"].includes(scope) ? scope : "mine",
      };
    }
    // A task URL may omit the worker port when it is only a storage/detail
    // reference.  Classify these suffix routes before the numbered-port
    // matcher so `/jobs/<id>/configuration` cannot become a Job whose port is
    // the numeric-looking part of its id.
    if (parts[0] === "jobs" && parts.length === 3 && parts[2] === "configuration") {
      return {
        kind: "job-configuration", port: 0,
        id: decodeURIComponent(parts[1]),
        ...serverSelector(search),
      };
    }
    if (parts[0] === "jobs" && parts.length >= 4 && parts[2] === "inputs") {
      return {
        kind: "job-input", port: 0,
        id: decodeURIComponent(parts[1]),
        inputName: decodeURIComponent(parts.slice(3).join("/")),
        ...serverSelector(search),
      };
    }
    if (parts[0] === "jobs" && parts.length === 4 && parts[3] === "configuration") {
      return {
        kind: "job-configuration", port: Number(parts[1]),
        id: decodeURIComponent(parts[2]),
        ...serverSelector(search),
      };
    }
    if (parts[0] === "jobs" && parts.length >= 5 && parts[3] === "inputs") {
      return {
        kind: "job-input", port: Number(parts[1]),
        id: decodeURIComponent(parts[2]),
        inputName: decodeURIComponent(parts.slice(4).join("/")),
        ...serverSelector(search),
      };
    }
    if (parts[0] === "jobs" && parts.length >= 3) {
      return {
        kind: "job", port: Number(parts[1]),
        id: decodeURIComponent(parts.slice(2).join("/")),
        ...serverSelector(search),
      };
    }
    if (parts[0] === "jobs" && parts[1]) {
      return {
        kind: "job", port: 0,
        id: decodeURIComponent(parts.slice(1).join("/")),
        ...serverSelector(search),
      };
    }
    if (parts[0] === "jobs") {
      const params = new URLSearchParams(search);
      const requestedSection = params.get("section");
      return {
        kind: "jobs",
        section: requestedSection === "tasks" || params.has("scope")
          ? "tasks" : "types",
      };
    }
    if (parts[0] === "docs") {
      return {kind: "docs", slug: decodeURIComponent(parts.slice(1).join("/"))};
    }
    if (parts[0] === "sqlite-web") return {kind: "remote-module", module: "sqlite-web"};
    if (parts[0] === "mihomo") return {kind: "mihomo"};
    if (parts[0] === "ic-test") return {kind: "ic-test", ...restoredTestState(search)};
    if (parts[0] === "backtest") return {kind: "backtest", ...restoredTestState(search)};
    if (parts[0] === "factor-series") {
      const params = new URLSearchParams(search);
      return {
        kind: "factor-series",
        factorRef: params.get("factor_ref") || "",
        groupRef: params.get("group_ref") || "",
      };
    }
    if (parts[0] === "test-templates" && parts[1]) {
      return {kind: "test-template", id: decodeURIComponent(parts.slice(1).join("/"))};
    }
    if (parts[0] === "factors" && parts[1] === "families") {
      const scope = new URLSearchParams(search).get("scope") || "public";
      return {
        kind: "factor-families",
        scope: ["public", "mine", "subordinates"].includes(scope)
          ? scope : "public",
      };
    }
    if (parts[0] === "factors" && parts[1] === "sets") {
      const scope = new URLSearchParams(search).get("scope") || "mine";
      return {kind: "factor-sets", scope: ["mine", "subordinates"].includes(scope) ? scope : "mine"};
    }
    if (parts[0] === "factors" && parts[1] === "family" && parts[2]) {
      const id = decodeURIComponent(parts.slice(2).join("/"));
      const params = new URLSearchParams(search);
      return {
        kind: "factor-family",
        id: id === "new" ? "" : id,
        mode: params.get("mode") || (id === "new" ? "create" : "view"),
        publicMode: params.get("visibility") === "public",
      };
    }
    if (parts[0] === "factors" && parts[1] === "factor" && parts[2]) {
      const id = decodeURIComponent(parts.slice(2).join("/"));
      const params = new URLSearchParams(search);
      const mode = params.get("mode")
        || (id === "new" ? "create" : "view");
      return {
        kind: "factor", id: id === "new" ? "" : id, mode,
        familyRef: params.get("family_ref") || "",
      };
    }
    if (parts[0] === "factors" && parts[1] === "set" && parts[2]) {
      const id = decodeURIComponent(parts.slice(2).join("/"));
      const mode = new URLSearchParams(search).get("mode")
        || (id === "new" ? "create" : "view");
      return {kind: "factor-set", id: id === "new" ? "" : id, mode};
    }
    if (parts[0] === "factors") {
      const scope = new URLSearchParams(search).get("scope") || "mine";
      return {kind: "factors", scope: ["mine", "subordinates"].includes(scope) ? scope : "mine"};
    }
    if (parts[0] === "products" && parts[1] === "group" && parts[2]) {
      return {kind: "product-group", id: decodeURIComponent(parts.slice(2).join("/"))};
    }
    if (parts[0] === "products" && parts[1] === "product" && parts[2]) {
      return {kind: "product", id: decodeURIComponent(parts.slice(2).join("/"))};
    }
    if (parts[0] === "products" && ["contract", "continuous-contract"].includes(parts[1]) && parts[2]) {
      return {kind: "product-reference", referenceKind: parts[1], id: decodeURIComponent(parts.slice(2).join("/"))};
    }
    if (parts[0] === "products" && parts[1] === "sources" && parts[2]) {
      return {
        kind: "product-source-family",
        id: decodeURIComponent(parts.slice(2).join("/")),
      };
    }
    if (parts[0] === "products" && parts[1] === "sources") return {kind: "product-sources"};
    if (parts[0] === "products" && parts[1] === "groups") return {kind: "product-groups"};
    if (parts[0] === "products" && parts[1] === "categories") {
      if (parts.length >= 3) {
        const id = parts.slice(2).join("/");
        const mode = new URLSearchParams(search).get("mode")
          || (id === "new" ? "create" : "view");
        return {
          kind: "product-category",
          id: id === "new" ? "" : decodeURIComponent(id),
          mode,
        };
      }
      return {kind: "product-categories"};
    }
    if (parts[0] === "products") return {kind: "products"};
    if (parts[0] === "profiles" && parts[1]) {
      return {kind: "profile", id: decodeURIComponent(parts.slice(1).join("/"))};
    }
    if (parts[0] === "profiles") return {kind: "profiles"};
    if (parts[0] === "settings") return {kind: "settings", section: parts[1] || "account"};
    if (parts[0] === "manager") {
      const section = new URLSearchParams(search).get("section") || "services";
      return {
        kind: "manager",
        section: ["services", "allowlist", "devices", "accounts"].includes(section)
          ? section : "services",
      };
    }
    return {kind: "unknown"};
  }

  window.FTNavigation = Object.freeze({
    fallbackModulesForSession,
    modulePath,
    moduleForPath,
    isPinnedPath,
    titleForPath,
    tabIcon,
    referenceDetails,
    matchRoute,
  });
})();
