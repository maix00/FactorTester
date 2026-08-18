(() => {
  function categoryID(value) {
    return value?.id || value?.name || value?.label || "";
  }

  async function initialize(context, state) {
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
    state.values.category = categoryID(category);
  }

  function setEnabled(state, category, enabled) {
    category.enabled = Boolean(enabled);
    if (!category.enabled && state.values.category === categoryID(category)) {
      state.values.category = "";
    }
  }

  function openEditor(context, mode, ref, onSaved) {
    return FTTestObjectEditorOverlay.open(context, {
      kind: "category", mode, ref, onSaved,
    });
  }

  function upsertCategory(state, category) {
    const id = categoryID(category);
    if (!id) return null;
    const rows = candidates(state);
    const index = rows.findIndex(value => categoryID(value) === id);
    if (index >= 0) rows[index] = {...rows[index], ...category};
    else rows.push(category);
    state.values.category_candidates = rows;
    return rows[index >= 0 ? index : rows.length - 1];
  }

  function editAction(context, category, onSaved) {
    if (!context.session || !category || category.source_managed) return null;
    const id = categoryID(category);
    if (!id) return null;
    return {
      label: context.t("编辑"),
      title: context.t("在当前浮层编辑产品分类"),
      buttonClass: "secondary",
      onClick: event => {
        event?.preventDefault();
        void openEditor(context, "edit", id, onSaved);
      },
    };
  }

  function panel(context, state, refresh) {
    const items = candidates(state).map(category => ({
      value: categoryID(category),
      label: category.title_zh || category.alias || categoryID(category),
      description: [
        category.source || context.t("数据源"),
        Array.isArray(category.categories) ? category.categories.join("、") : "",
      ].filter(Boolean).join(" · "),
      disabled: category.enabled === false,
      source_managed: category.source_managed === true,
    })).filter(item => item.value);
    const savedCategory = value => {
      const category = upsertCategory(state, value);
      if (!category) return;
      setCategory(state, category);
      refresh?.();
    };
    const picker = FTTestObjectPicker.create(context, {
      title: context.t("分类"),
      note: context.t(state.kind === "ic"
        ? "选择一个分类用于 IC；分类由数据源或用户产品分类提供"
        : "管理本次测试中新建产品组可使用的产品分类"),
      items,
      selected: state.values.category ? [state.values.category] : [],
      multi: false,
      loading: state.lazy?.categories?.status === "loading",
      loadingText: context.t("正在读取产品分类候选…"),
      compact: true,
      name: "ic-category",
      onCreate: context.session
        ? () => void openEditor(context, "create", "new", savedCategory)
        : null,
      createLabel: context.t("新建产品分类"),
      itemActions: item => {
        const category = candidates(state).find(value => categoryID(value) === item.value);
        const actions = [];
        const edit = editAction(context, category, savedCategory);
        if (edit) actions.push(edit);
        if (category) {
          actions.push({
            label: category.enabled === false ? context.t("启用") : context.t("停用"),
            title: context.t("切换此分类是否参与候选"),
            buttonClass: "secondary",
            onClick: event => {
              event?.preventDefault();
              setEnabled(state, category, category.enabled === false);
              refresh?.();
            },
          });
        }
        return actions;
      },
      onChange: values => {
        const value = values[0] || "";
        const category = candidates(state).find(item => categoryID(item) === value);
        if (category) setCategory(state, category); else state.values.category = "";
        refresh?.();
      },
    });
    const root = FTTestFieldRow.create(
      context.t("分类"), picker.element,
      window.FTTestFieldHelp?.forField?.(state.manifest, "category", context) || "",
      {className: "test-category-selector"},
    );
    const control = root.querySelector(".test-field-row-control");
    if (!items.length) control.append(FTUI.empty(
      context.t("暂无分类"), context.t("当前数据源没有声明分类"),
    ));
    if (state.categoryError) {
      const error = document.createElement("small");
      error.className = "test-product-warning";
      error.textContent = state.categoryError;
      control.append(error);
    }
    return root;
  }

  window.FTTestCategories = Object.freeze({
    categoryID, initialize, candidates, setCategory, setEnabled, panel,
  });
})();
