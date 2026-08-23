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
        disabled: item?.disabled === true,
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
    return translate(context, "已选 %lld 项", "已选%lld项")
      .replace(/%lld/g, String(count));
  }

  function helpIcon(help) {
    if (window.FTUI?.helpIcon) return window.FTUI.helpIcon(help);
    if (window.FTHelp?.create) return window.FTHelp.create(help);
    const icon = document.createElement("button");
    icon.type = "button";
    icon.className = "ft-help-icon";
    icon.textContent = "?";
    icon.setAttribute("aria-label", help);
    return icon;
  }

  let outsideCloseBound = false;
  const portaledControls = new Set();
  let orphanObserver = null;

  function watchPortaledControl(control) {
    portaledControls.add(control);
    if (orphanObserver || typeof MutationObserver !== "function"
      || !document?.documentElement) return;
    orphanObserver = new MutationObserver(() => {
      for (const current of [...portaledControls]) {
        if (current.section.isConnected) continue;
        current.close();
        portaledControls.delete(current);
      }
    });
    orphanObserver.observe(document.documentElement, {childList: true, subtree: true});
  }

  function bindOutsideClose() {
    if (outsideCloseBound
      || typeof document === "undefined"
      || typeof document.addEventListener !== "function") return;
    document.addEventListener("click", event => {
      if (event.target?.closest?.(".ft-multi-select-dropdown")) return;
      if (typeof document.querySelectorAll !== "function") return;
      document.querySelectorAll(".ft-multi-select-dropdown[open]")
        .forEach(dropdown => { dropdown.open = false; });
    });
    outsideCloseBound = true;
  }

  function create(context, options = {}) {
    bindOutsideClose();
    const controlDisabled = Boolean(options.loading) || (
      typeof options.disabled === "function" ? false : Boolean(options.disabled)
    );
    const disabledReason = String(
      options.disabledReason
      || (options.loading ? options.loadingText || translate(context, "正在读取候选…") : ""),
    ).trim();
    const items = normalizeItems(options.items).map(item => ({
      ...item,
      disabled: item.disabled || (typeof options.disabled === "function"
        ? Boolean(options.disabled(item)) : Boolean(options.disabled)),
    }));
    const multi = options.multi !== false;
    let selected = normalizeSelected(options.selected ?? [], items);
    if (!multi && selected.length > 1) selected = [selected[selected.length - 1]];
    let committedSelected = [...selected];

    const section = document.createElement("section");
    section.className = ["ft-multi-select-filter", options.className || ""]
      .filter(Boolean).join(" ");
    if (controlDisabled) {
      section.classList.add("is-locked");
      section.setAttribute("aria-disabled", "true");
      if (disabledReason) section.title = disabledReason;
    }
    const heading = document.createElement("div");
    heading.className = "ft-multi-select-heading";
    if (options.title && options.compact !== true) {
      const title = document.createElement("h2");
      title.textContent = options.title;
      heading.append(title);
    }
    const selectedLabel = document.createElement("span");
    selectedLabel.className = "ft-multi-select-selection";
    heading.append(selectedLabel);
    const headingActions = document.createElement("div");
    headingActions.className = "ft-multi-select-heading-actions";
    const declaredActions = [
      ...(Array.isArray(options.actions) ? options.actions : []),
      ...(options.createAction ? [options.createAction] : []),
    ].filter(action => action && action.label);
    for (const action of declaredActions) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = ["ft-multi-select-heading-action", action.buttonClass || ""]
        .filter(Boolean).join(" ");
      button.textContent = action.label;
      if (action.title) button.title = action.title;
      button.disabled = controlDisabled || (typeof action.disabled === "function"
        ? Boolean(action.disabled()) : Boolean(action.disabled));
      button.addEventListener("click", event => action.onClick?.(event));
      headingActions.append(button);
    }
    const trailingActions = options.actionsPlacement === "trailing"
      && headingActions.childElementCount > 0;
    if (!trailingActions && headingActions.childElementCount) heading.append(headingActions);
    if (options.compact !== true || (!trailingActions && headingActions.childElementCount)) {
      if (options.compact === true) heading.classList.add("is-compact");
      section.append(heading);
    }

    const dropdown = document.createElement("details");
    dropdown.className = "ft-multi-select-dropdown";
    const summary = document.createElement("summary");
    summary.className = "ft-multi-select-summary";
    if (controlDisabled) {
      summary.classList.add("is-disabled");
      summary.setAttribute("aria-disabled", "true");
      if (disabledReason) summary.title = disabledReason;
    }
    summary.setAttribute("aria-label", options.title || translate(context, "筛选"));
    const summaryText = document.createElement("span");
    summaryText.className = "ft-multi-select-summary-text";
    summary.append(summaryText);
    if (controlDisabled) {
      const lockIndicator = document.createElement("span");
      lockIndicator.className = "ft-multi-select-lock-indicator";
      lockIndicator.textContent = translate(context, "自动确定", "自动确定");
      summary.append(lockIndicator);
    }

    const menu = document.createElement("div");
    menu.className = ["ft-multi-select-menu", options.menuClass || ""]
      .filter(Boolean).join(" ");
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
    menu.append(searchRow, optionList);
    if (multi) menu.append(note);
    if (multi || typeof options.onApply === "function") menu.append(actions);
    dropdown.append(summary, menu);
    if (trailingActions) {
      const controlRow = document.createElement("div");
      controlRow.className = "ft-multi-select-control-row";
      headingActions.classList.add("ft-multi-select-trailing-actions");
      controlRow.append(dropdown, headingActions);
      section.append(controlRow);
    } else {
      section.append(dropdown);
    }
    const selectionPreview = document.createElement("div");
    selectionPreview.className = "ft-multi-select-selection-preview";
    if (options.compact === true && multi) section.append(selectionPreview);

    let applying = false;
    let menuPortaled = false;

    function canPortalMenu() {
      return Boolean(document?.body?.append
        && summary?.getBoundingClientRect
        && menu?.style);
    }

    function positionPortaledMenu() {
      if (!menuPortaled) return;
      const rect = summary.getBoundingClientRect();
      const viewportWidth = Number(window.innerWidth || document.documentElement?.clientWidth || 0);
      const viewportHeight = Number(window.innerHeight || document.documentElement?.clientHeight || 0);
      const margin = 8;
      const width = Math.max(240, Math.min(rect.width || 300, viewportWidth - margin * 2));
      const left = Math.max(margin, Math.min(rect.left, viewportWidth - width - margin));
      menu.style.width = `${width}px`;
      menu.style.left = `${left}px`;
      menu.style.top = `${Math.min(rect.bottom + 4, viewportHeight - margin)}px`;
      const menuRect = menu.getBoundingClientRect?.();
      if (menuRect && menuRect.bottom > viewportHeight - margin) {
        const above = rect.top - menuRect.height - 4;
        menu.style.top = `${Math.max(margin, above)}px`;
      }
    }

    function portalMenu() {
      if (menuPortaled || !canPortalMenu()) return;
      document.body.append(menu);
      menu.classList.add("is-portaled");
      if (typeof menu.showPopover === "function") {
        menu.setAttribute("popover", "manual");
        try { menu.showPopover(); } catch (_error) { /* fixed portal remains usable */ }
      }
      menuPortaled = true;
      positionPortaledMenu();
      window.addEventListener?.("resize", positionPortaledMenu);
      window.addEventListener?.("scroll", positionPortaledMenu, true);
      watchPortaledControl({section, close: () => {
        dropdown.open = false;
        restoreMenu();
      }});
    }

    function restoreMenu() {
      if (!menuPortaled) return;
      window.removeEventListener?.("resize", positionPortaledMenu);
      window.removeEventListener?.("scroll", positionPortaledMenu, true);
      if (typeof menu.hidePopover === "function") {
        try { menu.hidePopover(); } catch (_error) { /* it may already be closed */ }
      }
      menu.removeAttribute?.("popover");
      menu.classList.remove?.("is-portaled");
      menu.removeAttribute?.("style");
      dropdown.append(menu);
      menuPortaled = false;
      for (const control of [...portaledControls]) {
        if (control.section === section) portaledControls.delete(control);
      }
    }

    function itemFor(value) {
      return items.find(item => item.value === value);
    }

    function labelsFor(values = selected) {
      return values.map(value => itemLabel(itemFor(value), value));
    }

    function selectedFirst(values) {
      const selectedSet = new Set(selected);
      if (String(search.value || "").trim()) return values;
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
      const summaryValue = labels.length
        ? (labels.length === 1 ? labels[0] : countLabel(context, labels.length))
        : "";
      summaryText.textContent = summaryValue || translate(context, "未筛选");
      selectedLabel.textContent = labels.length ? labels.join("、")
        : translate(context, "未筛选");
      if (multi) {
        selectionPreview.textContent = labels.length
          ? `${translate(context, "已选择", "已选择")}：${labels.join("、")}` : "";
        selectionPreview.hidden = !labels.length;
      }
      summary.title = controlDisabled && disabledReason
        ? disabledReason : labels.join("、");
      if (multi) {
        note.textContent = labels.length
          ? `${translate(context, "已选择", "已选择")}：${labels.join("、")}`
          : translate(context, "尚未选择");
      }
      clear.hidden = !String(search.value || "");
      optionList.replaceChildren(...visibleItems().map(item => {
        const row = document.createElement("label");
        row.className = "ft-multi-select-option";
        if (selected.includes(item.value)) row.classList.add("is-selected");
        if (item.exclusive) row.classList.add("is-exclusive");
        if (item.disabled) row.classList.add("is-disabled");
        row.setAttribute("aria-label", `${item.label}：${item.description}`);
        const input = document.createElement("input");
        input.type = multi ? "checkbox" : "radio";
        if (!multi) input.name = options.name || "ft-single-select";
        input.value = item.value;
        input.checked = selected.includes(item.value);
        input.disabled = item.disabled;
        input.dataset.filterValue = item.value;
        const label = document.createElement("span");
        label.className = "ft-multi-select-option-label";
        label.textContent = item.label;
        const info = helpIcon(item.description);
        info.classList.add("ft-multi-select-option-info");
        row.append(input, label, info);
        if (item.exclusive) {
          const badge = document.createElement("span");
          badge.className = "ft-multi-select-exclusive-badge";
          badge.textContent = translate(context, "排他项", "排他");
          row.append(badge);
        }
        const itemActions = typeof options.itemActions === "function"
          ? options.itemActions(item) : [];
        const actionHost = document.createElement("span");
        actionHost.className = "ft-multi-select-option-actions";
        for (const action of (Array.isArray(itemActions) ? itemActions : [])) {
          if (!action?.label) continue;
          const button = document.createElement("button");
          button.type = "button";
          button.className = ["ft-multi-select-option-action", action.buttonClass || ""]
            .filter(Boolean).join(" ");
          button.textContent = action.label;
          button.title = action.title || action.label;
          button.disabled = controlDisabled || (typeof action.disabled === "function"
            ? Boolean(action.disabled()) : Boolean(action.disabled));
          button.addEventListener("click", event => {
            event.preventDefault();
            event.stopPropagation();
            action.onClick?.(event, item);
          });
          actionHost.append(button);
        }
        if (actionHost.childElementCount) row.append(actionHost);
        input.addEventListener("change", () => {
          if (item.disabled) return;
          if (input.checked) {
            selected = !multi
              ? [item.value]
              : item.exclusive
              ? [item.value]
              : [...selected.filter(value => !itemFor(value)?.exclusive), item.value];
          } else {
            selected = selected.filter(value => value !== item.value);
          }
          render();
          if (!multi) {
            committedSelected = [...selected];
            options.onChange?.([...selected]);
            dropdown.open = false;
          }
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
    dropdown.addEventListener("toggle", () => {
      const shell = section.closest?.(".backend-settings-shell");
      if (shell?.classList?.toggle) {
        const openPicker = shell.querySelector?.(
          ".ft-multi-select-dropdown[open]",
        );
        shell.classList.toggle("has-open-multi-select", Boolean(openPicker));
      }
      if (dropdown.open && !controlDisabled) {
        portalMenu();
        options.onOpen?.();
      } else {
        if (dropdown.open && controlDisabled) dropdown.open = false;
        restoreMenu();
      }
      if (!dropdown.open && multi && !applying) {
        selected = [...committedSelected];
        render();
      }
    });
    if (controlDisabled) {
      summary.addEventListener("click", event => {
        event.preventDefault();
        dropdown.open = false;
      });
    }

    if (multi || typeof options.onApply === "function") {
      const apply = document.createElement("button");
      apply.type = "button";
      apply.className = "primary ft-multi-select-apply";
      apply.textContent = options.applyLabel
        || translate(context, "保存", "保存");
      apply.disabled = controlDisabled;
      apply.addEventListener("click", async () => {
        if (applying || controlDisabled) return;
        applying = true;
        apply.disabled = true;
        try {
          let result;
          if (typeof options.onApply === "function") {
            result = options.onApply([...selected]);
          } else {
            result = options.onChange?.([...selected]);
          }
          if (result && typeof result.then === "function") await result;
          committedSelected = [...selected];
          dropdown.open = false;
        } catch (error) {
          context.showNotice?.(error.message || translate(context, "应用失败"), true);
        } finally {
          applying = false;
          apply.disabled = controlDisabled;
        }
      });
      actions.append(apply);
    }

    render();
    return Object.freeze({
      element: section,
      dropdown,
      summary,
      menu,
      optionList,
      search,
      clear,
      render,
      get values() { return [...selected]; },
      get multi() { return multi; },
      setValues(values) {
        selected = normalizeSelected(values, items);
        if (!multi && selected.length > 1) selected = [selected[selected.length - 1]];
        committedSelected = [...selected];
        render();
      },
      setItems(nextItems) {
        items.splice(0, items.length, ...normalizeItems(nextItems).map(item => ({
          ...item,
          disabled: item.disabled || (typeof options.disabled === "function"
            ? Boolean(options.disabled(item)) : controlDisabled),
        })));
        selected = normalizeSelected(selected, items);
        if (!multi && selected.length > 1) selected = [selected[selected.length - 1]];
        committedSelected = [...selected];
        render();
      },
    });
  }

  window.FTMultiSelectFilter = Object.freeze({create, normalizeItems});
})();
