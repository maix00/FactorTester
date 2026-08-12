(() => {
  function categoryID(value) {
    return value?.name || value?.id || value?.label || "";
  }

  async function initialize(context, state) {
    if (state.kind !== "ic") return;
    const existing = candidates(state);
    if (existing.length) return;
    try {
      const value = await context.api("/api/data_source_categories");
      state.values.category_candidates = (value.categories || []).map(item => ({
        ...item,
        enabled: item.enabled !== false,
      }));
      state.categoryError = "";
    } catch (error) {
      state.categoryError = error.message;
    }
  }

  function candidates(state) {
    return Array.isArray(state.values?.category_candidates)
      ? state.values.category_candidates.filter(item => item && typeof item === "object")
      : [];
  }

  function setCategory(state, category) {
    const id = categoryID(category);
    state.values.category = state.values.category === id ? "" : id;
  }

  function setEnabled(state, category, enabled) {
    category.enabled = Boolean(enabled);
    if (!category.enabled && state.values.category === categoryID(category)) {
      state.values.category = "";
    }
  }

  function panel(context, state, refresh) {
    if (state.kind !== "ic") return null;
    const root = document.createElement("fieldset");
    root.className = "test-category-selector test-object-field";
    const legend = document.createElement("legend");
    legend.textContent = context.t("分类");
    const note = document.createElement("small");
    note.textContent = context.t("用于分组 IC；选择一个默认分类，并可停用不参与候选的分类");
    const list = document.createElement("div");
    list.className = "test-category-list";
    for (const category of candidates(state)) {
      const row = document.createElement("div");
      row.className = "test-category-row";
      const selected = document.createElement("input");
      selected.type = "radio";
      selected.name = "ic-category";
      selected.checked = state.values.category === categoryID(category);
      selected.disabled = category.enabled === false;
      selected.addEventListener("click", () => {
        setCategory(state, category);
        refresh();
      });
      const copy = document.createElement("span");
      const title = document.createElement("b");
      title.textContent = categoryID(category);
      const detail = document.createElement("small");
      const members = Array.isArray(category.categories) ? category.categories.join("、") : "";
      detail.textContent = [category.source || context.t("数据源"), members]
        .filter(Boolean).join(" · ");
      copy.append(title, detail);
      const toggle = context.button(
        category.enabled === false ? context.t("已停用") : context.t("已启用"),
        () => {
          setEnabled(state, category, category.enabled === false);
          refresh();
        },
      );
      toggle.className = category.enabled === false ? "is-disabled" : "is-enabled";
      row.append(selected, copy, toggle);
      list.append(row);
    }
    if (!list.childElementCount) {
      list.append(FTUI.empty(context.t("暂无分类"), context.t("当前数据源没有声明分类")));
    }
    root.append(legend, note, list);
    if (state.categoryError) {
      const error = document.createElement("small");
      error.className = "test-product-warning";
      error.textContent = state.categoryError;
      root.append(error);
    }
    return root;
  }

  window.FTTestCategories = Object.freeze({
    categoryID, initialize, candidates, setCategory, setEnabled, panel,
  });
})();
