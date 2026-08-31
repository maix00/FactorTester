(() => {
  const fallbackTypes = [
    {
      id: "ic-test", title: "IC 测试", title_key: "IC 测试",
      description_key: "配置并运行因子 IC 测试", icon: "IC",
      sfSymbol: "chart.xyaxis.line", path: "/ic-test",
      requiresAuth: true, tab_behavior: "new",
    },
    {
      id: "backtest", title: "回测", title_key: "回测",
      description_key: "配置并运行分组回测", icon: "BT",
      sfSymbol: "chart.line.uptrend.xyaxis", path: "/backtest",
      requiresAuth: true, tab_behavior: "new",
    },
  ];

  function definitions(context) {
    const jobs = (context.modules || []).find(item => item.id === "jobs");
    const typesTab = (jobs?.children || []).find(item => item.id === "jobs.types");
    const nested = (typesTab?.children || []).filter(item => item?.path);
    if (nested.length) return nested;
    const topLevel = (context.modules || []).filter(item =>
      ["ic-test", "backtest"].includes(item.id)
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
