(() => {
  async function list(context, helpers) {
    const {embeddedOf, sourceOf, pathFor, catalogSwitch, request,
      sourceSummary, isCurrent} = helpers;
    const current = sourceOf();
    context.activeNav("products");
    context.setHeading(context.t("数据源"), context.t("产品目录"));
    catalogSwitch(context, "sources", current);
    context.toolbar.append(context.button("↻", () => list(context, helpers), context.t("刷新")));
    context.content.replaceChildren(FTUI.loading(context.t("正在读取数据源…")));

    const origins = [{id: "server", endpoint: "/api/catalog/sources"}];
    // A browser cannot access the client filesystem. Local providers are
    // requested only by the embedded Swift presentation.
    if (embeddedOf()) origins.push({id: "local", endpoint: "/api/client/product_sources"});
    const settled = await Promise.allSettled(origins.map(async origin => ({
      origin,
      payload: await request(context, origin.endpoint),
    })));
    const rows = [];
    settled.forEach((result, index) => {
      const origin = origins[index];
      if (result.status === "fulfilled") {
        (result.value.payload.sources || []).forEach(descriptor => {
          rows.push([origin, descriptor]);
        });
      } else {
        rows.push([origin, {
          source_name: origin.id,
          bundle_name: "—",
          bundle_id: "—",
          server_provided: origin.id === "server",
          product_paths: [], categories: [], data_modes: [],
          availability: {status: "error", error: result.reason?.message || ""},
        }]);
      }
    });
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
        multilineCell([
          descriptor.bundle_name,
          ...(descriptor.members || []).map(member =>
            `${member.label || member.id} · ${member.frequency || "—"}`),
        ], "catalog-source-lines catalog-source-bundle"),
        descriptor.server_provided ? context.t("是") : context.t("否"),
        multilineCell(descriptor.product_paths, "catalog-source-lines catalog-source-paths"),
        multilineCell((descriptor.categories || []).map(category =>
          category.title_zh || category.title || category.id || "").filter(Boolean)),
        dataModesCell(context, descriptor.data_modes),
        availabilityCell(context, descriptor),
        frequencyCell(context, descriptor.availability),
      ]),
    );
    rows.forEach(([origin, descriptor], index) => {
      const row = table.body.rows[index];
      row.dataset.href = "true";
      row.addEventListener("click", () => context.navigate(pathFor(
        "/products", origin.id, descriptor.id && descriptor.id !== "—"
          ? [descriptor.id] : [],
      )));
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

  function availabilityCell(context, descriptor) {
    const value = descriptor?.availability || {};
    return multilineCell([
      `${context.t("状态")}：${value.status === "ready" ? context.t("可用") : context.t("暂无数据")}`,
      `${context.t("目录产品数")}：${
        descriptor?.catalog_product_count ?? value.product_count ?? 0
      }`,
      `${context.t("已有数据产品数")}：${value.product_count ?? 0}`,
    ], "catalog-source-lines catalog-source-availability");
  }

  function frequencyCell(context, availability) {
    const names = (availability?.frequency_names || []).map(value => String(value));
    return multilineCell(names.length ? names : [context.t("暂无频率")], "catalog-source-lines catalog-source-frequency");
  }

  window.FTProductSources = Object.freeze({list});
})();
