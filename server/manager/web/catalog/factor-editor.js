(() => {
  const model = () => window.FTFactorModel;

  function familyAlias(value) {
    return String(
      value?.factor_family_alias || value?.family || value?.alias
      || value?.factor_family_name || value?.name || value?.id || "",
    ).trim();
  }

  function familyRef(value) {
    return String(
      value?.factor_family_ref || value?.family_ref || familyAlias(value),
    ).trim();
  }

  function familyItems(data) {
    const seen = new Set();
    return (data?.families || []).flatMap(item => {
      const value = familyRef(item);
      if (!value || seen.has(value)) return [];
      seen.add(value);
      return [{
        value,
        label: model().familyName(item) || value,
        description: [
          item.chinese_name || item.description || "",
          item.owner_alias || item.owner_username || "",
          item.factor_kind === "public" ? "公共因子家族" : "可见因子家族",
        ].filter(Boolean).join(" · "),
        family: item,
      }];
    });
  }

  // The catalog page and the workbench overlay must use the same selector.
  // The workbench wrapper only adds create/edit actions when it is available;
  // the catalog module still works standalone with the shared base control.
  function sharedPicker(context, options) {
    if (window.FTTestObjectPicker?.create) {
      return FTTestObjectPicker.create(context, options);
    }
    return FTMultiSelectFilter.create(context, options);
  }

  function sourceModePicker(context, state, redraw) {
    const picker = sharedPicker(context, {
      compact: true,
      name: "factor-source-mode",
      multi: false,
      items: [
        {
          value: "family",
          label: context.t("已有可见因子家族"),
          description: context.t("从因子库家族选择参数并登记一个因子"),
        },
        {
          value: "source",
          label: context.t("上传或编写因子家族源码"),
          description: context.t("校验源码并解析参数后保存到因子库"),
        },
      ],
      selected: [state.sourceMode],
      onChange: values => {
        state.sourceMode = values[0] || "family";
        state.inspection = state.sourceMode === "source"
          ? state.inspection : null;
        redraw();
      },
    });
    return field(context.t("因子来源"), picker.element);
  }

  function familyPicker(context, data, state, redraw) {
    const picker = sharedPicker(context, {
      compact: true,
      name: "factor-family-source",
      title: context.t("因子家族"),
      multi: false,
      items: familyItems(data),
      selected: state.family ? [familyRef(state.family)] : [],
      onChange: values => {
        state.family = familyItems(data).find(item => item.value === values[0])?.family || null;
        state.parameterValues = defaults(state.family?.params || []);
        state.inspection = null;
        redraw();
      },
    });
    return field(context.t("因子家族"), picker.element);
  }

  function defaults(parameters) {
    return Object.fromEntries((parameters || []).map(parameter => [
      parameter.alias || parameter.name,
      parameter.value ?? parameter.default_value ?? "",
    ]).filter(([alias]) => alias));
  }

  function parameters(state) {
    if (state.familyMode) return [];
    if (state.sourceMode === "source") return state.inspection?.params || [];
    return state.family?.params || [];
  }

  function parameterEditor(context, state) {
    const list = parameters(state);
    if (!list.length) return null;
    return window.FTFactorDetailShared.parameterEditor(
      context, list, state.parameterValues,
    );
  }

  function filePicker(context, state, redraw) {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".py,text/x-python";
    input.hidden = true;
    input.addEventListener("change", async () => {
      const file = input.files?.[0];
      input.value = "";
      if (!file) return;
      state.sourceCode = await file.text();
      state.inspection = null;
      redraw();
    });
    return input;
  }

  async function inspect(context, state, redraw, status) {
    if (!state.sourceCode.trim()) {
      status.textContent = context.t("源码不能为空");
      return;
    }
    state.inspecting = true;
    status.textContent = context.t("正在校验源码并解析参数…");
    try {
      const value = await context.api("/custom-factors/api/validate", {
        method: "POST",
        body: JSON.stringify({source_code: state.sourceCode}),
      });
      if (!value.valid) throw new Error(value.error || context.t("因子源码无法通过检查"));
      state.inspection = value;
      state.parameterValues = defaults(value.params || []);
      status.textContent = context.t("源码有效，参数已解析");
    } catch (error) {
      state.inspection = null;
      status.textContent = error.message || context.t("因子源码无法通过检查");
    } finally {
      state.inspecting = false;
      redraw();
    }
  }

  function sourceControls(context, state, redraw, options = {}) {
    const root = document.createElement("section");
    root.className = "factor-editor-source-controls";
    const actions = document.createElement("div");
    actions.className = "detail-actions factor-editor-source-actions";
    const file = options.fileInput || filePicker(context, state, redraw);
    if (options.showUpload !== false) {
      const upload = context.button(context.t("上传因子家族源码"), () => file.click());
      upload.type = "button";
      actions.append(upload);
    }
    const validate = context.button(context.t("校验源码"), () => {
      void inspect(context, state, redraw, status);
    });
    validate.type = "button";
    actions.append(validate);
    const source = document.createElement("textarea");
    source.rows = 16;
    source.required = true;
    source.placeholder = context.t("填写继承 FactorFamily 的 Python 类源码");
    source.value = state.sourceCode;
    source.addEventListener("input", () => {
      state.sourceCode = source.value;
      state.inspection = null;
    });
    const status = document.createElement("small");
    status.className = "form-error factor-editor-source-status";
    if (state.inspection) {
      status.className = "factor-editor-source-status";
      status.textContent = context.t("源码已通过校验");
    }
    if (!options.fileInput) root.append(file);
    root.append(actions, field(context.t("Python 源码"), source), status);
    if (state.inspection) {
      root.append(window.FTFactorDetailShared.summary(context, {
        ...state.inspection,
        math_expr: state.inspection.math_expr || state.inspection.expression,
        description: state.inspection.description || state.inspection.desc,
      }));
    }
    return root;
  }

  function sourceMetadata(context, state) {
    const family = state.family || state.inspection || {};
    const loaded = state.loaded || {};
    const owner = loaded.factor_owner_ref || loaded.owner_ref
      || family.factor_owner_ref || family.owner_ref
      || family.owner_alias || "";
    const familyValue = loaded.factor_family_ref || loaded.family_ref
      || family.factor_family_ref || family.family_ref || familyAlias(family);
    const commit = loaded.factor_git_commit || loaded.git_commit
      || family.factor_git_commit || family.git_commit || "";
    if (!owner && !familyValue && !commit && !state.family && !state.inspection) {
      return null;
    }
    const root = document.createElement("section");
    root.className = "factor-editor-source-metadata";
    const version = commit
      ? `${context.t("历史源码版本")} · ${commit}`
      : context.t("当前因子家族最新源码");
    root.append(
      field(context.t("因子所有者"), readOnlyValue(owner || context.t("未设置"))),
      field(context.t("因子家族引用"), readOnlyValue(familyValue || context.t("未设置"))),
      field(context.t("源码版本"), readOnlyValue(version)),
    );
    return root;
  }

  function readOnlyValue(value) {
    const output = document.createElement("span");
    output.className = "factor-editor-readonly-value";
    output.textContent = value;
    return output;
  }

  function readInput(wrapper) {
    return wrapper.querySelector("input")?.value.trim() || "";
  }

  function normalizeSaved(value, state, context) {
    const saved = value || {};
    const family = state.family || state.inspection || {};
    const alias = saved.factor_alias || saved.name || saved.id
      || state.inspection?.factor_name || familyAlias(family);
    const params = saved.params || saved.factor_params || state.parameterValues || {};
    const owner = saved.factor_owner_ref || saved.owner_ref
      || saved.owner_username || context.session?.username || "";
    const familyAliasValue = saved.factor_family_alias || saved.family
      || familyAlias(family) || alias;
    const familyRefValue = saved.factor_family_ref || saved.family_ref
      || familyRef(family) || familyAliasValue;
    const commit = saved.factor_git_commit || saved.git_commit || "";
    return {
      ...saved,
      id: saved.id || alias,
      name: saved.name || alias,
      factor_ref: saved.factor_ref || saved.id || alias,
      factor_alias: alias,
      factor_owner_ref: owner,
      factor_family_ref: familyRefValue,
      factor_params: params,
      owner_ref: saved.owner_ref || owner,
      family_ref: saved.family_ref || familyRefValue,
      params,
      factor_family_alias: familyAliasValue,
      source_kind: saved.source_kind || "factor_library",
      can_edit: saved.can_edit ?? true,
      ...(commit ? {factor_git_commit: commit, git_commit: commit} : {}),
    };
  }

  async function saveLibraryFactor(context, state) {
    const alias = familyAlias(state.family);
    if (!alias) throw new Error(context.t("请先选择因子家族"));
    if (context.testObjectTemporary) {
      return {
        factor_family_alias: alias,
        factor_alias: alias,
        params: state.parameterValues || {},
        parameter_definitions: state.family?.params || [],
        source_kind: "factor_library",
        source_origin: "test_inline",
        temporary: true,
      };
    }
    const value = await context.api(
      `/custom-factors/api/factor-library-configs/${encodeURIComponent(alias)}`,
      {
        method: "PUT",
        body: JSON.stringify({params_list: [state.parameterValues || {}]}),
      },
    );
    return value.factors?.[0] || {
      factor_family_alias: alias,
      factor_alias: alias,
      params: state.parameterValues || {},
    };
  }

  async function saveSourceFactor(context, state, fields) {
    if (!state.inspection) {
      throw new Error(context.t("请先校验因子家族源码"));
    }
    const payload = {
      source_code: state.sourceCode,
      chinese_name: readInput(fields.chineseName),
      description: readInput(fields.description),
      category: readInput(fields.category) || "自编",
    };
    if (context.testObjectTemporary) {
      const alias = state.inspection?.factor_name || state.factorID
        || readInput(fields.name);
      return {
        ...payload,
        name: alias,
        factor_alias: alias,
        params: state.parameterValues || {},
        parameter_definitions: state.inspection?.params || [],
        source_kind: "transient",
        source_origin: "test_inline",
        transient_factor_id: alias,
        temporary: true,
      };
    }
    const endpoint = state.familyMode
      ? state.publicMode
        ? state.mode === "create"
          ? "/custom-factors/api/create-public"
          : `/custom-factors/api/update-public/${encodeURIComponent(state.factorID)}`
        : state.mode === "create"
          ? "/custom-factors/api/create"
          : `/custom-factors/api/update/${encodeURIComponent(state.factorID)}`
      : state.mode === "create"
        ? "/custom-factors/api/create"
        : `/custom-factors/api/update/${encodeURIComponent(state.factorID)}`;
    const value = await context.api(endpoint, {
      method: "POST", body: JSON.stringify(payload),
    });
    const saved = value.factor || value;
    const alias = saved.name || saved.id || state.factorID;
    if (!state.familyMode && Object.keys(state.parameterValues || {}).length) {
      await context.api(
        `/custom-factors/api/factor-library-configs/${encodeURIComponent(alias)}`,
        {
          method: "PUT",
          body: JSON.stringify({params_list: [state.parameterValues]}),
        },
      );
    }
    return saved;
  }

  async function render(context, data, targetRef, mode, options = {}) {
    if (!context.session) throw new Error(context.t("登录后才能编辑因子"));
    const familyMode = options.familyMode === true;
    const publicMode = options.publicMode === true;
    let factor = familyMode
      ? data.families.find(item => item.family_ref === targetRef
        || item.factor_family_alias === targetRef)
      : context.testObjectInitialValue || data.factors.find(item => item.factor_ref === targetRef
        || item.factor_alias === targetRef || item.id === targetRef);
    const factorID = familyMode
      ? familyAlias(factor) || targetRef
      : factor?.factor_alias || factor?.id || targetRef;
    if (mode === "edit" && !factorID) throw new Error(context.t("因子不存在"));
    let loaded = factor ? {...factor} : {};
    if (mode === "edit" && !context.testObjectTemporary) {
      const endpoint = familyMode && publicMode
        ? `/custom-factors/api/public-factor/${encodeURIComponent(factorID)}`
        : familyMode
          ? `/custom-factors/api/get/${encodeURIComponent(factorID)}`
            + `?owner_username=${encodeURIComponent(factor?.owner_username || context.session.username || "")}`
          : `/custom-factors/api/get/${encodeURIComponent(factorID)}`;
      const value = await context.api(
        endpoint,
      );
      loaded = {...loaded, ...(value.factor || {})};
    }
    const temporaryFamilyEdit = mode === "edit" && context.testObjectTemporary
      && loaded.source_kind !== "transient" && !loaded.source_code;
    const loadedFamily = temporaryFamilyEdit
      ? data.families.find(item => familyRef(item) === (
        loaded.factor_family_ref || loaded.family_ref
      ) || familyAlias(item) === (
        loaded.factor_family_alias || loaded.family_alias
      )) || null
      : null;
    const state = {
      mode, factorID, familyMode, publicMode,
      sourceMode: familyMode ? "source" : mode === "edit" && !temporaryFamilyEdit
        ? "source" : "family",
      family: loadedFamily,
      sourceCode: loaded.source_code || "",
      inspection: mode === "edit" && !temporaryFamilyEdit ? {
        params: Array.isArray(loaded.parameter_definitions)
          ? loaded.parameter_definitions : (Array.isArray(loaded.params) ? loaded.params : []),
        math_expr: loaded.math_expr || loaded.formula || "",
        description: loaded.description || loaded.chinese_name || "",
      } : null,
      parameterValues: Array.isArray(loaded.params)
        ? Object.fromEntries(loaded.params.map(parameter => [
          parameter.alias || parameter.name,
          parameter.value ?? parameter.default_value ?? "",
        ]))
        : {...(loaded.factor_params || loaded.params || {})},
      loaded,
    };
    const noun = familyMode ? context.t("因子家族") : context.t("因子");
    const titleText = mode === "create"
      ? context.t(`新增${familyMode ? "因子家族" : "因子"}`)
      : loaded.factor_alias || loaded.name || factorID;
    context.setHeading(titleText, noun + context.t("详情"));
    context.updateActiveTab?.({title: titleText});
    const form = document.createElement("form");
    form.className = "detail-stack factor-editor-form";
    const name = textField(context, familyMode ? "因子家族类名" : "因子类名", loaded.name || loaded.factor_alias || "", {
      readOnly: mode === "edit", required: true,
    });
    const chineseName = textField(context, "中文名称", loaded.chinese_name || "");
    const description = textField(context, "说明", loaded.description || "");
    const category = textField(context, "分类", loaded.category || "自编");
    const sourceMount = document.createElement("div");
    const parameterMount = document.createElement("div");
    const status = document.createElement("small");
    status.className = "form-error";
    const redraw = () => {
      sourceMount.replaceChildren();
      if (state.familyMode) {
        sourceMount.append(sourceControls(context, state, redraw, {
          fileInput: familyFileInput,
          showUpload: false,
        }));
      } else if (state.mode === "create") {
        sourceMount.append(sourceModePicker(context, state, redraw));
        if (state.sourceMode === "family") {
          sourceMount.append(familyPicker(context, data, state, redraw));
          if (state.family) {
            sourceMount.append(window.FTFactorDetailShared.summary(context, state.family));
          }
        } else {
          sourceMount.append(sourceControls(context, state, redraw));
        }
      } else {
        sourceMount.append(sourceControls(context, state, redraw));
      }
      const metadata = sourceMetadata(context, state);
      if (metadata) sourceMount.append(metadata);
      parameterMount.replaceChildren();
      const editor = parameterEditor(context, state);
      if (editor) {
        // parameterEditor owns the mutable values object; keep the same
        // object on state so edits made in the shared editor reach the save
        // request without inventing a second parameter form.
        state.parameterValues = editor.values;
        parameterMount.append(
          Object.assign(document.createElement("h3"), {textContent: context.t("参数")}),
          editor.root,
        );
      }
    };
    const familyFileInput = familyMode ? filePicker(context, state, redraw) : null;
    if (familyFileInput) {
      context.toolbar?.append(FTUI.iconButton(
        context,
        "paperclip",
        "上传因子家族源码",
        () => familyFileInput.click(),
        {className: "factor-editor-upload-action"},
      ));
    }
    const actions = document.createElement("div"); actions.className = "detail-actions";
    const cancel = context.button(context.t("取消"), () => {
      if (!FTTabReturn.returnToSource(context)) {
        context.closeTab?.(context.tabID); context.navigate("/factors");
      }
    });
    cancel.type = "button";
    const save = context.button(context.t("保存"), () => form.requestSubmit());
    save.type = "button"; save.className = "primary";
    actions.append(cancel, save);
    if (familyFileInput) form.append(familyFileInput);
    form.append(name, chineseName, description, category, sourceMount,
      parameterMount, status, actions);
    context.content.replaceChildren(form);
    redraw();
    form.addEventListener("submit", async event => {
      event.preventDefault(); save.disabled = true; status.textContent = "";
      try {
        const saved = state.sourceMode === "family"
          ? await saveLibraryFactor(context, state)
          : await saveSourceFactor(context, state, {
            name, chineseName, description, category,
          });
        const result = normalizeSaved(saved, state, context);
        if (context.testObjectTemporary && result.source_code && context.testState) {
          window.FTTestInputState?.putFactor?.(context.testState, {
            factor_id: result.factor_alias,
            path: `inline/${result.factor_alias}.py`,
            source_code: result.source_code,
            source_origin: "upload",
          }, {
            factor_name: result.factor_alias,
            params: state.inspection?.params || [],
            description: result.description || "",
            math_expr: state.inspection?.math_expr || "",
          });
        }
        if (context.onSaved) { context.onSaved(result); return; }
        const ref = state.familyMode
          ? result.family_ref || result.factor_family_ref || result.id
            || result.name || state.factorID
          : result.factor_ref || result.factor_alias || result.name;
        const kind = state.familyMode ? "family" : "factor";
        if (FTTabReturn.returnToSource(context, {kind, ref})) return;
        context.closeTab?.(context.tabID);
        const path = state.familyMode
          ? `/factors/family/${encodeURIComponent(ref)}?updated=${Date.now()}`
          : `/factors/factor/${encodeURIComponent(ref)}?updated=${Date.now()}`;
        context.navigate(path);
      } catch (error) {
        status.textContent = error.message || context.t("因子保存失败");
        save.disabled = false;
      }
    });
  }

  function textField(context, labelText, value, options = {}) {
    const input = document.createElement("input");
    input.value = value || "";
    input.readOnly = options.readOnly === true;
    input.required = options.required === true;
    return field(labelText, input);
  }

  function field(labelText, input) {
    if (window.FTTestFieldRow?.create) {
      return FTTestFieldRow.create(labelText, input);
    }
    const row = document.createElement("div");
    row.className = "test-setting-row test-field-row";
    const copy = document.createElement("span");
    const heading = document.createElement("span");
    heading.className = "test-field-row-heading";
    const title = document.createElement("b"); title.textContent = labelText;
    heading.append(title);
    copy.append(heading);
    const value = document.createElement("div");
    value.className = "test-field-row-control";
    value.append(input);
    row.append(copy, value);
    return row;
  }

  window.FTFactorEditor = Object.freeze({render});
})();
