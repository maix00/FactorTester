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

  window.FTNavigation = Object.freeze({
    modulePath,
    moduleForPath,
    isPinnedPath,
    titleForPath,
    tabIcon,
  });
})();
