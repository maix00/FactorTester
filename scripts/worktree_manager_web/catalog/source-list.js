(() => {
  async function list(context, helpers) {
    const {embeddedOf, sourceOf, pathFor, catalogSwitch, request,
      loadCategories, sourceSummary, isCurrent} = helpers;
    const current = sourceOf();
    context.activeNav("products");
    context.setHeading(context.t("数据源"), context.t("产品目录"));
    catalogSwitch(context, "sources", current);
    context.toolbar.append(context.button("↻", () => list(context, helpers), context.t("刷新")));
    context.content.replaceChildren(FTUI.loading(context.t("正在读取数据源…")));

    const sources = [{
      id: "server", title: context.t("服务器产品数据包"),
      bundle: context.t("Manager 提供的产品、合约与行情目录"),
      description: context.t("适用于 Web 与 Swift 客户端的共享数据源"),
    }];
    // A browser cannot access the client filesystem. The local row is only
    // meaningful inside the Swift embedded presentation.
    if (embeddedOf()) sources.unshift({
      id: "local", title: context.t("本地客户端产品数据包"),
      bundle: context.t("安装在本机并绑定当前账户的产品目录"),
      description: context.t("只在 Swift 客户端中可用"),
    });
    const rows = await Promise.all(sources.map(async item => {
      let descriptor = {
        source_name: item.title,
        bundle_name: item.bundle,
        bundle_id: "—",
        server_provided: item.id === "server",
        product_paths: [], categories: [], data_modes: [], availability: {},
      };
      try {
        const payload = await loadCategories(context, item.id);
        descriptor = (payload.sources || []).find(value => value.id === item.id) || descriptor;
      } catch (error) {
        descriptor.availability = {status: "error", error: error.message || ""};
      }
      return [item, descriptor];
    }));
    if (!isCurrent(context)) return;
    const root = document.createElement("div");
    root.className = "detail-stack product-source-page";
    root.append(sourceSummary(context, current));
    const table = FTUI.table(
      [context.t("数据源名称"), context.t("Bundle"), context.t("服务器提供"),
        context.t("产品路径"), context.t("产品类别"), context.t("数据形态"),
        context.t("可用性"), context.t("数据频率")],
      rows.map(([, descriptor]) => [
        descriptor.source_name || "—",
        multilineCell([descriptor.bundle_name, descriptor.bundle_id], "catalog-source-lines catalog-source-bundle"),
        descriptor.server_provided ? context.t("是") : context.t("否"),
        multilineCell(descriptor.product_paths, "catalog-source-lines catalog-source-paths"),
        multilineCell((descriptor.categories || []).map(category =>
          category.title_zh || category.title || category.id || "").filter(Boolean)),
        dataModesCell(context, descriptor.data_modes),
        availabilityCell(context, descriptor.availability),
        frequencyCell(context, descriptor.availability),
      ]),
    );
    rows.forEach(([item], index) => {
      const row = table.body.rows[index];
      row.dataset.href = "true";
      row.addEventListener("click", () => context.navigate(pathFor("/products", item.id)));
    });
    root.append(table.shell);
    root.append(Object.assign(document.createElement("p"), {
      className: "catalog-source-note",
      textContent: embeddedOf()
        ? context.t("选择数据源后，产品与产品组页面会读取对应的数据包")
        : context.t("Web 端只能访问服务器提供的数据源"),
    }));
    context.content.replaceChildren(root);
  }

  function multilineCell(values, className = "catalog-source-lines") {
    const cell = document.createElement("div");
    cell.className = className;
    const items = Array.isArray(values) ? values : [values];
    items.map(value => String(value || "").trim()).filter(Boolean).forEach(value => {
      cell.append(Object.assign(document.createElement("div"), {textContent: value}));
    });
    if (!cell.childElementCount) cell.textContent = "—";
    return cell;
  }

  function dataModesCell(context, modes) {
    const values = (Array.isArray(modes) ? modes : []).map(item => {
      const title = item?.title_zh || item?.id || "";
      return title ? `${title}：${item?.available ? context.t("已提供") : context.t("未提供")}` : "";
    });
    return multilineCell(values, "catalog-source-lines catalog-source-modes");
  }

  function availabilityCell(context, availability) {
    const value = availability || {};
    return multilineCell([
      `${context.t("状态")}：${value.status === "ready" ? context.t("可用") : context.t("暂无数据")}`,
      `${context.t("产品数")}：${value.product_count ?? 0}`,
    ], "catalog-source-lines catalog-source-availability");
  }

  function frequencyCell(context, availability) {
    const names = (availability?.frequency_names || []).map(value => String(value));
    return multilineCell(names.length ? names : [context.t("暂无频率")], "catalog-source-lines catalog-source-frequency");
  }

  window.FTProductSources = Object.freeze({list});
})();
