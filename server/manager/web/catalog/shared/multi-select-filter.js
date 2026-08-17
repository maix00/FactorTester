(() => {
  function translate(context, key, fallback = key) {
    return typeof context?.t === "function" ? context.t(key, fallback) : fallback;
  }

  function itemValue(item) {
    return String(item?.value ?? item?.ref ?? item?.id ?? "").trim();
  }

  function itemLabel(item, value) {
    return String(item?.label ?? item?.title ?? value).trim() || value;
  }

  function normalizeItems(items) {
    const seen = new Set();
    return (Array.isArray(items) ? items : []).flatMap(item => {
      const value = itemValue(item);
      if (seen.has(value)) return [];
      seen.add(value);
      return [{
        ...item,
        value,
        label: itemLabel(item, value),
        description: String(
          item?.description ?? item?.desc ?? item?.title ?? item?.label ?? value,
        ).trim(),
        exclusive: item?.exclusive === true,
      }];
    });
  }

  function normalizeSelected(values, items) {
    const allowed = new Set(items.map(item => item.value));
    const selected = [];
    const raw = Array.isArray(values) ? values : [values];
    raw.forEach(value => {
      const normalized = String(value ?? "").trim();
      if (allowed.has(normalized) && !selected.includes(normalized)) {
        selected.push(normalized);
      }
    });
    const exclusive = selected.filter(value => (
      items.find(item => item.value === value)?.exclusive === true
    ));
    if (exclusive.length) return [exclusive[exclusive.length - 1]];
    return selected;
  }

  function countLabel(context, count) {
    return translate(context, "已选 %lld 个", "已选%lld个")
      .replace(/%lld/g, String(count));
  }

  function create(context, options = {}) {
    const items = normalizeItems(options.items);
    let selected = normalizeSelected(options.selected ?? [], items);

    const section = document.createElement("section");
    section.className = ["ft-multi-select-filter", options.className || ""]
      .filter(Boolean).join(" ");
    const heading = document.createElement("div");
    heading.className = "ft-multi-select-heading";
    if (options.title) {
      const title = document.createElement("h2");
      title.textContent = options.title;
      heading.append(title);
    }
    const selectedLabel = document.createElement("span");
    selectedLabel.className = "ft-multi-select-selection";
    heading.append(selectedLabel);
    section.append(heading);

    const dropdown = document.createElement("details");
    dropdown.className = "ft-multi-select-dropdown";
    const summary = document.createElement("summary");
    summary.className = "ft-multi-select-summary";
    summary.setAttribute("aria-label", options.title || translate(context, "筛选"));
    const summaryText = document.createElement("span");
    summaryText.className = "ft-multi-select-summary-text";
    summary.append(summaryText);

    const menu = document.createElement("div");
    menu.className = "ft-multi-select-menu";
    menu.addEventListener("click", event => event.stopPropagation());
    const searchRow = document.createElement("div");
    searchRow.className = "ft-multi-select-search-row";
    const search = document.createElement("input");
    search.type = "search";
    search.className = "ft-multi-select-search";
    search.placeholder = options.searchPlaceholder
      || translate(context, "搜索…", "搜索…");
    search.setAttribute("aria-label", search.placeholder);
    const clear = document.createElement("button");
    clear.type = "button";
    clear.className = "ft-multi-select-clear";
    clear.textContent = "×";
    clear.title = translate(context, "清除搜索", "清除搜索");
    clear.setAttribute("aria-label", clear.title);
    searchRow.append(search, clear);
    const optionList = document.createElement("div");
    optionList.className = "ft-multi-select-options";
    optionList.setAttribute("role", "group");
    const note = document.createElement("div");
    note.className = "ft-multi-select-selection-note";
    const actions = document.createElement("div");
    actions.className = "ft-multi-select-actions";
    menu.append(searchRow, optionList, note);
    if (typeof options.onApply === "function") menu.append(actions);
    dropdown.append(summary, menu);
    section.append(dropdown);

    let applying = false;

    function itemFor(value) {
      return items.find(item => item.value === value);
    }

    function labelsFor(values = selected) {
      return values.map(value => itemLabel(itemFor(value), value));
    }

    function selectedFirst(values) {
      const selectedSet = new Set(selected);
      if (search.value.trim()) return values;
      return [...values].sort((left, right) => {
        const leftSelected = selectedSet.has(left.value) ? 0 : 1;
        const rightSelected = selectedSet.has(right.value) ? 0 : 1;
        return leftSelected - rightSelected
          || left.label.localeCompare(right.label, "zh-CN");
      });
    }

    function visibleItems() {
      const query = String(search.value || "").trim().toLocaleLowerCase();
      const filtered = !query ? items : items.filter(item => (
        `${item.label} ${item.value} ${item.description}`
          .toLocaleLowerCase().includes(query)
      ));
      return selectedFirst(filtered);
    }

    function render() {
      const labels = labelsFor();
      const summaryValue = labels.length === 1 && itemFor(selected[0])?.exclusive
        ? labels[0] : countLabel(context, labels.length);
      summaryText.textContent = summaryValue || translate(context, "未筛选");
      selectedLabel.textContent = labels.length ? labels.join("、")
        : translate(context, "未筛选");
      summary.title = labels.join("、");
      note.textContent = labels.length
        ? `${translate(context, "已选择", "已选择")}：${labels.join("、")}`
        : translate(context, "尚未选择");
      clear.hidden = !String(search.value || "");
      optionList.replaceChildren(...visibleItems().map(item => {
        const row = document.createElement("label");
        row.className = "ft-multi-select-option";
        if (selected.includes(item.value)) row.classList.add("is-selected");
        if (item.exclusive) row.classList.add("is-exclusive");
        row.title = item.description;
        row.setAttribute("aria-label", `${item.label}：${item.description}`);
        const input = document.createElement("input");
        input.type = "checkbox";
        input.value = item.value;
        input.checked = selected.includes(item.value);
        input.dataset.filterValue = item.value;
        const label = document.createElement("span");
        label.className = "ft-multi-select-option-label";
        label.textContent = item.label;
        const info = document.createElement("span");
        info.className = "ft-multi-select-option-info";
        info.textContent = "ⓘ";
        info.title = item.description;
        info.setAttribute("aria-label", item.description);
        row.append(input, label, info);
        input.addEventListener("change", () => {
          if (input.checked) {
            selected = item.exclusive
              ? [item.value]
              : [...selected.filter(value => !itemFor(value)?.exclusive), item.value];
          } else {
            selected = selected.filter(value => value !== item.value);
          }
          render();
          options.onChange?.([...selected]);
        });
        return row;
      }));
    }

    clear.addEventListener("click", () => {
      search.value = "";
      render();
      search.focus();
    });
    search.addEventListener("input", render);

    if (typeof options.onApply === "function") {
      const apply = document.createElement("button");
      apply.type = "button";
      apply.className = "primary ft-multi-select-apply";
      apply.textContent = options.applyLabel || translate(context, "应用");
      apply.addEventListener("click", async () => {
        if (applying) return;
        applying = true;
        apply.disabled = true;
        try {
          await options.onApply([...selected]);
          dropdown.open = false;
        } catch (error) {
          context.showNotice?.(error.message || translate(context, "应用失败"), true);
        } finally {
          applying = false;
          apply.disabled = false;
        }
      });
      actions.append(apply);
    }

    render();
    return Object.freeze({
      element: section,
      dropdown,
      menu,
      optionList,
      search,
      clear,
      render,
      get values() { return [...selected]; },
      setValues(values) {
        selected = normalizeSelected(values, items);
        render();
      },
    });
  }

  window.FTMultiSelectFilter = Object.freeze({create, normalizeItems});
})();
