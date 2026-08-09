(() => {
  function modulePath(module) {
    return module.path || `/${module.id === "home" ? "" : module.id}`;
  }

  function moduleForPath(path, modules) {
    const id = path.split("/").filter(Boolean)[0] || "home";
    return modules.find(item =>
      item.id === id || modulePath(item).split("/").filter(Boolean)[0] === id
    ) || {id, title: id, icon: ""};
  }

  function isPinnedPath(path) {
    const parts = path.split("/").filter(Boolean);
    return parts.length <= 1 && !["ic-test", "backtest"].includes(parts[0]);
  }

  function titleForPath(path, modules, t) {
    const parts = path.split("/").filter(Boolean);
    const module = moduleForPath(path, modules);
    if (parts.length <= 1) return t(module.title_key || module.title);
    const labels = {
      research: "研究报告", jobs: "测试任务", factors: "因子详情",
      products: "产品详情", profiles: "Profile", "test-templates": "测试模板",
    };
    return t(labels[parts[0]] || module.title || parts[0]);
  }

  function tabIcon(path, modules) {
    return FTIcons.module(moduleForPath(path, modules));
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
      };
    }
    if (parts[0] === "research" && parts[1]) {
      return {kind: "report", id: parts.slice(1).join("/")};
    }
    if (parts[0] === "research") return {kind: "research"};
    if (parts[0] === "jobs" && parts.length >= 3) {
      return {kind: "job", port: Number(parts[1]), id: decodeURIComponent(parts.slice(2).join("/"))};
    }
    if (parts[0] === "jobs" && parts[1]) {
      return {kind: "job", port: 0, id: decodeURIComponent(parts.slice(1).join("/"))};
    }
    if (parts[0] === "jobs") return {kind: "jobs"};
    if (parts[0] === "docs") return {kind: "remote-module", module: "docs"};
    if (parts[0] === "sqlite-web") return {kind: "remote-module", module: "sqlite-web"};
    if (parts[0] === "ic-test") return {kind: "ic-test"};
    if (parts[0] === "backtest") return {kind: "backtest"};
    if (parts[0] === "test-templates" && parts[1]) {
      return {kind: "test-template", id: decodeURIComponent(parts.slice(1).join("/"))};
    }
    if (parts[0] === "factors" && parts[1] === "families") return {kind: "factor-families"};
    if (parts[0] === "factors" && parts[1] === "family" && parts[2]) {
      return {kind: "factor-family", id: decodeURIComponent(parts.slice(2).join("/"))};
    }
    if (parts[0] === "factors" && parts[1] === "factor" && parts[2]) {
      return {kind: "factor", id: decodeURIComponent(parts.slice(2).join("/"))};
    }
    if (parts[0] === "factors" && parts[1] === "set" && parts[2]) {
      return {kind: "factor-set", id: decodeURIComponent(parts.slice(2).join("/"))};
    }
    if (parts[0] === "factors") return {kind: "factors"};
    if (parts[0] === "products" && parts[1] === "group" && parts[2]) {
      return {kind: "product-group", id: decodeURIComponent(parts.slice(2).join("/"))};
    }
    if (parts[0] === "products" && parts[1] === "product" && parts[2]) {
      return {kind: "product", id: decodeURIComponent(parts.slice(2).join("/"))};
    }
    if (parts[0] === "products" && ["contract", "continuous-contract"].includes(parts[1]) && parts[2]) {
      return {kind: "product-reference", referenceKind: parts[1], id: decodeURIComponent(parts.slice(2).join("/"))};
    }
    if (parts[0] === "products" && parts[1] === "sources") return {kind: "product-sources"};
    if (parts[0] === "products" && parts[1] === "groups") return {kind: "product-groups"};
    if (parts[0] === "products") return {kind: "products"};
    if (parts[0] === "profiles" && parts[1]) {
      return {kind: "profile", id: decodeURIComponent(parts.slice(1).join("/"))};
    }
    if (parts[0] === "profiles") return {kind: "profiles"};
    if (parts[0] === "settings") return {kind: "settings", section: parts[1] || "account"};
    if (parts[0] === "manager") return {kind: "manager"};
    return {kind: "unknown"};
  }

  window.FTNavigation = Object.freeze({
    modulePath,
    moduleForPath,
    isPinnedPath,
    titleForPath,
    tabIcon,
    matchRoute,
  });
})();
