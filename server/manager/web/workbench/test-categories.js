(() => {
  const pendingLoads = new WeakMap();
  function categoryID(value) {
    return value?.id || value?.name || value?.label || "";
  }

  async function initialize(context, state) {
    const existing = candidates(state);
    if (state.categoryCandidatesLoaded) return;
    if (pendingLoads.has(state)) return pendingLoads.get(state);
    const request = (async () => { try {
      const value = await context.api("/api/product-library/data-source-categories");
      const fetched = (value.categories || []).map(item => ({
        ...item,
        enabled: item.enabled !== false,
      }));
      const byID = new Map();
      for (const item of [...fetched, ...existing]) {
        const id = categoryID(item);
        if (id) byID.set(String(id), item);
      }
      state.categoryCatalog = [...byID.values()];
      state.values.category_candidates = [...state.categoryCatalog];
      state.categoryCandidatesLoaded = true;
      state.categoryError = "";
    } catch (error) {
      state.categoryError = error.message;
    } finally {
      pendingLoads.delete(state);
    }})();
    pendingLoads.set(state, request);
    return request;
  }

  function candidates(state) {
    const catalog = Array.isArray(state.categoryCatalog)
      ? state.categoryCatalog : state.values?.category_candidates;
    return Array.isArray(catalog)
      ? catalog.filter(item => item && typeof item === "object")
      : [];
  }

  function availableCandidates(state) {
    const values = candidates(state);
    return window.FTStrategyEditorScope?.constrainedCandidates
      ? FTStrategyEditorScope.constrainedCandidates(
          state, "category_candidates", values,
        )
      : values;
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

  function openEditor(context, mode, ref, onSaved, testState = null, initialValue = null) {
    return FTTestLazyCode.openObjectEditor(context, {
      kind: "category", mode, ref, onSaved, testState,
      temporary: mode === "create" || initialValue?.temporary === true,
      initialValue,
    });
  }

  function upsertCategory(state, category) {
    const id = categoryID(category);
    if (!id) return null;
    const rows = candidates(state);
    const index = rows.findIndex(value => categoryID(value) === id);
    if (index >= 0) rows[index] = {...rows[index], ...category};
    else rows.push(category);
    state.categoryCatalog = rows;
    state.values.category_candidates = [...rows];
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
        void openEditor(context, "edit", id, onSaved, null, category);
      },
    };
  }

  function panel(context, state, refresh) {
    const items = availableCandidates(state).map(category => ({
      value: categoryID(category),
      label: category.title_zh || category.alias || categoryID(category),
      description: [
        category.source || context.t("数据源"),
        Array.isArray(category.categories) ? category.categories.join("、") : "",
      ].filter(Boolean).join(" · "),
      disabled: category.enabled === false,
      source_managed: category.source_managed === true,
      category,
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
      loading: FTTestObjectPicker.lazyLoading(state, "categories"),
      loadingText: context.t("正在读取产品分类候选…"),
      compact: true,
      name: "ic-category",
      onCreate: context.session
        ? () => void openEditor(context, "create", "new", savedCategory, state)
        : null,
      createLabel: context.t("新建产品分类"),
      editSelected: item => item.category?.temporary === true
        || item.category?.source_origin === "test_inline",
      onEdit: (_event, item) => void openEditor(
        context, "edit", categoryID(item.category), savedCategory, state, item.category,
      ),
      editLabel: context.t("编辑产品分类"),
      itemActions: item => {
        const category = availableCandidates(state).find(value => categoryID(value) === item.value);
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
        const category = availableCandidates(state).find(item => categoryID(item) === value);
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
    if (state.values.category && !items.some(item => item.value === state.values.category)) {
      const warning = document.createElement("small");
      warning.className = "test-product-warning";
      warning.textContent = context.t("当前产品分类不受已选数据源完整支持，请重新选择");
      control.append(warning);
    }
    return root;
  }

  window.FTTestCategories = Object.freeze({
    categoryID, initialize, candidates, availableCandidates,
    setCategory, setEnabled, panel,
  });
})();
