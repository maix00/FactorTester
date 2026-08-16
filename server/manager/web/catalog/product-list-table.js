(() => {
  function catalogPath(path, source) {
    const [pathname, rawQuery = ""] = String(path).split("?", 2);
    const query = new URLSearchParams(rawQuery);
    if (source === "local") query.set("source", "local");
    const encoded = query.toString();
    return encoded ? `${pathname}?${encoded}` : pathname;
  }

  function pageLabel(context, page, totalPages) {
    return context.t("第 %lld / %lld 页")
      .replace("%lld", String(page))
      .replace("%lld", String(totalPages));
  }

  function paginationModel(total, page, limit) {
    const boundedLimit = Math.min(100, Math.max(1, Number(limit) || 25));
    const totalPages = Math.max(
      1, Math.ceil(Math.max(0, Number(total) || 0) / boundedLimit),
    );
    const boundedPage = Math.min(totalPages, Math.max(1, Number(page) || 1));
    return {
      page: boundedPage,
      limit: boundedLimit,
      total: Math.max(0, Number(total) || 0),
      totalPages,
      hasPrevious: boundedPage > 1,
      hasNext: boundedPage < totalPages,
    };
  }

  function productTable(context, nodes, source) {
    const values = Array.isArray(nodes) ? nodes : [];
    const rows = values.map(node => [
      node.product_name || node.title || "—",
      node.description || node.desc || "—",
      node.exchange || "—",
      node.product_code || node.code || "—",
      Array.isArray(node.source_ids) ? node.source_ids.join(", ") : "—",
      node.product_type === "contract" ? context.t("合约") : context.t("产品"),
    ]);
    const view = FTUI.table([
      context.t("名称"), context.t("产品描述"), context.t("交易所"),
      context.t("代码"), context.t("数据源"), context.t("类型"),
    ], rows);
    view.shell.classList.add("product-list-table-shell");
    view.table.className = "product-list-table";
    [...view.body.rows].forEach((row, index) => {
      const node = values[index];
      if (!node) return;
      row.dataset.href = "true";
      row.addEventListener("click", () => {
        const kind = node.product_type === "contract" ? "contract" : "product";
        const target = node.product_name || node.contract_uid || node.key || node.title;
        context.navigate(catalogPath(
          `/products/${kind}/${encodeURIComponent(target)}`, source,
        ));
      });
    });
    return view.shell;
  }

  function render(context, mount, node, options) {
    const browser = document.createElement("section");
    browser.className = "product-list-browser";
    const heading = document.createElement("div");
    heading.className = "product-list-heading";
    heading.append(Object.assign(document.createElement("h3"), {
      textContent: context.t("本级产品列表"),
    }));
    const toolbar = document.createElement("div");
    toolbar.className = "product-list-toolbar";
    const search = document.createElement("input");
    search.type = "search";
    search.className = "product-list-search";
    search.placeholder = context.t("搜索产品或代码");
    search.setAttribute("aria-label", context.t("搜索产品或代码"));
    const pageSize = document.createElement("select");
    pageSize.className = "product-list-page-size";
    pageSize.setAttribute("aria-label", context.t("每页行数"));
    [20, 50, 100].forEach(value => {
      const option = document.createElement("option");
      option.value = String(value);
      option.textContent = context.t("每页 %lld 行").replace("%lld", String(value));
      pageSize.append(option);
    });
    pageSize.value = "20";
    toolbar.append(search, pageSize);
    const tableMount = document.createElement("div");
    tableMount.className = "product-list-table-mount";
    const pagination = document.createElement("div");
    pagination.className = "product-list-pagination";
    browser.append(heading, toolbar, tableMount, pagination);
    mount.replaceChildren(browser);

    const state = {page: 1, limit: 20, query: "", sequence: 0};
    let searchTimer = null;
    const loadPage = async () => {
      const sequence = ++state.sequence;
      tableMount.replaceChildren(FTUI.loading(context.t("正在读取产品节点…")));
      try {
        const payload = await context.api(options.contractTreePath(
          node.key || "", {
            query: state.query, page: state.page, limit: state.limit,
          },
        ));
        if (sequence !== state.sequence) return;
        const model = paginationModel(payload.total, payload.page, payload.limit);
        state.page = model.page;
        state.limit = model.limit;
        tableMount.replaceChildren(productTable(
          context, payload.nodes || payload.products || [], options.source,
        ));
        pagination.replaceChildren();
        const previous = FTUI.actionButton(context.t("上一页"), () => {
          if (!model.hasPrevious) return;
          state.page = model.page - 1;
          loadPage();
        });
        previous.disabled = !model.hasPrevious;
        const next = FTUI.actionButton(context.t("下一页"), () => {
          if (!model.hasNext) return;
          state.page = model.page + 1;
          loadPage();
        });
        next.disabled = !model.hasNext;
        pagination.append(
          previous,
          Object.assign(document.createElement("span"), {
            className: "product-list-page-label",
            textContent: pageLabel(context, model.page, model.totalPages),
          }),
          next,
          Object.assign(document.createElement("span"), {
            className: "product-list-total",
            textContent: `${model.total} ${context.t("项")}`,
          }),
        );
      } catch (error) {
        if (sequence !== state.sequence) return;
        tableMount.replaceChildren(FTUI.empty(
          context.t("产品节点读取失败"), error.message || context.t("请稍后重试"),
        ));
        pagination.replaceChildren();
      }
    };
    search.addEventListener("input", () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        state.query = search.value.trim();
        state.page = 1;
        loadPage();
      }, 180);
    });
    pageSize.addEventListener("change", () => {
      state.limit = Number(pageSize.value) || 20;
      state.page = 1;
      loadPage();
    });
    loadPage();
  }

  window.FTProductListTable = {paginationModel, render};
})();
