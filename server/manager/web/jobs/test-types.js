(() => {
  const fallbackTypes = Object.values(window.FTTestTypeRegistry.definitions).map(item => ({
    id: item.pageID, title: item.title, title_key: item.title,
    description_key: item.description, icon: item.icon,
    sfSymbol: item.sfSymbol, path: item.route,
    requiresAuth: item.requiresAuth, tab_behavior: "new",
  }));

  function definitions(context) {
    const jobs = (context.modules || []).find(item => item.id === "jobs");
    const typesTab = (jobs?.children || []).find(item => item.id === "jobs.types");
    const nested = (typesTab?.children || []).filter(item => item?.path);
    if (nested.length) return nested;
    const topLevel = (context.modules || []).filter(item =>
      ["factor-series", "ic-test", "backtest"].includes(item.id)
    );
    return topLevel.length ? topLevel : fallbackTypes;
  }

  function render(context) {
    context.activeNav("jobs");
    context.setHeading(context.t("测试台"));
    context.toolbar.replaceChildren(FTTestPageTabs.render(context, "types"));

    const root = document.createElement("div");
    root.className = "test-types-page";
    const heading = document.createElement("div");
    heading.className = "section-heading";
    const title = document.createElement("h2");
    title.textContent = context.t("测试类型");
    const description = document.createElement("p");
    description.textContent = context.t("选择要运行的测试类型");
    heading.append(title, description);

    const cards = document.createElement("div");
    cards.className = "card-grid";
    definitions(context).forEach(module => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "card";
      card.innerHTML = '<span class="symbol"></span><b></b><small></small>';
      card.querySelector(".symbol").append(FTIcons.node(FTIcons.module(module)));
      card.querySelector("b").textContent = context.t(module.title_key || module.title);
      card.querySelector("small").textContent = context.t(
        module.description_key || module.desc || ""
      );
      card.addEventListener("click", () => context.navigate(module.path));
      cards.append(card);
    });
    root.append(heading, cards);
    context.content.replaceChildren(root);
  }

  window.FTTestTypes = Object.freeze({render});
})();
