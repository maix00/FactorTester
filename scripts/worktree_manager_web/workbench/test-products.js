(() => {
  function groupID(value) {
    return value?.group_ref || value?.product_group_ref || value?.id
      || value?.product_group_template_id || value?.product_path_selection_id || "";
  }

  function groupLabel(value) {
    return value?.title_zh || value?.name || value?.label || groupID(value);
  }

  function projection(group) {
    const id = groupID(group);
    const paths = [...(group?.paths || group?.selected_paths || [])];
    return {
      product_path_selection_id: id,
      product_group_template_id: id,
      label: groupLabel(group),
      selected_paths: paths,
      paths,
    };
  }

  function referenceOf(value) {
    return typeof value === "string" ? value : groupID(value);
  }

  function uniqueReferences(values) {
    return [...new Set((values || []).map(referenceOf).filter(Boolean))];
  }

  function restoreReferences(analysis = {}, ui = {}) {
    const values = [
      ...(ui.product_group_refs || []),
      ...(analysis.product_path_selections || []),
      ...(analysis.local_settings?.product_path_selections || []),
      analysis.product_path_selection,
      analysis.product_path_selection_id,
      analysis.local_settings?.product_group_ref,
      ui.product_group_ref,
    ];
    return uniqueReferences(values);
  }

  function synchronize(state) {
    const saved = uniqueReferences(state.values?.product_path_selections || []);
    if (state.kind === "ic") {
      state.groupRefs = uniqueReferences(state.groupRefs?.length ? state.groupRefs : saved);
      state.groupRef = state.groupRefs[0] || "";
    } else {
      state.groupRef = state.groupRef || saved[0] || "";
      state.groupRefs = state.groupRef ? [state.groupRef] : [];
    }
    if (state.values) {
      state.values.product_path_candidates = state.groups.map(projection);
      state.values.product_path_selections = selectedGroups(state).map(projection);
    }
    return state.groupRefs;
  }

  function selectedGroups(state) {
    const selected = new Set(state.kind === "ic" ? state.groupRefs : [state.groupRef]);
    return state.groups.filter(group => selected.has(groupID(group)));
  }

  function selectedProjections(state) {
    return selectedGroups(state).map(projection);
  }

  function setSelected(state, group, checked) {
    const id = groupID(group);
    if (state.kind === "ic") {
      const refs = new Set(state.groupRefs || []);
      if (checked) refs.add(id); else refs.delete(id);
      state.groupRefs = [...refs];
    } else {
      state.groupRef = checked ? id : "";
    }
    synchronize(state);
  }

  function selectNew(state, group) {
    setSelected(state, group, true);
  }

  function panel(context, state, refresh) {
    const root = document.createElement("div");
    root.className = "test-product-manager";
    root.append(state.kind === "ic"
      ? multiplePanel(context, state, refresh)
      : singlePanel(context, state, refresh));
    const toolbar = document.createElement("div");
    toolbar.className = "test-product-manager-actions";
    toolbar.append(context.button(context.t("新建产品组"), () => {
      showCreator(context, state, root, refresh);
    }));
    root.append(toolbar);
    return root;
  }

  function multiplePanel(context, state, refresh) {
    const root = document.createElement("fieldset");
    root.className = "test-product-selector test-object-field";
    const legend = document.createElement("legend");
    legend.textContent = context.t("产品组");
    const note = document.createElement("small");
    note.textContent = context.t("每个产品组冻结并提交为独立任务；所选因子会在每个任务中共同计算");
    const list = document.createElement("div");
    list.className = "test-product-group-list";
    for (const group of state.groups) {
      const row = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = (state.groupRefs || []).includes(groupID(group));
      input.addEventListener("change", () => {
        setSelected(state, group, input.checked);
        refresh?.();
      });
      const copy = document.createElement("span");
      const title = document.createElement("b");
      title.textContent = groupLabel(group);
      const detail = document.createElement("small");
      const count = group.path_count ?? group.paths?.length ?? 0;
      detail.textContent = `${count} ${context.t("条产品路径")}`;
      copy.append(title, detail);
      row.append(input, copy);
      list.append(row);
    }
    if (!state.groups.length) list.append(FTUI.empty(context.t("暂无产品组"), ""));
    const unavailable = (state.groupRefs || []).filter(ref => (
      !state.groups.some(group => groupID(group) === ref)
    ));
    if (unavailable.length) {
      const warning = document.createElement("small");
      warning.className = "test-product-warning";
      warning.textContent = `${context.t("当前不可用的产品组")}: ${unavailable.join("、")}`;
      root.append(legend, note, list, warning);
    } else {
      root.append(legend, note, list);
    }
    return root;
  }

  function singlePanel(context, state, refresh) {
    const field = document.createElement("label");
    field.className = "test-product-selector test-object-field";
    const label = document.createElement("b");
    label.textContent = context.t("产品组");
    const select = document.createElement("select");
    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = `— ${context.t("产品组")} —`;
    select.append(empty);
    for (const group of state.groups) {
      const option = document.createElement("option");
      option.value = groupID(group);
      option.textContent = groupLabel(group);
      select.append(option);
    }
    select.value = state.groupRef;
    select.addEventListener("change", () => {
      state.groupRef = select.value;
      synchronize(state);
      refresh?.();
    });
    field.append(label, select);
    return field;
  }

  function showCreator(context, state, root, refresh) {
    root.querySelector(".test-inline-creator")?.remove();
    const form = document.createElement("form");
    form.className = "test-inline-creator";
    const name = document.createElement("input");
    name.required = true;
    name.placeholder = context.t("产品组名称");
    const paths = document.createElement("textarea");
    paths.required = true;
    paths.rows = 4;
    paths.placeholder = context.t("每行一个产品路径");
    const status = document.createElement("span");
    const save = context.button(context.t("创建并选中"), () => {});
    save.type = "submit";
    const cancel = context.button(context.t("取消"), () => form.remove());
    cancel.type = "button";
    form.append(name, paths, save, cancel, status);
    form.addEventListener("submit", async event => {
      event.preventDefault();
      const selectedPaths = paths.value.split(/\r?\n/)
        .map(value => value.trim()).filter(Boolean);
      if (!selectedPaths.length) {
        status.textContent = context.t("请填写至少一个产品路径");
        return;
      }
      try {
        const value = await context.api("/api/catalog/product-groups", {
          method: "POST",
          body: JSON.stringify({name: name.value.trim(), paths: selectedPaths}),
        });
        state.groups.push(value.group);
        selectNew(state, value.group);
        refresh?.();
      } catch (error) {
        status.textContent = error.message;
      }
    });
    root.append(form);
    name.focus();
  }

  window.FTTestProducts = Object.freeze({
    groupID, groupLabel, projection, restoreReferences, synchronize,
    selectedGroups, selectedProjections, setSelected, selectNew, panel,
  });
})();
