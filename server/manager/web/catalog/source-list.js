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
          [context.t("数据源族"), context.t("数据源"), context.t("服务器提供"),
            context.t("提供服务器"), context.t("访客访问"),
            context.t("产品路径"), context.t("产品类别"), context.t("数据形态"),
            context.t("可用性"), context.t("数据频率")],
          rows.map(([, descriptor]) => [
            familyLink(context, helpers, descriptor),
            membersCell(context, descriptor.members),
            descriptor.server_provided ? context.t("是") : context.t("否"),
            providersCell(context, descriptor),
            visitorAccessCell(context, descriptor),
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
      } finally {
        if (refresh && isCurrentView(token)) refresh.disabled = false;
      }
    };
    refresh = context.button("↻", () => {
      if (refresh.disabled) return;
      refresh.disabled = true;
      void loadIntoMount();
    }, context.t("刷新"));
    context.toolbar.append(refresh);
    void loadIntoMount();
  }

  async function loadDescriptors(context, helpers) {
    const {localCatalogAvailable, request} = helpers;
    const origins = [{id: "server", endpoint: "/api/catalog/sources"}];
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
      showProvidersOverlay(context, descriptor);
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

  function membersCell(context, members) {
    return multilineCell(
      (Array.isArray(members) ? members : []).map(member => {
        const label = member.label || member.id || context.t("未命名数据源");
        const frequency = member.frequency || context.t("暂无频率");
        return `${label} · ${frequency}`;
      }),
      "catalog-source-lines catalog-source-members",
    );
  }

  function visitorAccessCell(context, descriptor) {
    if (descriptor.visitor_data_accessible === true) {
      return context.t("可获取");
    }
    if (descriptor.visitor_data_accessible === false) {
      return context.t("仅显示，访客不可获取");
    }
    return "—";
  }

  function showProvidersOverlay(context, descriptor) {
    const dialog = document.createElement("dialog");
    dialog.dataset.ftTabID = context.tabID || "";
    dialog.className = "catalog-source-providers-dialog";
    const card = document.createElement("form");
    card.method = "dialog";
    card.className = "dialog-card wide catalog-source-providers-card";
    const close = document.createElement("button");
    close.type = "submit";
    close.className = "dialog-close";
    close.setAttribute("aria-label", context.t("关闭"));
    close.textContent = "×";
    const title = document.createElement("h2");
    title.textContent = `${familyName(descriptor) || context.t("数据源族")} · ${context.t("提供服务器")}`;
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
    card.append(close, title, table.shell);
    dialog.append(card);
    dialog.addEventListener("close", () => dialog.remove(), {once: true});
    document.body.append(dialog);
    dialog.showModal();
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
      `${context.t("状态")}：${availabilityStatus(context, value.status)}`,
      `${context.t("目录产品数")}：${
        descriptor?.catalog_product_count ?? value.product_count ?? 0
      }`,
      `${context.t("已有数据产品数")}：${value.product_count ?? 0}`,
    ], "catalog-source-lines catalog-source-availability");
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

  function frequencyCell(context, availability) {
    const names = (availability?.frequency_names || []).map(value => String(value));
    return multilineCell(names.length ? names : [context.t("暂无频率")], "catalog-source-lines catalog-source-frequency");
  }

  window.FTProductSources = Object.freeze({list, loadDescriptors});
})();
