(() => {
  function productID(value) {
    return String(
      value?.name || value?.code || value?.product_ref || value?.id || value || "",
    ).trim();
  }

  function productLabel(value) {
    return String(
      value?.display_name || value?.title_zh || value?.description
        || value?.name || value?.code || productID(value),
    ).trim();
  }

  function rowsFromState(state) {
    const result = [];
    for (const group of state?.groups || []) {
      for (const value of group?.products || group?.product_names || []) {
        const id = productID(value);
        if (id && !result.some(item => item.value === id)) {
          result.push({value: id, label: productLabel(value), description: id});
        }
      }
    }
    return result;
  }

  function normalizeRows(values) {
    const result = [];
    for (const value of values || []) {
      const id = productID(value);
      if (!id || result.some(item => item.value === id)) continue;
      result.push({value: id, label: productLabel(value), description: id});
    }
    return result;
  }

  function apiRows(payload) {
    return normalizeRows(payload?.products || payload?.items || []);
  }

  async function loadCandidates(context, state, selected) {
    const local = normalizeRows(state.productFilterCandidates || rowsFromState(state));
    if (local.length) return includeSelected(local, selected);
    try {
      const value = await context.api("/api/product-library/products");
      const remote = apiRows(value);
      if (remote.length) state.productFilterCandidates = remote;
      return includeSelected(remote, selected);
    } catch (_) {
      return includeSelected([], selected);
    }
  }

  function includeSelected(items, selected) {
    const result = [...items];
    for (const value of selected || []) {
      const id = String(value || "").trim();
      if (id && !result.some(item => item.value === id)) {
        result.push({value: id, label: id, description: "已保存筛选项"});
      }
    }
    return result;
  }

  function render(context, state, selected = [], onChange) {
    const root = document.createElement("section");
    root.className = "strategy-editor-product-filter";
    const note = document.createElement("small");
    note.textContent = context.t("可留空表示不限制；这里只筛选交易产品，不改变产品组或派生关系");
    const mount = document.createElement("div");
    mount.append(FTUI.loading(context.t("正在读取交易产品…")));
    root.append(note, mount);
    void loadCandidates(context, state, selected).then(items => {
      if (!mount.isConnected) return;
      const picker = FTTestObjectPicker.create(context, {
        title: context.t("交易产品"),
        items,
        selected: [...selected],
        multi: true,
        compact: true,
        name: `strategy-trading-products-${Date.now()}`,
        onChange,
      });
      mount.replaceChildren(FTTestFieldRow.create(
        context.t("交易产品"), picker.element,
      ));
    }).catch(error => {
      mount.replaceChildren(FTUI.empty(
        context.t("交易产品读取失败"), error.message || context.t("请稍后重试"),
      ));
    });
    return root;
  }

  window.FTStrategyEditorProductFilter = Object.freeze({render});
})();
