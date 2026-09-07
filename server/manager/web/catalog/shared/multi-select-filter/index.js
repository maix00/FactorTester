(() => {
  // Page-level mutual exclusion: only one dropdown is expanded at a time.  A
  // module-level handle to the currently-open dropdown lets any newly opened
  // dropdown collapse the previous one regardless of host shell structure —
  // this is what makes "同一个 tab 同时只能展开一个" hold even when the pickers
  // live in different settings shells / parameter tables.
  let activeMultiSelect = null;

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

  // Row-level object viewing: an option item may declare an optional `view`
  // descriptor so its trailing "?" opens the matching object's view overlay
  // (factor, factor family, product group, category, factor set, ...) instead
  // of a plain text bubble.  Descriptors are {kind, ref, initialValue,
  // temporary} — the same shape FTObjectOverlay.open consumes.  The picker
  // itself stays domain-free: it only needs a resolver that turns an item
  // into such a descriptor (or null) and an opener that lifts it.
  function openItemView(context, view, options = {}) {
    if (!view || typeof view !== "object") return false;
    const descriptor = {kind: view.kind, mode: "view", ref: view.ref || ""};
    if (view.initialValue !== undefined) descriptor.initialValue = view.initialValue;
    if (view.temporary === true) descriptor.temporary = true;
    if (typeof view.onSaved === "function") descriptor.onSaved = view.onSaved;
    if (options.testState !== undefined) descriptor.testState = options.testState;
    const open = context?.openObject || (window.FTObjectOverlay?.open
      ? childOptions => window.FTObjectOverlay.open(context, childOptions)
      : null);
    if (open) { open(descriptor); return true; }
    const loader = window.FTStaticLoader?.loadGroups;
    if (typeof loader !== "function") return false;
    void Promise.resolve(loader(["object-overlay"])).then(() => {
      if (window.FTObjectOverlay?.open) {
        window.FTObjectOverlay.open(context, descriptor);
      }
    }).catch(() => {});
    return true;
  }

  function optionHelp(context, item, options = {}) {
    const view = typeof options.viewOf === "function"
      ? options.viewOf(item) : item?.view || null;
    if (view && typeof view === "object") {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "ft-help-icon";
      button.textContent = "?";
      // Descriptor titles are i18n keys ("查看因子", "查看因子家族", …).
      const label = view.title ? context.t(view.title)
        : translate(context, "查看", "查看");
      button.setAttribute("aria-label", label);
      button.title = label;
      button.addEventListener("click", event => {
        event.preventDefault?.();
        event.stopPropagation?.();
        // On-the-fly objects: the view overlay edits in place and, on save,
        // overwrites this candidate — a shared capability for every temporary
        // object (factor, family, set, ...), not just the factor parameter.
        const enhanced = (item.onsite === true || item.temporary === true)
          ? {
              ...view,
              initialValue: view.initialValue !== undefined
                ? view.initialValue
                : (item.factor || item.family || item.factorSet || item),
              temporary: view.temporary !== true ? true : view.temporary,
              onSaved: typeof view.onSaved === "function" ? view.onSaved : saved => {
                options.updateTemporaryCandidate?.(item, saved);
              },
            }
          : view;
        openItemView(context, enhanced, options);
      });
      return button;
    }
    return helpIcon(item?.description);
  }

  let outsideCloseBound = false;
  const portaledControls = new Set();
  let orphanObserver = null;
  let pickerSequence = 0;

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
    const configuredDisabled = (
      typeof options.disabled === "function" ? false : Boolean(options.disabled)
    );
    let manualLoading = Boolean(options.loading);
    let controlDisabled = manualLoading || configuredDisabled;
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
    // Candidate-type grouping: when any candidate carries a `type`/`kind`
    // field (object pickers), the 候选 section is split into one
    // 「候选（××类型）」 group per type; scalar providers without a type field
    // keep a single plain 「候选」 group.
    const typeOf = options.typeOf
      || (item => String(item?.type || item?.kind || "").trim());
    const typeLabelOf = options.typeLabelOf
      || ((key, item) => String(item?.typeLabel || key || "").trim());
    const candidateGrouped = options.groupByType !== false
      && items.some(item => typeOf(item));
    const singleGroupName = `${String(options.name || "ft-single-select").trim()
      || "ft-single-select"}-${++pickerSequence}`;
    let selected = normalizeSelected(options.selected ?? [], items);
    if (!multi && selected.length > 1) selected = [selected[selected.length - 1]];
    let committedSelected = [...selected];
    let manualStatusText = String(options.statusText || "").trim();
    let manualErrorText = String(options.errorText || "").trim();
    const remoteFactory = typeof options.loadItems === "function"
      && window.FTMultiSelectRemote?.create;

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
    // Multi-select state already appears in the closed summary and checked
    // menu rows. Keep the heading value only for single-select callers so a
    // multi-select never duplicates its selected items outside the control.
    if (!multi) heading.append(selectedLabel);
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
    if (controlDisabled && !options.loading) {
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
    // Optional on-the-fly creation entry ("+") declared by the caller.  It
    // reuses the caller's existing on-the-fly path; created candidates join
    // the selectable pool flagged with an 当场 badge.  Editing stays on the
    // view-overlay (?) infrastructure.
    if (typeof options.onAddCandidate === "function"
      && !(candidateGrouped && typeof options.onAddCandidateForType === "function")) {
      const addToggle = document.createElement("button");
      addToggle.type = "button";
      addToggle.className = "ft-multi-select-add-toggle icon-action-button";
      const addTitle = translate(context, "当场新增", "当场新增");
      addToggle.title = addTitle;
      addToggle.setAttribute("aria-label", addTitle);
      addToggle.addEventListener("click", event => {
        event.stopPropagation?.();
        const add = value => {
          if (!value || typeof value !== "object") return;
          const ref = String(
            value.value ?? value.ref ?? value.id ?? value.factor_ref ?? "",
          ).trim();
          const valueKey = ref || String(value.label || value.alias || "").trim();
          if (!valueKey) return;
          if (items.some(item => (
            String(item.value ?? item.ref ?? item.id ?? "").trim() === valueKey
            || (item.label || "").trim() === valueKey
          ))) return;
          items.push({
            ...value,
            value: valueKey,
            onsite: true,
            temporary: true,
            label: value.label || value.alias || valueKey,
          });
          render();
        };
        options.onAddCandidate(context, {add, close: () => {}});
      });
      const plusNode = window.FTIcons?.node?.("plus");
      if (plusNode) {
        addToggle.replaceChildren?.(plusNode);
      } else {
        addToggle.textContent = "+";
      }
      searchRow.append(addToggle);
    }
    // Default refresh icon in the search row: reuse FTUI.refreshButton, which
    // owns the spin/lock animation (refreshing → complete → idle, error tint)
    // and disables the button while re-pulling the long-lived candidate source.
    if (window.FTUI?.refreshButton) {
      const syncButton = window.FTUI.refreshButton(context, async () => {
        if (typeof options.onRefresh === "function") {
          await options.onRefresh(context);
        } else if (remote?.refresh) {
          await remote.refresh();
        }
        if (remote) remote.render(); else render();
      }, { label: "同步候选", className: "ft-multi-select-sync-toggle" });
      searchRow.append(syncButton);
    } else {
      const syncToggle = document.createElement("button");
      syncToggle.type = "button";
      syncToggle.className = "ft-multi-select-sync-toggle icon-action-button";
      const syncTitle = translate(context, "同步候选", "同步候选");
      syncToggle.title = syncTitle;
      syncToggle.setAttribute("aria-label", syncTitle);
      syncToggle.addEventListener("click", event => {
        event.stopPropagation?.();
        if (typeof options.onRefresh === "function") {
          const result = options.onRefresh(context);
          if (result && typeof result.then === "function") {
            result.finally(() => { if (remote) remote.render(); else render(); });
          }
          return;
        }
        remote?.refresh?.();
      });
      const syncIcon = window.FTIcons?.node
        ? (window.FTIcons.node("arrow.clockwise")
          || window.FTIcons.node("arrow.2.circlepath"))
        : null;
      if (syncIcon) {
        syncToggle.replaceChildren?.(syncIcon);
      } else {
        syncToggle.textContent = "↻";
      }
      searchRow.append(syncToggle);
    }
    const optionList = document.createElement("div");
    optionList.className = "ft-multi-select-options";
    optionList.setAttribute("role", "group");
    const actions = document.createElement("div");
    actions.className = "ft-multi-select-actions";
    menu.append(searchRow, optionList);
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
    let applying = false;
    let menuPortaled = false;
    let menuResizeObserver = null;

    function canPortalMenu() {
      return Boolean(document?.body?.append
        && summary?.getBoundingClientRect
        && menu?.style);
    }

    function portalHost() {
      // A modal <dialog> makes the rest of the document inert.  Portaling its
      // menu to document.body therefore paints the menu but prevents real
      // pointer input from reaching its options.  Keep the fixed-position
      // menu inside the owning dialog's top-layer subtree instead.
      return section.closest?.("dialog[open]") || document.body;
    }

    function positionPortaledMenu() {
      if (!menuPortaled) return;
      const rect = summary.getBoundingClientRect();
      const viewport = window.visualViewport;
      const viewportWidth = Number(viewport?.width || window.innerWidth || document.documentElement?.clientWidth || 0);
      const viewportHeight = Number(viewport?.height || window.innerHeight || document.documentElement?.clientHeight || 0);
      const viewportLeft = Number(viewport?.offsetLeft || 0);
      const viewportTop = Number(viewport?.offsetTop || 0);
      const margin = 8;
      const width = Math.min(Math.max(240, rect.width || 300), 560, Math.max(0, viewportWidth - margin * 2));
      const left = Math.max(viewportLeft + margin, Math.min(rect.left, viewportLeft + viewportWidth - width - margin));
      const above = Math.max(0, rect.top - viewportTop - margin - 4);
      const below = Math.max(0, viewportTop + viewportHeight - rect.bottom - margin - 4);
      const openAbove = above >= 120 || above >= below;
      menu.style.position = "fixed";
      menu.style.minWidth = "0px";
      menu.style.width = `${width}px`;
      menu.style.left = `${left}px`;
      menu.style.maxHeight = `${Math.min(680, openAbove ? above : below)}px`;
      const menuRect = menu.getBoundingClientRect?.();
      const height = Math.min(menuRect?.height || 0, openAbove ? above : below);
      menu.style.top = `${openAbove ? Math.max(viewportTop + margin, rect.top - height - 4) : rect.bottom + 4}px`;
    }

    function portalMenu() {
      if (menuPortaled || !canPortalMenu()) return;
      portalHost().append(menu);
      menu.classList.add("is-portaled");
      if (typeof menu.showPopover === "function") {
        menu.setAttribute("popover", "manual");
        try { menu.showPopover(); } catch (_error) { /* fixed portal remains usable */ }
      }
      menuPortaled = true;
      positionPortaledMenu();
      if (typeof ResizeObserver === "function") {
        menuResizeObserver = new ResizeObserver(positionPortaledMenu);
        menuResizeObserver.observe(summary);
        menuResizeObserver.observe(menu);
      }
      window.addEventListener?.("resize", positionPortaledMenu);
      window.addEventListener?.("scroll", positionPortaledMenu, true);
      // Pinch-zoom changes the visual viewport without firing window resize;
      // reposition so the menu stays anchored to its summary.
      window.visualViewport?.addEventListener?.("resize", positionPortaledMenu);
      window.visualViewport?.addEventListener?.("scroll", positionPortaledMenu);
      watchPortaledControl({section, close: () => {
        dropdown.open = false;
        restoreMenu();
      }});
    }

    function restoreMenu() {
      if (!menuPortaled) return;
      menuResizeObserver?.disconnect();
      menuResizeObserver = null;
      window.removeEventListener?.("resize", positionPortaledMenu);
      window.removeEventListener?.("scroll", positionPortaledMenu, true);
      window.visualViewport?.removeEventListener?.("resize", positionPortaledMenu);
      window.visualViewport?.removeEventListener?.("scroll", positionPortaledMenu);
      menu.classList.remove?.("menu-open-flip");
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

    function visibleItems() {
      const query = String(search.value || "").trim().toLocaleLowerCase();
      const base = !query ? items : items.filter(item => (
        `${item.label} ${item.value} ${item.description}`
          .toLocaleLowerCase().includes(query)
      ));
      return base;
    }

    function setItems(nextItems, preserveSelected = false) {
      const preserved = preserveSelected
        ? items.filter(item => selected.includes(item.value)
          || committedSelected.includes(item.value))
        : [];
      items.splice(0, items.length, ...normalizeItems([
        ...preserved,
        ...(Array.isArray(nextItems) ? nextItems : []),
      ]).map(item => ({
        ...item,
        disabled: item.disabled || (typeof options.disabled === "function"
          ? Boolean(options.disabled(item)) : controlDisabled),
      })));
      selected = normalizeSelected(selected, items);
      if (!multi && selected.length > 1) selected = [selected[selected.length - 1]];
      committedSelected = preserveSelected
        ? normalizeSelected(committedSelected, items) : [...selected];
      render();
    }

    const remote = remoteFactory ? remoteFactory({
      context, options, controlDisabled, search, setItems,
      refresh: () => render(),
    }) : null;

    function render() {
      const remoteStatus = remote?.status?.() || {};
      const loading = Boolean(manualLoading || remoteStatus.loading);
      const errorText = manualErrorText || String(remoteStatus.errorText || "").trim();
      const statusText = manualStatusText;
      const emptyText = remoteStatus.empty
        ? translate(context, "没有匹配的候选") : "";
      const labels = labelsFor();
      const summaryValue = labels.length
        ? (labels.length === 1 ? labels[0] : countLabel(context, labels.length))
        : "";
      summaryText.textContent = loading
        ? (options.loadingText || translate(context, "正在读取候选…"))
        : errorText || statusText || emptyText || summaryValue || translate(context, "未筛选");
      summary.classList.toggle?.("is-disabled", controlDisabled);
      if (controlDisabled) summary.setAttribute("aria-disabled", "true");
      else summary.removeAttribute?.("aria-disabled");
      summary.classList.toggle?.("is-loading", loading);
      summary.classList.toggle?.("is-error", Boolean(errorText));
      selectedLabel.textContent = labels.length ? labels.join("、")
        : translate(context, "未筛选");
      summary.title = controlDisabled && disabledReason
        ? disabledReason : errorText || labels.join("、");
      remote?.render();
      clear.hidden = !String(search.value || "");
      optionList.replaceChildren(...buildMenuSections());
    }
    // Rebuild list rows: collapsible 已选 section, 排他 section (an optional
    // caller-declared hand-typed exclusive entry), then the other candidates.
    // Selected rows reappear in the other-candidates section with the
    // is-selected visual; clicking a row toggles it (multi keeps the change
    // until the outside click commits, single commits immediately).
    var selectedCollapsed = false;
    var exclusiveCollapsed = false;
    var onsiteCollapsed = false;
    var othersCollapsed = false;
    // Per-type collapse state (each defaults to collapsed) for the multi-type
    // 候选（××类型） groups so they can fold independently.
    const groupedCollapsed = new Map();
    // Add a typed on-the-fly candidate: the per-type 「候选（××类型）」 heading "+"
    // delegates to the caller's onAddCandidateForType(type, context, {add}).
    // The pushed row carries `type` so it lands in (and stays in) that type's
    // 候选 group; it is never surfaced into a separate 当场 section.
    function addTypedCandidate(key) {
      if (typeof options.onAddCandidateForType !== "function") return;
      const add = value => {
        if (!value || typeof value !== "object") return;
        const ref = String(
          value.value ?? value.ref ?? value.id ?? value.factor_ref ?? "",
        ).trim();
        const valueKey = ref || String(value.label || value.alias || "").trim();
        if (!valueKey) return;
        if (items.some(item => (
          String(item.value ?? item.ref ?? item.id ?? "").trim() === valueKey
          || (item.label || "").trim() === valueKey
        ))) return;
        items.push({
          ...value,
          value: valueKey,
          type: key,
          onsite: true,
          temporary: true,
          label: value.label || value.alias || valueKey,
        });
        if (!multi) {
          selected = [valueKey];
          committedSelected = [...selected];
        }
        render();
      };
      options.onAddCandidateForType(key, context, {add, close: () => {}});
    }
    function buildMenuSections() {
      const shown = visibleItems();
      const rows = [];
      const buildRow = item => {
        const row = document.createElement("label");
        row.className = "ft-multi-select-option";
        if (selected.includes(item.value)) row.classList.add("is-selected");
        if (item.exclusive) row.classList.add("is-exclusive");
        if (item.disabled) row.classList.add("is-disabled");
        row.setAttribute("aria-label", `${item.label}：${item.description}`);
        const input = document.createElement("input");
        input.type = multi ? "checkbox" : "radio";
        if (!multi) input.name = singleGroupName;
        input.value = item.value;
        input.checked = selected.includes(item.value);
        input.disabled = item.disabled;
        input.dataset.filterValue = item.value;
        const label = document.createElement("span");
        label.className = "ft-multi-select-option-label";
        label.textContent = item.label;
        const info = optionHelp(context, item, {...options, updateTemporaryCandidate});
        info.classList.add("ft-multi-select-option-info");
        row.append(input, label, " ");
        if (item.onsite === true) {
          // Delete icon sits to the LEFT of the row's "?" (view overlay) so the
          // on-the-fly object is removed without entering its view overlay.
          const del = window.FTUI?.iconButton
            ? window.FTUI.iconButton(
              context, "trash", translate(context, "删除", "删除"),
              () => removeTemporaryCandidate(item),
              {className: "ft-multi-select-option-remove"},
            )
            : null;
          if (del) row.append(del, " ");
        }
        row.append(info);
        if (item.exclusive) {
          const badge = document.createElement("span");
          badge.className = "ft-multi-select-exclusive-badge";
          badge.textContent = translate(context, "排他项", "排他");
          label.append(" ", badge);
        }
        if (item.onsite || item.temporary === true) {
          const badge = document.createElement("span");
          badge.className = "ft-multi-select-onsite-badge";
          badge.textContent = translate(context, "当场", "当场");
          label.append(" ", badge);
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
            event.stopPropagation?.();
            action.onClick?.(event, item);
          });
          actionHost.append(button);
        }
        if (actionHost.childElementCount) row.append(actionHost);
        function selectionAfterToggle() {
          const isSelected = selected.includes(item.value);
          if (!multi) return isSelected ? [] : [item.value];
          if (isSelected) return selected.filter(value => value !== item.value);
          if (item.exclusive) return [item.value];
          return [
            ...selected.filter(value => !itemFor(value)?.exclusive),
            item.value,
          ];
        }
        function selectionAfterNativeChange() {
          if (!input.checked) return selected.filter(value => value !== item.value);
          if (!multi) return [item.value];
          if (item.exclusive) return [item.value];
          return [
            ...selected.filter(value => value !== item.value
              && !itemFor(value)?.exclusive),
            item.value,
          ];
        }
        async function commitSingle(next) {
          const previous = [...committedSelected];
          selected = [...next];
          dropdown.open = false;
          restoreMenu();
          render();
          try {
            const commit = options.onChange || options.onApply;
            const result = commit?.([...next]);
            if (result && typeof result.then === "function") await result;
            committedSelected = [...next];
          } catch (error) {
            selected = previous;
            render();
            context.showNotice?.(
              error.message || translate(context, "应用失败"), true,
            );
          }
        }
        let clickHandled = false;
        input.addEventListener("click", event => {
          if (item.disabled) return;
          event.preventDefault();
          clickHandled = true;
          const next = selectionAfterToggle();
          if (!multi) {
            void commitSingle(next);
            return;
          }
          selected = next;
          render();
        });
        input.addEventListener("change", () => {
          if (clickHandled) {
            clickHandled = false;
            return;
          }
          if (item.disabled) return;
          const next = selectionAfterNativeChange();
          if (!multi) {
            void commitSingle(next);
            return;
          }
          selected = next;
          render();
        });
        return row;
      };
      function sectionHeading(text, collapsed, onToggle, onAdd) {
        const head = document.createElement("div");
        head.className = "ft-multi-select-section-heading";
        const marker = document.createElement("span");
        marker.className = "ft-multi-select-section-marker";
        marker.textContent = collapsed ? "▸" : "▾";
        const title = document.createElement("span");
        title.textContent = text;
        head.append(marker, title);
        if (onAdd) {
          const add = document.createElement("button");
          add.type = "button";
          add.className = "ft-multi-select-section-add icon-action-button";
          const addTitle = translate(context, "当场新增", "当场新增");
          add.title = addTitle;
          add.setAttribute("aria-label", addTitle);
          add.addEventListener("click", event => {
            event.preventDefault();
            event.stopPropagation?.();
            onAdd();
          });
          const plusNode = window.FTIcons?.node?.("plus");
          if (plusNode) add.replaceChildren?.(plusNode); else add.textContent = "+";
          head.append(add);
        }
        head.addEventListener("click", event => {
          event.preventDefault();
          event.stopPropagation?.();
          onToggle();
        });
        return head;
      }
      const wrap = (rows, className) => {
        const box = document.createElement("div");
        box.className = className;
        for (const row of rows) box.append(row);
        return box;
      };
      const selectedItems = items.filter(item => selected.includes(item.value));
      if (selectedItems.length) {
        const head = sectionHeading(
          `${translate(context, "已选", "已选")} (${selectedItems.length})`,
          selectedCollapsed,
          () => { selectedCollapsed = !selectedCollapsed; render(); },
        );
        rows.push(head);
        if (!selectedCollapsed) {
          rows.push(wrap(
            selectedItems.map(item => buildRow(item)),
            "ft-multi-select-section-selected",
          ));
        }
      }
      const exclusiveShown = shown.filter(item => item.exclusive);
      if (exclusiveShown.length || options.exclusiveManual) {
        rows.push(sectionHeading(
          translate(context, "排他", "排他"),
          exclusiveCollapsed,
          () => { exclusiveCollapsed = !exclusiveCollapsed; render(); },
        ));
        if (!exclusiveCollapsed) {
          if (exclusiveShown.length) {
            rows.push(wrap(
              exclusiveShown.map(item => buildRow(item)),
              "ft-multi-select-section-exclusive",
            ));
          }
          if (options.exclusiveManual) {
          const manualRow = document.createElement("label");
          manualRow.className = "ft-multi-select-option ft-multi-select-exclusive ft-multi-select-manual-exclusive";
          const input = document.createElement("input");
          input.type = "text";
          input.placeholder = options.exclusiveManual.placeholder
            || options.exclusiveManual.label
            || translate(context, "手填排他项…", "手填排他项…");
          input.disabled = controlDisabled;
          const confirm = () => {
            const raw = String(input.value || "").trim();
            input.value = "";
            if (!raw) return;
            let item = itemFor(raw) || items.find(candidate => (
              String(candidate.label || "") === raw
            ));
            if (!item) {
              item = {
                value: raw, label: raw, exclusive: true,
                description: translate(context, "手填排他项", "手填排他项"),
              };
              items.push(item);
            }
            if (!multi) {
              selected = [item.value];
              void (async () => {
                dropdown.open = false;
                restoreMenu();
                render();
                try {
                  const commit = options.onChange || options.onApply;
                  const result = commit?.([item.value]);
                  if (result && typeof result.then === "function") await result;
                  committedSelected = [item.value];
                } catch (error) {
                  context.showNotice?.(
                    error.message || translate(context, "应用失败"), true,
                  );
                }
              })();
              return;
            }
            selected = [item.value];
            render();
          };
          input.addEventListener("keydown", event => {
            event.stopPropagation?.();
            if (event.key === "Enter") confirm();
          });
          input.addEventListener("blur", () => {
            if (String(input.value || "").trim()) confirm();
          });
          manualRow.append(input);
          rows.push(wrap([manualRow], "ft-multi-select-section-exclusive"));
        }
      }
      }
      // 当场区 only exists for a single-type (non-grouped) picker; typed
      // on-the-fly candidates stay in their type's 候选 group when grouping.
      const onsiteItems = shown.filter(item => item.onsite === true && !item.exclusive);
      if (!candidateGrouped && onsiteItems.length) {
        rows.push(sectionHeading(
          `${translate(context, "当场", "当场")} (${onsiteItems.length})`,
          onsiteCollapsed,
          () => { onsiteCollapsed = !onsiteCollapsed; render(); },
        ));
        if (!onsiteCollapsed) {
          rows.push(wrap(
            onsiteItems.map(item => buildRow(item)),
            "ft-multi-select-section-onsite",
          ));
        }
      }
      // When grouping, all candidates (incl. typed on-the-fly ones) go into
      // their per-type section; when not grouping, on-the-fly items are shown
      // in the 当场 section above.
      const others = shown.filter(item => (
        !item.exclusive && (candidateGrouped || item.onsite !== true)
      ));
      if (others.length) {
        if (candidateGrouped) {
          const grouped = new Map();
          for (const item of others) {
            const key = typeOf(item);
            if (!grouped.has(key)) grouped.set(key, []);
            grouped.get(key).push(item);
          }
          for (const [key, list] of grouped) {
            const baseLabel = translate(context, "候选", "候选");
            const label = key
              ? `${baseLabel}（${typeLabelOf(key, list[0])}）`
              : baseLabel;
            const typeCollapsed = groupedCollapsed.get(key) ?? true;
            rows.push(sectionHeading(
              `${label} (${list.length})`,
              typeCollapsed,
              () => {
                groupedCollapsed.set(key, !(groupedCollapsed.get(key) ?? true));
                render();
              },
              (typeof options.onAddCandidateForType === "function" && key
                && (typeof options.canAddForType !== "function"
                  || options.canAddForType(key)))
                ? () => addTypedCandidate(key) : undefined,
            ));
            if (!typeCollapsed) {
              rows.push(wrap(list.map(item => buildRow(item)), "ft-multi-select-section-others"));
            }
          }
        } else {
          rows.push(sectionHeading(
            `${translate(context, "候选", "候选")} (${others.length})`,
            othersCollapsed,
            () => { othersCollapsed = !othersCollapsed; render(); },
          ));
          if (!othersCollapsed) {
            rows.push(wrap(others.map(item => buildRow(item)), "ft-multi-select-section-others"));
          }
        }
      }
      return rows;
    }
    // Commit-on-outside-close for multi: no explicit apply button.
    async function commitMultiOnClose() {
      if (applying || controlDisabled) return;
      applying = true;
      try {
        const changed = JSON.stringify(selected)
          !== JSON.stringify(committedSelected);
        if (!changed) return;
        let result;
        if (typeof options.onApply === "function") {
          result = options.onApply([...selected]);
        } else {
          result = options.onChange?.([...selected]);
        }
        if (result && typeof result.then === "function") await result;
        committedSelected = [...selected];
      } catch (error) {
        selected = [...committedSelected];
        render();
        context.showNotice?.(error.message || translate(context, "应用失败"), true);
      } finally {
        applying = false;
      }
    }

    clear.addEventListener("click", () => {
      search.value = "";
      render();
      search.focus?.();
    });
    // Typing only narrows the candidates below (已选 stays untouched).
    search.addEventListener("input", () => render());
    // Delete an on-the-fly candidate: pull it from the pool and selection
    // states, then let the caller release any view overlay / state.
    function removeTemporaryCandidate(item) {
      if (!item) return;
      const index = items.indexOf(item);
      if (index >= 0) items.splice(index, 1);
      selected = selected.filter(value => value !== item.value);
      committedSelected = committedSelected.filter(value => value !== item.value);
      render();
      options.onTemporaryCandidateRemoved?.(item);
      options.onChange?.([...committedSelected]);
    }

    function updateTemporaryCandidate(item, saved) {
      const index = items.indexOf(item);
      if (index < 0 || !saved) return;
      const value = String(saved.factor_ref || saved.ref || saved.family_ref
        || saved.group_ref || saved.strategy_ref || saved.id || item.value);
      const next = {...item, value,
        label: saved.alias || saved.factor_alias || saved.name || saved.title_zh || item.label,
        view: {...item.view, ref: value, initialValue: saved}};
      for (const key of ["factor", "family", "factorSet", "group", "category", "strategy"]) {
        if (item[key] !== undefined) next[key] = saved;
      }
      items[index] = next;
      selected = selected.map(ref => ref === item.value ? value : ref);
      committedSelected = committedSelected.map(ref => ref === item.value ? value : ref);
      options.onTemporaryCandidateUpdated?.(item, next, saved);
      options.onChange?.([...committedSelected]);
      render();
    }

    // On-the-fly object lifecycle is fully managed by the row's delete ("×")
    // icon; there is no automatic sweep on menu close.  When the hosting tab /
    // page unmounts, the candidates are released with the component memory.

    // Outside click / collapse commits multi selections (no apply button);
    // single mode already commits on each pick.
    const holdOpen = () => { try { dropdown.open = false; } catch (_error) {} };
    dropdown.addEventListener("toggle", () => {
      const settingsShell = section.closest
        ? section.closest('[class*="settings-shell"]')
        : null;
      if (settingsShell) {
        settingsShell.classList.toggle("has-open-multi-select", dropdown.open);
      }
      if (dropdown.open) {
        // Mutual exclusion: opening one dropdown collapses any previously-open
        // one, page-wide (handles the same-tab / same-shell / parameter-table
        // cases uniformly).
        if (activeMultiSelect && activeMultiSelect !== holdOpen) {
          try { activeMultiSelect(); } catch (_error) { /* already closed */ }
        }
        activeMultiSelect = holdOpen;
        // Lazy catalog owners attach their loader here. Keep opening fast,
        // then let their refresh callback rebuild the host with loaded items.
        try {
          const opened = options.onOpen?.(context);
          if (opened && typeof opened.catch === "function") opened.catch(() => {});
        } catch (_error) { /* the owner renders its own load error state */ }
        // One viewport-relative positioning path for every host. Popover
        // supplies the top layer; the portal is the older-browser fallback.
        if (canPortalMenu()) {
          if (!menuPortaled) portalMenu();
          return;
        }
        return;
      }
      restoreMenu();
      if (activeMultiSelect === holdOpen) activeMultiSelect = null;
      if (multi && !applying) void commitMultiOnClose();
    });
    // A disabled control never opens (native details toggling suppressed).
    summary.addEventListener("click", event => {
      if (!controlDisabled) return;
      event.preventDefault();
      if (dropdown.open) dropdown.open = false;
    });

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
      get hasSelection() { return selected.length > 0; },
      get multi() { return multi; },
      setValues(values) {
        selected = normalizeSelected(values, items);
        if (!multi && selected.length > 1) selected = [selected[selected.length - 1]];
        committedSelected = [...selected];
        render();
      },
      setItems,
      setStatus(next = {}) {
        if (Object.prototype.hasOwnProperty.call(next, "loading")) {
          manualLoading = Boolean(next.loading);
          controlDisabled = manualLoading || configuredDisabled;
        }
        manualStatusText = String(next.text || "").trim();
        manualErrorText = String(next.errorText || "").trim();
        render();
      },
    });
  }

  window.FTMultiSelectFilter = Object.freeze({create, normalizeItems});
})();
