(() => {
  async function list(context, helpers) {
    const {
      sourceOf, pathFor, catalogSwitch, sourceSummary, isCurrent,
      localCatalogAvailable,
    } = helpers;
    const current = sourceOf();
    context.activeNav("products");
    context.setHeading(context.t("数据源族"), context.t("产品目录"));
    catalogSwitch(context, "sources", current);
    const root = document.createElement("div");
    root.className = "detail-stack product-source-page";
    root.append(sourceSummary(context, current));
    const mount = document.createElement("div");
    mount.className = "product-source-results";
    root.append(mount);
    root.append(Object.assign(document.createElement("p"), {
      className: "catalog-source-note",
      textContent: localCatalogAvailable()
        ? context.t("选择数据源族后，产品与产品组页面会读取对应的数据包")
        : context.t("Web 端只能访问服务器提供的数据源"),
    }));
    context.content.replaceChildren(root);
    let refresh;
    let loadToken = 0;
    const isCurrentView = token => token === loadToken
      && isCurrent(context) !== false
      && root.isConnected !== false
      && mount.isConnected !== false;
    const loadIntoMount = async () => {
      const token = ++loadToken;
      mount.replaceChildren(FTUI.loading(context.t("正在读取数据源族…")));
      try {
        const rows = await loadDescriptors(context, helpers);
        if (!isCurrentView(token)) return;
        const table = FTUI.table(
          [context.t("数据源族"), context.t("数据能力"),
            context.t("数据覆盖"), context.t("操作")],
          rows.map(([, descriptor]) => [
            familyLink(context, helpers, descriptor),
            compactMembersCell(context, descriptor.members),
            compactCoverageCell(context, descriptor),
            sourceActionsCell(context, descriptor),
          ]),
        );
        rows.forEach(([origin, descriptor], index) => {
          const row = table.body.rows[index];
          row.dataset.href = "true";
          if (descriptor.visitor_data_accessible === false) {
            row.classList.add("is-unavailable");
            row.title = context.t("访客只能查看该数据源信息，不能获取数据");
          }
          row.addEventListener("click", () => context.navigate(pathFor(
            `/products/sources/${encodeURIComponent(familyID(descriptor))}`,
            origin.id,
          )));
        });
        mount.replaceChildren(table.shell);
      } catch (error) {
        if (!isCurrentView(token)) return;
        mount.replaceChildren(FTUI.empty(
          context.t("数据源族读取失败"), error.message || context.t("请稍后重试"),
        ));
      }
    };
    refresh = FTUI.refreshButton(context, loadIntoMount);
    context.toolbar.append(refresh);
    void loadIntoMount();
  }

  async function loadDescriptors(context, helpers) {
    const {localCatalogAvailable, request} = helpers;
    const origins = [{id: "server", endpoint: "/api/product-library/data-sources"}];
    // A browser cannot access the client filesystem. Local providers are
    // requested only by the embedded Swift presentation.
    if (localCatalogAvailable()) {
      origins.push({id: "local", endpoint: "/api/client/product_sources"});
    }
    const settled = await Promise.allSettled(origins.map(async origin => ({
      origin,
      payload: await request(context, origin.endpoint),
    })));
    const merged = new Map();
    settled.forEach((result, index) => {
      const origin = origins[index];
      if (result.status === "fulfilled") {
        (result.value.payload.sources || []).forEach(descriptor => {
          mergeSourceDescriptor(merged, origin, descriptor);
        });
      } else {
        mergeSourceDescriptor(merged, origin, {
          source_name: origin.id,
          family_name: origin.id,
          family_id: origin.id,
          bundle_name: "—",
          bundle_id: "—",
          server_provided: origin.id === "server",
          product_paths: [], categories: [], data_modes: [], members: [],
          availability: {status: "error", error: result.reason?.message || ""},
        });
      }
    });
    return [...merged.values()];
  }

  function mergeSourceDescriptor(target, origin, incoming) {
    const descriptor = incoming && typeof incoming === "object"
      ? incoming : {};
    const key = String(
      descriptor.family_id || descriptor.bundle_id || descriptor.source_name
        || descriptor.id || origin.id,
    ).trim().toLocaleLowerCase();
    const existing = target.get(key);
    if (!existing) {
      const value = {...descriptor};
      value.family_id = familyID(value) || origin.id;
      value.family_name = familyName(value) || origin.id;
      value.local_available = origin.id === "local";
      target.set(key, [origin, value]);
      return;
    }
    const [, value] = existing;
    value.local_available = value.local_available || origin.id === "local";
    value.server_provided = value.server_provided || Boolean(descriptor.server_provided);
    if (origin.id === "server") {
      // Prefer the server route when both views describe one bundle.  It keeps
      // product selection on the normal Manager API while local availability
      // remains visible in the same row.
      existing[0] = origin;
      value.id = descriptor.id || value.id;
      value.source_ref = descriptor.source_ref || value.source_ref;
    }
    value.bundle_name = value.bundle_name && value.bundle_name !== "—"
      ? value.bundle_name : descriptor.bundle_name;
    value.family_name = familyName(value) || familyName(descriptor);
    value.family_id = familyID(value) || familyID(descriptor);
    value.members = mergeMembers(value.members, descriptor.members);
    value.server_providers = mergeObjects(
      value.server_providers || [], descriptor.server_providers || [],
      item => `${item.server_id || ""}:${item.port || ""}`,
    );
    value.product_paths = mergeValues(value.product_paths, descriptor.product_paths);
    value.categories = mergeObjects(
      value.categories || [], descriptor.categories || [],
      item => String(item.id || item.title_zh || item.title || ""),
    );
    value.data_modes = mergeObjects(
      value.data_modes || [], descriptor.data_modes || [],
      item => String(item.id || item.frequency || item.title_zh || ""),
    );
    const oldAvailability = value.availability || {};
    const newAvailability = descriptor.availability || {};
    value.availability = {
      ...oldAvailability,
      status: oldAvailability.status === "ready" || newAvailability.status === "ready"
        ? "ready" : oldAvailability.status || newAvailability.status,
      product_count: Math.max(
        Number(oldAvailability.product_count || 0),
        Number(newAvailability.product_count || 0),
      ),
      frequency_names: mergeValues(
        oldAvailability.frequency_names, newAvailability.frequency_names,
      ),
    };
    value.catalog_product_count = Math.max(
      Number(value.catalog_product_count || 0),
      Number(descriptor.catalog_product_count || 0),
    );
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
    ).trim();
  }

  function mergeMembers(first, second) {
    const values = new Map();
    [...(Array.isArray(first) ? first : []), ...(Array.isArray(second) ? second : [])]
      .filter(item => item && typeof item === "object")
      .forEach(item => {
        const key = String(item.id || item.key || item.label || "").trim();
        if (!key) return;
        const existing = values.get(key);
        values.set(key, existing ? {...existing, ...item} : {...item});
      });
    return [...values.values()];
  }

  function mergeValues(first, second) {
    return [...new Set([...(Array.isArray(first) ? first : []),
      ...(Array.isArray(second) ? second : [])].map(value => String(value)))];
  }

  function mergeObjects(first, second, keyOf) {
    const result = new Map();
    [...(Array.isArray(first) ? first : []), ...(Array.isArray(second) ? second : [])]
      .forEach(value => result.set(keyOf(value), value));
    return [...result.values()];
  }

  function providersCell(context, descriptor) {
    const providers = Array.isArray(descriptor?.server_providers)
      ? descriptor.server_providers : [];
    const button = document.createElement("button");
    button.type = "button";
    button.className = "catalog-source-providers-button";
    const online = providers.filter(item => item?.online).length;
    button.textContent = providers.length
      ? `${online}/${providers.length}`
      : context.t("查看");
    button.title = context.t("查看提供此数据源的服务器");
    button.addEventListener("click", event => {
      event.stopPropagation();
      void openProvidersOverlay(context, descriptor);
    });
    return button;
  }

  function familyLink(context, helpers, descriptor) {
    const label = familyName(descriptor) || "—";
    const link = document.createElement("a");
    link.className = "catalog-source-family-link";
    link.textContent = label;
    const id = familyID(descriptor);
    if (!id || id === "—") return link;
    link.href = helpers.pathFor(
      `/products/sources/${encodeURIComponent(id)}`,
      helpers.sourceOf(),
    );
    link.addEventListener("click", event => {
      event.preventDefault();
      event.stopPropagation();
      context.navigate(link.href);
    });
    return link;
  }

  function compactMembersCell(context, members) {
    const values = Array.isArray(members) ? members : [];
    const frequencies = [...new Set(values
      .map(member => String(member.frequency || "").trim())
      .filter(Boolean))];
    return multilineCell(
      [
        `${values.length} ${context.t("个数据源")}`,
        frequencies.length ? frequencies.join(" · ") : context.t("未声明频率"),
      ],
      "catalog-source-lines catalog-source-members",
    );
  }

  function compactCoverageCell(context, descriptor) {
    const value = descriptor?.availability || {};
    const rawAvailable = value.product_count ?? descriptor?.product_count;
    const known = rawAvailable !== null && rawAvailable !== undefined
      && Number.isFinite(Number(rawAvailable));
    const available = known ? Number(rawAvailable) : null;
    const catalog = descriptor?.catalog_product_count ?? available;
    const visitor = descriptor.visitor_data_accessible === false
      ? context.t("访客只读") : "";
    return multilineCell([
      availabilityStatus(context, value.status),
      known
        ? `${context.t("有数据")} ${available} / ${catalog} ${context.t("个产品")}`
        : context.t("产品数量未报告"),
      visitor,
    ], "catalog-source-lines catalog-source-availability");
  }

  function sourceActionsCell(context, descriptor) {
    const actions = document.createElement("div");
    actions.className = "catalog-source-actions";
    actions.append(providersCell(context, descriptor));
    actions.append(sourceDetailsButton(context, descriptor));
    return actions;
  }

  function sourceDetailsButton(context, descriptor) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "catalog-source-providers-button";
    button.textContent = context.t("属性");
    button.title = context.t("查看数据源声明与 Nautilus 适配能力");
    button.addEventListener("click", async event => {
      event.preventDefault();
      event.stopPropagation();
      try {
        await window.FTStaticLoader?.loadGroups?.([
          "catalog-product-source-family", "object-overlay",
        ]);
        if (!window.FTProductSourceFamilyDetail?.openFamilyOverlay) {
          throw new Error(context.t("数据源详情组件不可用"));
        }
        await window.FTProductSourceFamilyDetail.openFamilyOverlay(context, descriptor);
      } catch (error) {
        context.showNotice?.(error.message || context.t("数据源详情读取失败"), true);
      }
    });
    return button;
  }

  async function openProvidersOverlay(context, descriptor) {
    try {
      if (!window.FTObjectOverlay?.open) {
        await window.FTStaticLoader?.loadGroups?.(["object-overlay"]);
      }
      if (!window.FTObjectOverlay?.open) throw new Error(context.t("公共详情面板不可用"));
      return window.FTObjectOverlay.open(context, {
        kind: "data_source_providers", ref: familyID(descriptor), mode: "view",
        initialValue: descriptor,
        draftKey: `data-source-providers:${familyID(descriptor)}`,
      });
    } catch (error) {
      context.showNotice?.(error.message || context.t("提供服务器读取失败"), true);
      return null;
    }
  }

  function providersOverlay(context, _ref, _mode, options = {}) {
    const descriptor = options.initialValue || {};
    const providers = Array.isArray(descriptor?.server_providers)
      ? descriptor.server_providers : [];
    const table = FTUI.table(
      [context.t("服务器"), context.t("状态"), context.t("端口"),
        context.t("分支"), context.t("频率"), context.t("产品数")],
      providers.length ? providers.map(provider => [
        multilineCell([
          provider.server_id || "—",
          provider.server_host || provider.server_endpoint || "—",
        ], "catalog-source-lines"),
        provider.online ? context.t("在线") : context.t("离线"),
        multilineCell((provider.ports || []).map(String)),
        provider.server_branch || "—",
        multilineCell(provider.frequencies || [context.t("未知")]),
        `${provider.available_product_count ?? 0}/${provider.catalog_product_count ?? 0}`,
      ]) : [[context.t("暂无服务器信息"), "—", "—", "—", "—", "—"]],
    );
    const root = document.createElement("div");
    root.className = "detail-stack catalog-source-providers-overlay";
    const title = document.createElement("h2");
    title.textContent = `${familyName(descriptor) || context.t("数据源族")} · ${context.t("提供服务器")}`;
    root.append(title, table.shell);
    context.content.replaceChildren(root);
    return root;
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

  function availabilityStatus(context, status) {
    const labels = {
      ready: "可用",
      empty: "暂无数据",
      not_probed: "尚未探测",
      unavailable: "不可用",
      error: "读取失败",
    };
    return context.t(labels[status] || "未知");
  }

  window.FTProductSources = Object.freeze({list, loadDescriptors, providersOverlay});
})();
