(() => {
  // Internal adapter for repeated strategy rows.  The backend surface decides
  // what an item means; this module only supplies the old list interaction:
  // batches, disclosure, selection, chips and row actions.
  function render(options = {}) {
    const root = document.createElement("section");
    root.className = options.className || "strategy-list";
    const heading = document.createElement("header");
    heading.className = "strategy-list-heading";
    const title = document.createElement("strong");
    title.textContent = options.title || "";
    const count = document.createElement("small");
    count.textContent = options.count || "";
    heading.append(title, count);
    if (options.showConfig !== false) {
      const toggle = button(
        options.context, options.showConfigOpen ? "收起设置" : "显示设置",
        () => options.onToggleConfig?.(!options.showConfigOpen),
      );
      toggle.className = "strategy-list-config-toggle";
      toggle.setAttribute("aria-pressed", String(Boolean(options.showConfigOpen)));
      heading.append(toggle);
    }
    root.append(heading);
    const batches = normalizeBatches(options);
    if (!batches.length) {
      root.append(options.empty || empty("暂无策略", "先创建一个策略条目"));
      return root;
    }
    for (const batch of batches) root.append(renderBatch(batch, options));
    return root;
  }

  function renderBatch(batch, options) {
    const shell = document.createElement("section");
    shell.className = "strategy-list-batch";
    shell.dataset.batchKey = batch.key;
    const expanded = batch.expanded !== false;
    const header = document.createElement("div");
    header.className = `strategy-list-batch-header${batch.selected ? " selected" : ""}`;
    const body = document.createElement("div");
    body.className = "strategy-list-batch-body";
    body.id = `strategy-list-batch-${batch.key}`;
    body.hidden = !expanded;
    const disclosure = button(options.context, expanded ? "▾" : "▸", event => {
      event?.preventDefault?.();
      event?.stopPropagation?.();
      const next = body.hidden;
      body.hidden = !next;
      disclosure.textContent = next ? "▾" : "▸";
      disclosure.title = tx(options, next ? "收起添加批次" : "展开添加批次");
      disclosure.setAttribute("aria-expanded", String(next));
      options.onToggleBatch?.(batch.key, next);
    });
    disclosure.className = "strategy-list-disclosure";
    disclosure.title = tx(options, expanded ? "收起添加批次" : "展开添加批次");
    disclosure.setAttribute("aria-expanded", String(expanded));
    disclosure.setAttribute("aria-controls", `strategy-list-batch-${batch.key}`);
    const select = options.batchSelection === false
      ? document.createElement("span") : selection(options, batch, true);
    const copy = document.createElement("span");
    copy.className = "strategy-list-batch-copy";
    const label = document.createElement("b");
    label.textContent = batch.label || batch.key;
    copy.append(label);
    if (batch.description) {
      const note = document.createElement("small");
      note.textContent = batch.description;
      copy.append(note);
    }
    header.append(select, copy);
    if (batch.actions) header.append(actions(batch.actions, options));
    header.append(disclosure);
    shell.append(header);
    for (const item of batch.items || []) body.append(renderItem(item, options));
    shell.append(body);
    return shell;
  }

  function renderItem(item, options) {
    const row = document.createElement("div");
    row.className = `strategy-list-row${item.selected ? " selected" : ""}`;
    row.dataset.strategyId = item.key;
    row.style.setProperty("--strategy-depth", String(item.depth || 0));
    const branch = document.createElement("span");
    branch.className = "strategy-list-branch";
    const hasChildren = Boolean(item.hasChildren || (item.children || []).length);
    if (hasChildren) {
      const disclosure = button(options.context, item.expanded === false ? "▸" : "▾", () => (
        options.onToggleItem?.(item.key, item.expanded === false)
      ));
      disclosure.className = "strategy-list-disclosure strategy-list-item-disclosure";
      disclosure.title = tx(options, item.expanded === false ? "展开子策略" : "收起子策略");
      branch.append(disclosure);
    }
    const select = selection(options, item, false);
    const copy = document.createElement("span");
    copy.className = "strategy-list-item-copy";
    const name = item.editableName
      ? inlineName(item, options)
      : document.createElement("b");
    if (!item.editableName) name.textContent = item.label || item.key;
    copy.append(name);
    row.append(branch, select, copy);
    if (options.showConfigOpen && item.chips) row.append(chips(item.chips));
    if (item.actions) row.append(actions(item.actions, options));
    if (item.content) row.append(item.content);
    return row;
  }

  function inlineName(item, options) {
    const host = document.createElement("span");
    host.className = "strategy-list-name-editor";
    const label = String(item.label || item.key);
    const display = document.createElement("button");
    display.type = "button";
    display.className = "strategy-list-name";
    display.textContent = label;
    display.title = tx(options, "点击名称直接编辑，按 Enter 或离开输入框保存");
    display.setAttribute("aria-label", tx(options, "编辑策略名称"));
    host.append(display);

    const edit = () => {
      if (host.dataset.editing === "true") return;
      host.dataset.editing = "true";
      const input = document.createElement("input");
      input.className = "strategy-list-name-input";
      input.type = "text";
      input.value = label;
      input.title = tx(options, "按 Enter 或离开输入框保存，按 Escape 取消");
      input.setAttribute("aria-label", tx(options, "策略名称"));
      let settled = false;
      let cancelled = false;
      const restore = () => {
        host.dataset.editing = "false";
        host.replaceChildren(display);
      };
      const commit = () => {
        if (settled || cancelled) return;
        settled = true;
        const next = input.value.trim();
        if (!next || next === label.trim()) {
          restore();
          return;
        }
        try {
          const result = item.onRename?.(next);
          if (result && typeof result.then === "function") {
            result.then(() => restore()).catch(error => {
              input.setCustomValidity(error.message || tx(options, "策略名称保存失败"));
              input.reportValidity?.();
              input.setCustomValidity("");
              restore();
            });
          } else if (result === false) {
            restore();
          } else {
            restore();
          }
        } catch (error) {
          input.setCustomValidity(error.message || tx(options, "策略名称保存失败"));
          input.reportValidity?.();
          input.setCustomValidity("");
          restore();
        }
      };
      input.addEventListener("keydown", event => {
        if (event.key === "Enter") {
          event.preventDefault();
          input.blur();
        }
        if (event.key === "Escape") {
          event.preventDefault();
          cancelled = true;
          settled = true;
          restore();
        }
      });
      input.addEventListener("blur", commit);
      host.replaceChildren(input);
      input.focus?.();
      input.select?.();
    };
    display.addEventListener("click", edit);
    return host;
  }

  function selection(options, item, batch) {
    if (options.selection === "none") return document.createElement("span");
    const input = document.createElement("input");
    input.type = options.selection === "single" ? "radio" : "checkbox";
    input.checked = Boolean(item.selected);
    input.title = tx(options, batch ? "选择整个添加批次" : "选择策略");
    input.addEventListener("change", () => {
      if (batch) options.onToggleBatchSelection?.(item, input.checked);
      else options.onToggle?.(item, input.checked);
    });
    return input;
  }

  function chips(value) {
    const host = document.createElement("div");
    host.className = "strategy-list-chips";
    if (isNode(value)) host.append(value);
    else for (const item of value || []) {
      if (isNode(item)) host.append(item);
    }
    return host;
  }

  function isNode(value) {
    return Boolean(value && typeof value === "object" && typeof value.append === "function");
  }

  function actions(items, options) {
    const host = document.createElement("span");
    host.className = "strategy-list-actions";
    for (const item of items || []) {
      const action = button(
        options.context, item.icon ? "" : (item.label || ""), item.onClick,
        item.title || item.label || "",
      );
      action.title = item.title || item.label || "";
      action.setAttribute("aria-label", item.label || item.title || "");
      action.className = `strategy-list-action ${item.className || ""}`.trim();
      if (item.icon && window.FTIcons?.node) {
        action.replaceChildren(window.FTIcons.node(item.icon));
      }
      if (item.disabled) action.disabled = true;
      host.append(action);
    }
    return host;
  }

  function normalizeBatches(options) {
    if (Array.isArray(options.batches)) return options.batches;
    const items = Array.isArray(options.items) ? options.items : [];
    return items.length ? [{key: "all", label: options.title || "策略", items}] : [];
  }

  function button(context, label, onClick, help = label) {
    const value = context?.button
      ? context.button(label, onClick, help)
      : document.createElement("button");
    value.type = "button";
    if (!value.textContent) value.textContent = label;
    if (!context?.button && onClick) value.addEventListener("click", onClick);
    return value;
  }

  function tx(options, value) {
    return options.context?.t ? options.context.t(value) : value;
  }

  function empty(title, copy) {
    const node = document.createElement("p");
    node.className = "strategy-list-empty";
    node.textContent = `${title}：${copy}`;
    return node;
  }

  window.FTStrategyList = Object.freeze({render});
})();
