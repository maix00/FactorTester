(() => {
  function lazyLoading(state, key) {
    const status = String(state?.lazy?.[key]?.status || "");
    return Boolean(status && status !== "ready" && status !== "error");
  }

  function create(context, options = {}) {
    const actions = [
      ...(Array.isArray(options.actions) ? options.actions : []),
    ];
    const selectedValues = Array.isArray(options.selected)
      ? options.selected : [options.selected].filter(Boolean);
    const selectedItem = (options.items || []).find(item => (
      selectedValues.includes(String(item.value ?? item.id ?? item.ref ?? ""))
    ));
    const editSelected = Boolean(
      selectedItem && options.onEdit
      && (typeof options.editSelected === "function"
        ? options.editSelected(selectedItem) : options.editSelected === true),
    );
    if (editSelected || options.onCreate) {
      actions.push({
        label: editSelected
          ? options.editLabel || context.t("编辑")
          : options.createLabel || context.t("新建"),
        title: editSelected
          ? options.editTitle || context.t("编辑当前选中的当场对象")
          : options.createTitle || context.t("新建并在当前浮层编辑"),
        buttonClass: "primary",
        onClick: editSelected
          ? event => options.onEdit(event, selectedItem)
          : options.onCreate,
      });
    }
    const kindLabelOf = options.typeLabelOf || ((key, item) => {
      const kind = String(item?.type || item?.kind || key || "").trim();
      const known = {
        factor: context.t("因子"), factor_family: context.t("因子家族"),
        product: context.t("产品"), product_group: context.t("产品组"),
        category: context.t("分类"), strategy: context.t("策略"),
        factor_set: context.t("因子候选"), factor_sequence: context.t("因子序列"),
        nested_factor: context.t("嵌套因子"), factor: context.t("因子"),
        column: context.t("DataColumn"),
      };
      return known[kind] || kind || "";
    });
    const filter = FTMultiSelectFilter.create(context, {
      ...options,
      items: (options.items || []).map(item => ({
        ...item,
        value: String(item.value ?? item.id ?? item.ref ?? ""),
        label: item.label || item.title || item.name || item.value || item.id,
      })),
      selected: options.selected || [],
      actions,
      actionsPlacement: options.actionsPlacement
        || (actions.length ? "trailing" : undefined),
      multi: options.multi !== false,
      typeLabelOf: options.typeLabelOf
        || ((key, item) => item?.typeLabel || kindLabelOf(key, item)),
    });
    filter.element.classList.add("ft-test-object-picker");
    const insertBeforeDropdown = node => {
      const dropdown = filter.element.querySelector(".ft-multi-select-dropdown");
      const anchor = dropdown?.parentElement || filter.element.firstChild;
      if (anchor?.parentElement) anchor.parentElement.insertBefore(node, anchor);
      else filter.element.append(node);
    };
    if (options.loading) {
      const loading = document.createElement("small");
      loading.className = "ft-test-object-picker-loading";
      loading.textContent = options.loadingText || context.t("正在读取候选…");
      insertBeforeDropdown(loading);
    }
    if (options.note && options.compact !== true) {
      const note = document.createElement("small");
      note.className = "ft-test-object-picker-note";
      note.textContent = options.note;
      insertBeforeDropdown(note);
    }
    return filter;
  }

  // The unified object picker: a thin wrapper over FTMultiSelectFilter that
  // concentrates the object-choice semantics (create/edit current object,
  // loading/note affordances, candidate-type grouping via type/kind).  Object
  // and scalar choice fields intentionally share this exact picker.  The
  // product/factor catalog filters call FTMultiSelectFilter directly; the
  // workbench wrapper only adds the create/edit actions and field semantics.
  window.FTObjectPicker = Object.freeze({create, lazyLoading});
  window.FTTestObjectPicker = window.FTObjectPicker;
  window.FTTestChoicePicker = window.FTObjectPicker;
})();
