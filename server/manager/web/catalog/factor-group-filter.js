(() => {
  function choices(context, groups) {
    const values = [
      {
        value: "*",
        label: context.t("全部产品组"),
        description: context.t("显示所有产品组绑定状态的因子"),
        exclusive: true,
      },
      {
        value: "",
        label: context.t("未绑定产品组"),
        description: context.t("只显示没有绑定产品组的因子"),
      },
    ];
    const names = (Array.isArray(groups) ? groups : []).flatMap(group => {
      const value = window.FTFactorModel.groupRef(group);
      if (!value) return [];
      return [{
        value,
        label: group.name || value,
        description: group.description
          || `${group.name || value} · ${group.path_count ?? group.paths?.length ?? 0}${context.t("条产品路径")}`,
      }];
    });
    names.sort((left, right) => left.label.localeCompare(right.label, "zh-CN"));
    return [...values, ...names];
  }

  function create(
    context,
    groups,
    initialValues = ["*"],
    onChange = () => {},
    options = {},
  ) {
    const filter = window.FTMultiSelectFilter.create(context, {
      title: context.t("按产品组筛选"),
      className: "factor-product-group-filter",
      menuClass: "factor-product-group-filter-menu",
      searchPlaceholder: context.t("搜索产品组"),
      items: choices(context, groups),
      selected: initialValues,
      onChange,
      onOpen: options.onOpen,
    });
    return Object.freeze({
      element: filter.element,
      dropdown: filter.dropdown,
      menu: filter.menu,
      optionList: filter.optionList,
      options: filter.optionList,
      search: filter.search,
      clear: filter.clear,
      render: filter.render,
      setValues: filter.setValues,
      get values() { return filter.values; },
      get value() { return filter.values[0] || ""; },
    });
  }

  window.FTFactorGroupFilter = Object.freeze({create, choices});
})();
