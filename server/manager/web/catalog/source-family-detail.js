(() => {
  const capabilityRequests = new Map();

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
    section.className = "product-source-family-overview compact-source-overview";
    const description = document.createElement("p");
    description.className = "catalog-source-summary";
    description.textContent = multilineText([
      descriptor.provider_kind,
      `${(descriptor.members || []).length} ${context.t("个数据源")}`,
      `${(descriptor.availability?.frequency_names || []).length || (descriptor.data_modes || []).length} ${context.t("种数据频率")}`,
      `${descriptor.availability?.product_count ?? 0} ${context.t("个有数据产品")}`,
    ]);
    section.append(description);
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
      multilineText([
        member.dimensions?.data_kind || member.data_modes?.[0]?.data_kind,
        member.dimensions?.market_depth || member.data_modes?.[0]?.market_depth,
      ]),
      multilineText([
        `${context.t("可用数据产品")}：${member.product_count ?? 0}`,
        availabilityStatus(context, member.availability?.status),
      ]),
      sourceDetailsButton(context, descriptor, member),
    ]);
    section.append(FTUI.table([
      context.t("数据源"), context.t("频率"), context.t("数据类型 / 深度"),
      context.t("可用性"), context.t("Nautilus 属性"),
    ], rows).shell);
    return section;
  }

  function sourceDetailsButton(context, descriptor, member) {
    const button = FTUI.actionButton(context.t("查看属性"), () => {
      void openFamilyOverlay(context, descriptor, member.key || member.id);
    }, {variant: "secondary"});
    button.type = "button";
    button.classList?.add("catalog-source-detail-button");
    return button;
  }

  async function openFamilyOverlay(context, descriptor, focusMember = "") {
    const options = {
      kind: "data_source_family", ref: familyID(descriptor), mode: "view",
      initialValue: {...descriptor, focus_member_key: focusMember},
      draftKey: `data-source:${familyID(descriptor)}`,
    };
    try {
      if (!window.FTObjectOverlay?.open) {
        await window.FTStaticLoader?.loadGroups?.(["object-overlay"]);
      }
      if (!window.FTObjectOverlay?.open) throw new Error(context.t("公共详情面板不可用"));
      return window.FTObjectOverlay.open(context, options);
    } catch (error) {
      context.showNotice?.(error.message || context.t("数据源详情打开失败"), true);
      return null;
    }
  }

  async function familyOverlay(context, ref, _mode, options = {}) {
    const descriptor = options.initialValue || {};
    const root = document.createElement("div");
    root.className = "detail-stack data-source-capability-overlay";
    const summary = document.createElement("p");
    summary.className = "catalog-source-summary";
    summary.textContent = `${familyName(descriptor)} · ${familyID(descriptor)}`;
    root.append(summary);
    const familyRows = [
      [context.t("提供类型"), descriptor.provider_kind || "—"],
      [context.t("服务器提供"), descriptor.server_provided
        ? context.t("是") : context.t("否")],
      [context.t("访问权限"), descriptor.visitor_data_accessible === false
        ? context.t("访客只读")
        : descriptor.visitor_data_accessible === true
          ? context.t("可获取") : "—"],
      [context.t("产品类别"), multilineText((descriptor.categories || []).map(
        item => item.title_zh || item.title || item.id,
      ))],
      [context.t("产品路径"), multilineText(descriptor.product_paths)],
      [context.t("数据形态"), multilineText((descriptor.data_modes || []).map(
        item => item.title_zh || item.id,
      ))],
      [context.t("可用性"), availabilityText(context, descriptor)],
    ];
    root.append(FTUI.table([context.t("数据源信息"), context.t("值")], familyRows).shell);
    const capabilityMount = document.createElement("div");
    capabilityMount.className = "data-source-capability-mount";
    capabilityMount.append(FTUI.loading(context.t("正在读取 Nautilus 数据源能力…")));
    root.append(capabilityMount);
    context.content.replaceChildren(root);
    let capabilities = null;
    let capabilityError = "";
    try {
      capabilities = await loadNautilusCapabilities(context);
    } catch (error) {
      capabilityError = error.message || context.t("请稍后重试");
    }
    const marketData = capabilities?.market_data_sources;
    if (marketData?.available === false) capabilityError ||= marketData.reason || "";
    capabilityMount.replaceChildren(renderCapabilityMembers(
      context, descriptor, marketData?.members || [], capabilities, capabilityError,
    ));
    const focus = String(descriptor.focus_member_key || "");
    if (focus) {
      const target = [...(capabilityMount.querySelectorAll?.("[data-source-member]") || [])]
        .find(item => item.dataset.sourceMember === focus);
      target?.scrollIntoView?.({block: "nearest"});
    }
    context.content.append(root);
  }

  function renderCapabilityMembers(
    context, descriptor, capabilityRows, capabilities, capabilityError = "",
  ) {
    const members = Array.isArray(descriptor.members) ? descriptor.members : [];
    if (!members.length) {
      return FTUI.empty(context.t("暂无数据源成员"), context.t("该数据源族没有登记具体数据源"));
    }
    const byKey = new Map((Array.isArray(capabilityRows) ? capabilityRows : [])
      .map(item => [String(item.member_key || ""), item]));
    const root = document.createElement("div");
    root.className = "data-source-capability-list";
    if (capabilityError) {
      const note = document.createElement("p");
      note.className = "catalog-source-note";
      note.textContent = `${context.t("当前服务能力查询失败，以下优先显示来源快照")}: ${capabilityError}`;
      root.append(note);
    }
    const bookTypes = nativeBookTypes(capabilities);
    members.forEach(member => {
      const embeddedCapability = member.nautilus_capability;
      const capability = embeddedCapability && Object.keys(embeddedCapability).length
        ? embeddedCapability
        : byKey.get(String(member.id || member.key || ""));
      const dimensions = member.dimensions || member.data_modes?.[0] || {};
      const card = document.createElement("section");
      card.className = "data-source-capability-card";
      card.dataset.sourceMember = String(member.id || member.key || "");
      const title = document.createElement("h3");
      title.textContent = `${member.label || member.id || context.t("未命名数据源")} · ${member.frequency || "—"}`;
      card.append(title);
      const adapterStatus = capability?.adapter_available === true
        ? context.t("已通过适配器校验")
        : capability ? context.t("尚未接入 Nautilus")
          : context.t("暂无 Nautilus 能力快照");
      const rows = [
        [context.t("采样模式"), capability?.sampling_mode || dimensions.sampling_mode || "—"],
        [context.t("数据类型"), capability?.data_kind || dimensions.data_kind || "—"],
        [context.t("市场深度"), capability?.market_depth || dimensions.market_depth || "—"],
        [context.t("数据交付"), capability?.delivery_mode || dimensions.delivery_mode || "—"],
        [context.t("BookType 支持"), multilineText(capability?.supported_book_types)],
        [context.t("Nautilus 可配置 BookType"), multilineText(bookTypes)],
        [context.t("适配状态"), adapterStatus],
        [context.t("适配器"), capability?.adapter_id || "—"],
        [context.t("Instrument 范围"), capability?.instrument_scope || "—"],
        [context.t("时区"), capability?.timezone || member.timezone || "—"],
        [context.t("Bar 时间语义"), capability?.bar_time_semantics || "—"],
        [context.t("原始时间戳单位"), capability?.raw_timestamp_unit || "—"],
        [context.t("数据布局"), capability?.layout || "—"],
        [context.t("命名规则"), capability?.naming_scheme || member.naming_scheme || "—"],
        [context.t("时间字段映射"), keyValueLines(capability?.time_columns || member.time_columns)],
        [context.t("行情字段映射"), keyValueLines(capability?.data_columns || member.data_columns)],
        [context.t("可用性说明"), capability?.reason || capabilityError || "—"],
      ];
      card.append(FTUI.table([context.t("属性"), context.t("值")], rows).shell);
      root.append(card);
    });
    return root;
  }

  function nativeBookTypes(capabilities) {
    const field = capabilities?.simulated_venue_config?.fields?.find(
      item => item.path === "book_type",
    );
    return (field?.options || []).map(item => (
      typeof item === "object" ? item.value : item
    )).filter(Boolean);
  }

  function keyValueLines(values) {
    const entries = Object.entries(values || {});
    return multilineText(entries.map(([key, value]) => `${key} → ${value}`));
  }

  function loadNautilusCapabilities(context) {
    const endpoint = context.servicePath?.("/api/nautilus/capabilities")
      || "/api/nautilus/capabilities";
    let request = capabilityRequests.get(endpoint);
    if (!request) {
      request = Promise.resolve(context.api(endpoint)).catch(error => {
        capabilityRequests.delete(endpoint);
        throw error;
      });
      capabilityRequests.set(endpoint, request);
    }
    return request;
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

  window.FTProductSourceFamilyDetail = Object.freeze({
    render, familyOverlay, openFamilyOverlay,
  });
})();
