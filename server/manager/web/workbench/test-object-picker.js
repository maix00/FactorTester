(() => {
  function lazyLoading(state, key) {
    const status = String(state?.lazy?.[key]?.status || "");
    return Boolean(status && status !== "ready" && status !== "error");
  }

  function create(context, options = {}) {
    const actions = [
      ...(Array.isArray(options.actions) ? options.actions : []),
    ];
    if (options.onCreate) {
      actions.push({
      label: options.createLabel || context.t("新建"),
        title: options.createTitle || context.t("新建并在当前浮层编辑"),
        buttonClass: "primary",
        onClick: options.onCreate,
      });
    }
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

  // Object and scalar choice fields intentionally share this exact picker.
  // The product/factor catalog filters call FTMultiSelectFilter directly; the
  // workbench wrapper only adds the create/edit actions and field semantics.
  window.FTTestObjectPicker = Object.freeze({create, lazyLoading});
  window.FTTestChoicePicker = Object.freeze({create, lazyLoading});
})();
