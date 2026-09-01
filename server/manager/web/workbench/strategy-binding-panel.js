(() => {
  function render(context, state, refresh) {
    FTTestInputState.initialize(state);
    const root = document.createElement("section");
    root.className = "strategy-binding-panel";
    const note = document.createElement("p");
    note.className = "strategy-binding-note";
    note.textContent = context.t("每个策略组可以绑定一个策略库版本，或只随本次配置保存的临时策略。");
    root.append(note);
    const groups = Array.isArray(state.analysis?.groups) ? state.analysis.groups : [];
    if (!groups.length) {
      root.append(FTUI.empty(context.t("暂无策略组"), context.t("请先添加策略组，再为策略组选择策略")));
      return root;
    }
    const rows = document.createElement("div");
    rows.className = "strategy-binding-rows";
    root.append(rows);
    const searchCache = new Map();
    const searchInFlight = new Map();
    const searchStrategies = query => {
      const normalized = String(query || "").trim().toLocaleLowerCase();
      if (searchCache.has(normalized)) return Promise.resolve(searchCache.get(normalized));
      if (searchInFlight.has(normalized)) return searchInFlight.get(normalized);
      const request = FTStrategyLibraryRuntime.search(context, normalized)
        .then(items => {
          const result = Array.isArray(items) ? items : [];
          searchCache.set(normalized, result);
          return result;
        })
        .finally(() => searchInFlight.delete(normalized));
      searchInFlight.set(normalized, request);
      return request;
    };
    const redraw = () => {
      rows.replaceChildren(...groups.map(group => bindingRow(
        context, state, group, searchStrategies, refresh, redraw,
      )));
    };
    redraw();
    return root;
  }

  function bindingRow(context, state, group, searchStrategies, refresh, redraw) {
    const root = document.createElement("div");
    root.className = "strategy-binding-row";
    const title = document.createElement("strong");
    title.textContent = group.name || group.id;
    root.append(title);
    const current = (state.strategyBindings || []).find(item => (
      item.target_strategy_id === group.id
    ));
    const values = strategyItems(state, [], current);
    const selected = current ? bindingValue(state, current, values) : "";
    const picker = FTTestObjectPicker.create(context, {
      title: context.t("策略"), name: `strategy-binding-${group.id}`,
      items: values, selected: selected ? [selected] : [], multi: false,
      note: context.t("打开下拉后按名称或引用搜索策略库；临时策略仅属于当前配置"),
      searchPlaceholder: context.t("搜索策略名称或引用…"),
      loadItems: async query => strategyItems(
        state, await searchStrategies(query), current,
      ),
      onChange: next => {
        const value = next[0] || "";
        if (!value) {
          if (current) FTTestInputState.removeStrategyBinding(
            state, current.binding_id,
          );
        } else {
          const parsed = parseValue(value);
          const selectedItem = values.find(item => item.value === value);
          FTTestInputState.putStrategyBinding(state, {
            binding_id: current?.binding_id || newID("binding"),
            target_strategy_id: group.id,
            source: parsed.kind === "inline"
              ? {kind: "inline", temp_ref: parsed.temp_ref}
              : {
                kind: "library", strategy_ref: parsed.strategy_ref,
                revision_ref: parsed.revision_ref,
                ...(selectedItem?.source_sha256
                  ? {source_sha256: selectedItem.source_sha256} : {}),
              },
          });
        }
        refresh?.();
      },
      onCreate: () => openInline(context, state, group.id, refresh, redraw),
      createLabel: context.t("新建临时策略"),
    });
    root.append(picker.element);
    return root;
  }

  function strategyItems(state, candidates, current) {
    const result = candidates.map(item => ({
      value: `library::${item.strategy_ref}::${item.current_revision_ref}`,
      label: item.name || item.strategy_ref,
      description: `${item.owner_ref || ""} · r${item.current_revision?.revision_number || "—"}`,
      source_sha256: item.current_revision?.source_sha256 || "",
    }));
    for (const item of state.temporaryStrategies || []) {
      result.push({
        value: `inline::${item.temp_ref}`,
        label: item.name || item.temp_ref,
        description: `临时策略 · ${item.entrypoint || "Strategy"}`,
      });
    }
    const source = current?.source || {};
    if (source.kind === "library") {
      const value = `library::${source.strategy_ref}::${source.revision_ref}`;
      if (!result.some(item => item.value === value)) {
        result.push({
          value,
          label: source.strategy_ref || "已冻结策略",
          description: `已冻结版本 · ${source.revision_ref || "—"}`,
          source_sha256: source.source_sha256 || "",
        });
      }
    } else if (source.kind === "inline" && source.temp_ref
        && !result.some(item => item.value === `inline::${source.temp_ref}`)) {
      result.push({
        value: `inline::${source.temp_ref}`,
        label: "临时策略（源码缺失）",
        description: "当前配置引用的临时策略未能恢复",
      });
    }
    return result;
  }

  function bindingValue(state, binding, values) {
    const source = binding.source || {};
    const value = source.kind === "inline"
      ? `inline::${source.temp_ref}`
      : `library::${source.strategy_ref}::${source.revision_ref}`;
    return values.some(item => item.value === value) ? value : "";
  }

  function parseValue(value) {
    const [kind, first, second] = String(value).split("::");
    return kind === "inline"
      ? {kind, temp_ref: first}
      : {kind: "library", strategy_ref: first, revision_ref: second};
  }

  async function openInline(context, state, target, refresh, redraw) {
    if (!window.FTStrategyLibraryEditor?.create) {
      await window.FTStaticLoader?.loadGroups?.(["strategy-library-editor-core"]);
    }
    if (window.FTStrategyLibraryEditor?.create) {
      return openInlineEditor(context, state, target, refresh, redraw);
    }
    const dialog = document.createElement("dialog");
    dialog.className = "strategy-inline-dialog";
    const card = document.createElement("form");
    card.className = "dialog-card wide";
    card.addEventListener("submit", async event => {
      event.preventDefault();
      submit.disabled = true;
      try {
        const inspected = await context.api("/api/run-inputs/strategy/inspect", {
          method: "POST",
          body: JSON.stringify({
            path: `configuration/strategies/${Date.now()}.py`,
            source_code: source.value(), entrypoint: entrypoint.value.trim(),
          }),
        });
        if (!inspected.valid) throw new Error(inspected.error || context.t("策略源码无法通过校验"));
        const tempRef = newID("temporary-strategy");
        FTTestInputState.putInlineStrategy(state, {
          temp_ref: tempRef,
          name: name.value.trim(),
          entrypoint: inspected.entrypoint || entrypoint.value.trim(),
          source_code: source.value(),
          source_sha256: inspected.source_sha256 || "",
          hooks: inspected.hooks || [],
          requirements: inspected.requirements || {},
        }, {
          binding_id: newID("binding"),
          target_strategy_id: target,
          source: {kind: "inline", temp_ref: tempRef},
        });
        dialog.close();
        refresh?.(); redraw?.();
      } catch (error) {
        errorNode.textContent = error.message || context.t("策略源码无法通过校验");
        submit.disabled = false;
      }
    });
    const title = document.createElement("h2"); title.textContent = context.t("新建临时策略");
    const name = textField(context, "策略名称", true);
    const entrypoint = textField(context, "入口类", true); entrypoint.value = "Strategy";
    const sourceEditor = FTUI.codeEditor("", {language: "python", required: true, ariaLabel: context.t("Python 策略源码")});
    const source = sourceEditor;
    const errorNode = document.createElement("small"); errorNode.className = "form-error";
    const actions = document.createElement("div"); actions.className = "dialog-actions";
    const cancel = FTUI.actionButton(context.t("取消"), () => dialog.close(), {variant: "secondary"});
    const submit = FTUI.actionButton(context.t("添加到当前配置"), null, {variant: "primary"});
    submit.type = "submit";
    actions.append(cancel, submit);
    card.append(title, row(context, "策略名称", name), row(context, "入口类", entrypoint), row(context, "Python 源码", source.element), errorNode, actions);
    dialog.append(card); document.body.append(dialog); dialog.addEventListener("close", () => dialog.remove()); dialog.showModal();
  }

  function openInlineEditor(context, state, target, refresh, redraw) {
    const dialog = document.createElement("dialog");
    dialog.className = "strategy-inline-dialog";
    const editor = FTStrategyLibraryEditor.create(context, {}, {
      mode: "create",
      storageMode: "configuration-inline",
      onSubmit: async (draft, status) => {
        const submit = dialog.querySelector('[type="submit"]');
        if (submit) submit.disabled = true;
        try {
          const inspected = await context.api("/api/run-inputs/strategy/inspect", {
            method: "POST",
            body: JSON.stringify({
              path: `configuration/strategies/${Date.now()}.py`,
              source_code: draft.source_code,
              entrypoint: draft.entrypoint,
            }),
          });
          if (!inspected.valid) {
            throw new Error(inspected.error || context.t("策略源码无法通过校验"));
          }
          const tempRef = newID("temporary-strategy");
          FTTestInputState.putInlineStrategy(state, {
            temp_ref: tempRef,
            name: draft.name.trim(),
            entrypoint: inspected.entrypoint || draft.entrypoint,
            source_code: draft.source_code,
            source_sha256: inspected.source_sha256 || "",
            hooks: inspected.hooks || [],
            requirements: inspected.requirements || {},
          }, {
            binding_id: newID("binding"),
            target_strategy_id: target,
            source: {kind: "inline", temp_ref: tempRef},
          });
          dialog.close();
          refresh?.();
          redraw?.();
        } catch (error) {
          status.textContent = error.message || context.t("策略源码无法通过校验");
          if (submit) submit.disabled = false;
        }
      },
    });
    const title = document.createElement("h2");
    title.textContent = context.t("新建临时策略");
    const actions = document.createElement("div");
    actions.className = "dialog-actions";
    const cancel = FTUI.actionButton(
      context.t("取消"), () => dialog.close(), {variant: "secondary"},
    );
    const submit = FTUI.actionButton(
      context.t("添加到当前配置"), null, {variant: "primary"},
    );
    submit.type = "submit";
    actions.append(cancel, submit);
    editor.form.prepend(title);
    editor.form.append(actions);
    dialog.append(editor.form);
    document.body.append(dialog);
    dialog.addEventListener("close", () => dialog.remove(), {once: true});
    dialog.showModal();
  }

  function textField(context, label, required) {
    const input = document.createElement("input");
    input.type = "text"; input.required = required; input.placeholder = context.t(label); input.setAttribute("aria-label", context.t(label));
    return input;
  }

  function row(context, label, control) {
    const root = document.createElement("label"); root.className = "strategy-binding-field";
    const title = document.createElement("span"); title.textContent = context.t(label); root.append(title, control); return root;
  }

  function newID(prefix) {
    const randomUUID = globalThis.crypto?.randomUUID;
    const suffix = typeof randomUUID === "function"
      ? randomUUID.call(globalThis.crypto)
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    return `${prefix}:${suffix}`;
  }

  window.FTStrategyBindingPanel = Object.freeze({render});
})();
