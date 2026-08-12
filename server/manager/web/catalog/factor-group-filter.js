(() => {
  function choices(context, groups) {
    const values = [
      {ref: "*", label: context.t("全部产品组")},
      {ref: "", label: context.t("未绑定产品组")},
    ];
    const names = (Array.isArray(groups) ? groups : []).flatMap(group => {
      const ref = window.FTFactorModel.groupRef(group);
      return ref ? [{ref, label: group.name || ref}] : [];
    });
    names.sort((left, right) => left.label.localeCompare(right.label, "zh-CN"));
    return [...values, ...names];
  }

  function create(context, groups, initialRef = "*", onChange = () => {}) {
    const section = document.createElement("section");
    section.className = "factor-product-group-filter";
    const heading = document.createElement("div");
    heading.className = "factor-product-group-filter-heading";
    const title = document.createElement("h2");
    title.textContent = context.t("按产品组筛选");
    const selectedLabel = document.createElement("span");
    selectedLabel.className = "factor-product-group-selection";
    heading.append(title, selectedLabel);
    const search = document.createElement("input");
    search.type = "search";
    search.className = "factor-product-group-search";
    search.placeholder = context.t("搜索产品组");
    const options = document.createElement("div");
    options.className = "factor-product-group-options";
    section.append(heading, search, options);

    const allChoices = choices(context, groups);
    let selectedRef = allChoices.some(item => item.ref === initialRef)
      ? initialRef : "*";

    function render() {
      const query = String(search.value || "").trim().toLowerCase();
      const visible = allChoices.filter(item => !query
        || `${item.label} ${item.ref}`.toLowerCase().includes(query));
      const buttons = visible.map(item => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = `factor-product-group-option${
          item.ref === selectedRef ? " active" : ""
        }`;
        button.textContent = item.label;
        button.setAttribute("aria-pressed", item.ref === selectedRef ? "true" : "false");
        button.addEventListener("click", () => {
          selectedRef = item.ref;
          render();
          onChange(selectedRef);
        });
        return button;
      });
      options.replaceChildren(...buttons);
      selectedLabel.textContent = allChoices.find(item => item.ref === selectedRef)?.label || "";
    }

    search.addEventListener("input", render);
    render();
    return {
      element: section,
      options,
      search,
      get value() { return selectedRef; },
    };
  }

  window.FTFactorGroupFilter = Object.freeze({create});
})();
