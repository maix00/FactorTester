(() => {
  async function render(context, helpers, targetID) {
    const source = helpers.sourceOf();
    context.activeNav("products");
    context.setHeading(context.t("数据源族"), context.t("产品目录"));
    helpers.catalogSwitch(context, "sources", source);
    context.content.replaceChildren(FTUI.loading(context.t("正在读取数据源族…")));
    let descriptors;
    try {
      descriptors = await window.FTProductSources.loadDescriptors(context, helpers);
    } catch (error) {
      if (!helpers.isCurrent(context)) return;
      context.content.replaceChildren(FTUI.empty(
        context.t("数据源族读取失败"), error.message || context.t("请稍后重试"),
      ));
      return;
    }
    if (!helpers.isCurrent(context)) return;
    const target = String(targetID || "");
    const entry = descriptors.find(([, item]) => familyID(item) === target)
      || descriptors.find(([, item]) => familyID(item).toLowerCase() === target.toLowerCase());
    const descriptor = entry?.[1];
    if (!descriptor) {
      throw new Error(context.t("数据源族不存在"));
    }
    const title = familyName(descriptor);
    context.setHeading(title, context.t("数据源族"));
    context.updateActiveTab?.({title});
    const root = document.createElement("div");
    root.className = "detail-stack product-source-family-detail-page";
    root.append(helpers.sourceSummary(context, source));
    root.append(backButton(context, helpers, source));
    root.append(familyOverview(context, descriptor));
    root.append(memberSection(context, descriptor));
    context.content.replaceChildren(root);
  }

  function backButton(context, helpers, source) {
    return FTUI.actionButton(context.t("返回数据源族"), () => {
      context.navigate(helpers.pathFor("/products/sources", source));
    }, {variant: "secondary"});
  }

  function familyOverview(context, descriptor) {
    const section = document.createElement("section");
    section.className = "product-source-family-overview";
    section.append(Object.assign(document.createElement("h2"), {
      textContent: context.t("数据源族信息"),
    }));
    const rows = [
      [context.t("数据源族"), familyName(descriptor)],
      [context.t("数据源族 ID"), familyID(descriptor)],
      [context.t("提供类型"), descriptor.provider_kind || "—"],
      [context.t("服务器提供"), descriptor.server_provided
        ? context.t("是") : context.t("否")],
      [context.t("访客访问"), descriptor.visitor_data_accessible === false
        ? context.t("仅显示，访客不可获取")
        : descriptor.visitor_data_accessible === true
          ? context.t("可获取") : "—"],
      [context.t("产品路径"), multilineText(descriptor.product_paths)],
      [context.t("产品类别"), multilineText((descriptor.categories || []).map(
        item => item.title_zh || item.title || item.id,
      ))],
      [context.t("数据形态"), multilineText((descriptor.data_modes || []).map(
        item => item.title_zh || item.id,
      ))],
      [context.t("可用性"), availabilityText(context, descriptor)],
    ];
    section.append(FTUI.table([context.t("字段"), context.t("值")], rows).shell);
    return section;
  }

  function memberSection(context, descriptor) {
    const section = document.createElement("section");
    section.className = "product-source-family-members";
    section.append(Object.assign(document.createElement("h2"), {
      textContent: `${context.t("数据源")}（${(descriptor.members || []).length}）`,
    }));
    const members = Array.isArray(descriptor.members) ? descriptor.members : [];
    if (!members.length) {
      section.append(FTUI.empty(context.t("暂无数据源"), context.t("该数据源族没有登记具体数据源")));
      return section;
    }
    const rows = members.map(member => [
      multilineText([member.label || member.id, member.id]),
      member.frequency || "—",
      member.timezone || "—",
      multilineText(member.data_modes?.map(item => item.title_zh || item.id)
        || [member.mode?.title_zh || member.mode?.id]),
      multilineText(member.product_paths),
      multilineText([
        `${context.t("目录产品数")}：${member.catalog_product_count ?? 0}`,
        `${context.t("已有数据产品数")}：${member.product_count ?? 0}`,
        `${context.t("状态")}：${availabilityStatus(context, member.availability?.status)}`,
      ]),
      multilineText([
        `${context.t("时间字段")}：${Object.keys(member.time_columns || {}).join(", ") || "—"}`,
        `${context.t("数据字段")}：${Object.keys(member.data_columns || {}).join(", ") || "—"}`,
      ]),
    ]);
    section.append(FTUI.table([
      context.t("数据源"), context.t("数据频率"), context.t("时区"),
      context.t("数据形态"), context.t("产品路径"), context.t("可用性"),
      context.t("字段"),
    ], rows).shell);
    return section;
  }

  function familyID(descriptor) {
    return String(
      descriptor?.family_id || descriptor?.bundle_id || descriptor?.id || "",
    ).trim();
  }

  function familyName(descriptor) {
    return String(
      descriptor?.family_name || descriptor?.bundle_name
        || descriptor?.source_name || descriptor?.id || "",
    ).trim() || "—";
  }

  function multilineText(values) {
    const items = (Array.isArray(values) ? values : [values])
      .map(value => String(value || "").trim()).filter(Boolean);
    return items.join("\n") || "—";
  }

  function availabilityText(context, descriptor) {
    const value = descriptor?.availability || {};
    return multilineText([
      `${context.t("状态")}：${availabilityStatus(context, value.status)}`,
      `${context.t("目录产品数")}：${descriptor?.catalog_product_count
        ?? value.product_count ?? 0}`,
      `${context.t("已有数据产品数")}：${value.product_count ?? 0}`,
    ]);
  }

  function availabilityStatus(context, status) {
    const labels = {
      ready: "可用", empty: "暂无数据", not_probed: "尚未探测",
      unavailable: "不可用", disabled: "已停用", error: "读取失败",
    };
    return context.t(labels[status] || "未知");
  }

  window.FTProductSourceFamilyDetail = Object.freeze({render});
})();
