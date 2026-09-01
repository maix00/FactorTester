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
      value?.family_ref || familyAlias(value),
    ).trim();
  }

  function persistedFamilyClassName(value) {
    return String(
      value?.name || value?.factor_family_name || value?.family_class_name
      || value?.factor_family_alias || value?.family_alias || value?.family || "",
    ).trim();
  }

  function familyClassNameMatches(expected, inspection) {
    const stored = String(expected || "").trim();
    const declared = String(inspection?.factor_name || "").trim();
    return Boolean(stored && declared && stored === declared);
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
        state.validationError = "";
        state.validationMessage = "";
        state.onFamilyChanged?.(state.family);
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
      onChange: async values => {
        state.family = familyItems(data).find(item => item.value === values[0])?.family || null;
        if (state.family && !(state.family.params || []).length) {
          try {
            const loaded = await window.FTFactorDetailShared.loadSourceVersion(
              context, state.family, "current", {
                familyID: familyAlias(state.family),
                sourceKind: state.family.factor_kind === "public" ? "public" : undefined,
                ownerUsername: state.family.owner_username
                  || context.session?.username || "",
              },
            );
            state.family = {...state.family, ...loaded};
          } catch (error) {
            state.sourceVersionError = error?.message
              || context.t("因子家族参数读取失败");
          }
        }
        state.latestFamily = state.family;
        state.parameterValues = defaults(state.family?.params || []);
        state.sourceVersionFingerprint = "";
        state.sourceVersions = null;
        state.sourceVersionError = "";
        state.inspection = null;
        state.validationError = "";
        state.validationMessage = "";
        redraw();
      },
    });
    return field(context.t("因子家族"), picker.element);
  }

  function sourceVersionPicker(context, state, redraw) {
    if (!state.family) return null;
    const options = window.FTFactorDetailShared.sourceOptions(state.family);
    const picker = window.FTFactorDetailShared.versionPicker(
      context, state.family, {
        ...options,
        payload: state.sourceVersions,
        selected: state.sourceVersionFingerprint || "__current__",
        onLoaded: payload => {
          state.sourceVersions = payload;
          redraw();
        },
        onError: () => {
          state.sourceVersionError = window.FTFactorDetailShared.sourceUnavailableText(
            context,
          );
          redraw();
        },
        onChange: selected => { void selectSourceVersion(
          context, state, selected, redraw,
        ); },
      },
    );
    return field(context.t("源码版本"), picker.element);
  }

  async function selectSourceVersion(context, state, selected, redraw) {
    const fingerprint = selected === "__current__" ? "" : String(selected || "");
    state.sourceVersionFingerprint = fingerprint;
    state.sourceVersionError = "";
    state.sourceVersionLoading = Boolean(fingerprint);
    redraw();
    if (!fingerprint) {
      state.family = state.latestFamily || state.family;
      state.sourceCode = state.family?.source_code || state.sourceCode;
      state.sourceVersionLoading = false;
      redraw();
      return;
    }
    try {
      const payload = await window.FTFactorDetailShared.loadSourceVersion(
        context, state.latestFamily || state.family, fingerprint,
      );
      state.family = {
        ...(state.latestFamily || state.family || {}),
        ...payload,
        family_formula_fingerprint:
          payload.family_formula_fingerprint || fingerprint,
      };
      state.sourceCode = payload.source_code || "";
      state.onFamilyChanged?.(state.family);
      const nextParameters = payload.params || state.family.params || [];
      const previous = state.parameterValues || {};
      state.parameterValues = Object.fromEntries(nextParameters.map(parameter => {
        const alias = parameter.alias || parameter.name;
        return [alias, previous[alias] ?? parameter.value ?? parameter.default_value ?? ""];
      }).filter(([alias]) => alias));
    } catch (_) {
      state.sourceVersionError = window.FTFactorDetailShared.sourceUnavailableText(
        context,
      );
    } finally {
      state.sourceVersionLoading = false;
      redraw();
    }
  }

  function defaults(parameters) {
    return Object.fromEntries((parameters || []).map(parameter => [
      parameter.alias || parameter.name,
      parameter.value ?? parameter.default_value ?? "",
    ]).filter(([alias]) => alias));
  }

  function reconcileParameterValues(parameters, previous = {}) {
    return Object.fromEntries((parameters || []).map(parameter => {
      const alias = parameter.alias || parameter.name;
      const fallback = parameter.value ?? parameter.default_value ?? "";
      return [
        alias,
        Object.prototype.hasOwnProperty.call(previous || {}, alias)
          ? previous[alias] : fallback,
      ];
    }).filter(([alias]) => alias));
  }

  function parameterDependencies(values = {}) {
    const result = [];
    const seen = new Set();
    const visit = value => {
      if (!value || typeof value !== "object") return;
      for (const dependency of value.factor_dependencies || []) visit(dependency);
      const ref = String(value.ref || "").trim();
      if (Number(value.schema_version) !== 2 || !ref || seen.has(ref)) return;
      seen.add(ref);
      result.push(value);
    };
    for (const value of Object.values(values || {})) visit(value);
    return result;
  }

  function normalizedInspection(value) {
    const item = value || {};
    const factor = item.factor || item.frozen_factor || {};
    return {
      ...item,
      math_expr: item.math_expr || item.resolved_math_expr
        || factor.math_expr || factor.formula || factor.latex || "",
      description: item.description || item.desc
        || factor.description || factor.desc || "",
    };
  }

  function parameters(state) {
    if (state.familyMode) return [];
    if (state.sourceMode === "source") return state.inspection?.params || [];
    return state.family?.params || [];
  }

  function factorParameterItems(data) {
    const seen = new Set();
    return (data?.factors || []).flatMap(factor => {
      const value = String(factor?.factor_alias || factor?.alias || "").trim();
      if (!value || seen.has(value)) return [];
      seen.add(value);
      return [{
        value, label: value,
        description: [factor.owner_alias || factor.owner_username,
          factor.factor_family_alias].filter(Boolean).join(" · "),
      }];
    });
  }

  function parameterEditor(context, data, state, redraw) {
    const list = parameters(state);
    if (!list.length) return null;
    return window.FTFactorParameterEditor.create(
      context, list, state.parameterValues, {
        factorItems: factorParameterItems(data),
        onValidateFactorAlias: async alias => {
          const familyAliasValue = String(alias || "").split("|", 1)[0];
          const family = (data?.families || []).find(item => (
            familyAlias(item) === familyAliasValue
          ));
          if (!family) {
            return {valid: false, error: context.t("找不到该 alias 对应的可见因子家族")};
          }
          return context.api("/api/factor-library/families/validate", {
            resolve_factor_alias: true,
            factor_alias: alias,
            factor_family_alias: familyAliasValue,
            owner_username: family.owner_username || family.workspace_username || "",
            is_public: family.factor_kind === "public" || family.source === "public",
          });
        },
        onCreateFactor: onSaved => (
          context.openTestObject || (childOptions => (
            FTTestObjectEditorOverlay.open(context, childOptions)
          ))
        )({
          kind: "factor", mode: "create", ref: "new", onSaved,
          temporary: context.testObjectTemporary === true,
        }),
        onFactorCreated: (factor, alias) => {
          const value = String(factor?.factor_alias || factor?.alias || "").trim();
          if (value) {
            state.parameterValues[alias] = value;
            data.factors ||= [];
            if (!data.factors.some(item => (
              item.factor_alias || item.alias
            ) === value)) data.factors.push(factor);
          }
          redraw();
        },
      },
    );
  }

  function filePicker(context, state, redraw, onChanged) {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".py,text/x-python";
    input.hidden = true;
    input.addEventListener("change", async () => {
      const file = input.files?.[0];
      input.value = "";
      if (!file) return;
      state.sourceCode = await file.text();
      state.onSourceChanged?.(state.sourceCode);
      state.inspection = null;
      state.validationError = "";
      state.validationMessage = "";
      onChanged?.();
      redraw();
    });
    return input;
  }

  async function inspect(context, state, redraw) {
    if (!state.sourceCode.trim()) {
      state.validationError = context.t("源码不能为空");
      state.validationMessage = state.validationError;
      redraw();
      return;
    }
    state.inspecting = true;
    state.validationError = "";
    state.validationMessage = context.t("正在校验源码并解析参数…");
    redraw();
    try {
      const parsed = await context.api("/api/factor-library/families/validate", {
        method: "POST",
        body: JSON.stringify({source_code: state.sourceCode, params: {}}),
      });
      if (!parsed.valid) {
        throw new Error(parsed.error || context.t("因子源码无法通过检查"));
      }
      const parameterValues = reconcileParameterValues(
        parsed.params || [], state.parameterValues,
      );
      const value = !state.familyMode && Object.keys(parameterValues).length
        ? await context.api("/api/factor-library/families/validate", {
          method: "POST",
          body: JSON.stringify({
            source_code: state.sourceCode,
            params: parameterValues,
          }),
        }) : parsed;
      if (!value.valid) throw new Error(value.error || context.t("因子源码无法通过检查"));
      state.inspection = normalizedInspection(value);
      state.onInspected?.(state.inspection);
      state.validationError = "";
      state.validationMessage = context.t("源码有效，参数已解析");
      state.parameterValues = parameterValues;
    } catch (error) {
      state.inspection = null;
      state.validationError = error.message || context.t("因子源码无法通过检查");
      state.validationMessage = state.validationError;
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
    const file = options.fileInput || filePicker(
      context, state, redraw, options.onChanged,
    );
    if (options.showUpload !== false) {
      const upload = FTUI.actionButton(
        context.t("上传因子源码"), () => file.click(), {variant: "secondary"},
      );
      actions.append(upload);
    }
    const validate = FTUI.actionButton(context.t("校验源码"), async () => {
      validate.disabled = true;
      await inspect(context, state, redraw);
      validate.disabled = false;
    }, {variant: "secondary"});
    actions.append(validate);
    const editor = FTUI.codeEditor(state.sourceCode, {
      language: "python",
      required: true,
      placeholder: context.t("填写继承 FactorFamily 的 Python 类源码"),
      ariaLabel: context.t("Python 源码"),
    });
    editor.textarea.addEventListener("input", () => {
      state.sourceCode = editor.value();
      state.onSourceChanged?.(state.sourceCode);
      state.inspection = null;
      state.validationError = "";
      state.validationMessage = "";
      options.onChanged?.();
    });
    const status = document.createElement("small");
    status.className = state.validationError
      ? "form-error factor-editor-source-status"
      : "factor-editor-source-status";
    status.textContent = state.validationMessage || (state.inspection
      ? context.t("源码已通过校验") : "");
    if (state.inspecting) {
      status.textContent = context.t("正在校验源码并解析参数…");
    }
    if (!options.fileInput) root.append(file);
    const sourceRow = field(context.t("Python 源码"), editor.element);
    sourceRow.classList.add("factor-editor-source-code-row");
    root.append(actions, sourceRow, status);
    return root;
  }

  function sourceMetadata(context, state) {
    const family = state.family || state.inspection || {};
    const loaded = state.loaded || {};
    const identity = window.FTFactorDetailShared.familyIdentity(loaded, family);
    const owner = loaded.factor_owner_ref
      || family.factor_owner_ref
      || family.owner_alias || "";
    const familyValue = identity.alias;
    const fingerprint = state.sourceVersionFingerprint || identity.fingerprint;
    const familyLabel = fingerprint
      ? context.t("冻结因子家族") : context.t("选定因子家族");
    if (!owner && !familyValue && !fingerprint && !state.family && !state.inspection) {
      return null;
    }
    const root = document.createElement("section");
    root.className = "factor-editor-source-metadata";
    const version = fingerprint
      ? `${context.t("公式版本")} · ${fingerprint.slice(0, 12)}`
      : context.t("尚未校验公式版本");
    root.append(
      field(
        familyLabel,
        readOnlyValue(identity.alias || context.t("未选择")),
      ),
      field(context.t("因子所有者"), readOnlyValue(owner || context.t("未设置"))),
      field(
        context.t("家族公式指纹"),
        readOnlyValue(fingerprint || context.t("尚未校验")),
      ),
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
    const frozen = saved.factor || saved.frozen_factor || {};
    const family = state.family || state.inspection || {};
    const alias = saved.factor_alias || saved.alias || frozen.alias
      || saved.name || saved.id
      || state.inspection?.factor_name || familyAlias(family);
    const params = saved.params || saved.factor_params
      || frozen.identity?.params || state.parameterValues || {};
    const owner = saved.factor_owner_ref || saved.owner_ref || frozen.owner_ref
      || saved.owner_username || context.session?.username || "";
    const familyAliasValue = saved.factor_family_alias || saved.family
      || frozen.identity?.family_alias || familyAlias(family) || alias;
    const ref = saved.ref || frozen.ref || saved.factor_ref || saved.id || alias;
    return {
      ...saved,
      ...frozen,
      id: saved.id || alias,
      name: saved.name || alias,
      ref,
      factor_ref: saved.factor_ref || frozen.ref || ref,
      factor_alias: alias,
      factor_owner_ref: owner,
      factor_params: params,
      params,
      factor_family_alias: familyAliasValue,
      source_kind: saved.source_kind || "factor_library",
      can_edit: saved.can_edit ?? true,
      family_formula_fingerprint:
        saved.family_formula_fingerprint || family?.family_formula_fingerprint || "",
      self_formula_fingerprint: saved.self_formula_fingerprint || "",
    };
  }

  async function saveLibraryFactor(context, state) {
    const alias = familyAlias(state.family);
    if (!alias) throw new Error(context.t("请先选择因子家族"));
    if (state.sourceVersionError) throw new Error(state.sourceVersionError);
    if (context.testObjectTemporary) {
      const owner = String(
        state.family?.owner_username || state.family?.owner_ref
        || context.session?.username || "",
      ).trim();
      const isPublic = state.family?.factor_kind === "public"
        || state.family?.source === "public"
        || owner === "public" || owner === "__public_jobs__";
      const value = await context.api("/api/factor-library/families/validate", {
        method: "POST",
        body: JSON.stringify({
          resolve_factor: true,
          factor_family_alias: alias,
          owner_username: owner,
          is_public: isPublic,
          params: state.parameterValues || {},
        }),
      });
      if (!value.valid || !value.factor) {
        throw new Error(value.error || context.t("因子解析失败"));
      }
      return {
        ...value.factor,
        factor_family_alias: alias,
        factor_alias: value.factor.alias,
        params: state.parameterValues || {},
        parameter_definitions: state.family?.params || [],
        source_kind: "factor_library",
        source_origin: "test_inline",
        temporary: true,
      };
    }
    const value = await context.api(
      `/api/factor-library/configurations/${encodeURIComponent(alias)}`,
      {
        method: "PUT",
        body: JSON.stringify({
          params_list: [state.parameterValues || {}],
          metadata: {
            family_formula_fingerprint:
              state.inspection?.family_formula_fingerprint
              || state.family?.family_formula_fingerprint || null,
            self_formula_fingerprint:
              state.inspection?.self_formula_fingerprint || null,
            factor_dependencies: parameterDependencies(state.parameterValues),
          },
        }),
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
      const value = await context.api("/api/factor-library/families/validate", {
        method: "POST",
        body: JSON.stringify({
          source_code: state.sourceCode,
          params: state.parameterValues || {},
        }),
      });
      if (!value.valid || !value.factor) {
        throw new Error(value.error || context.t("因子解析失败"));
      }
      return {
        ...payload,
        ...value.factor,
        name: alias,
        factor_alias: value.factor.alias || alias,
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
          ? "/api/factor-library/families/public"
          : `/api/factor-library/families/public/${encodeURIComponent(state.factorID)}`
        : state.mode === "create"
          ? "/api/factor-library/families/custom"
          : `/api/factor-library/families/custom/${encodeURIComponent(state.factorID)}`
      : state.mode === "create"
        ? "/api/factor-library/families/custom"
        : `/api/factor-library/families/custom/${encodeURIComponent(state.factorID)}`;
    const value = await context.api(endpoint, {
      method: state.mode === "create" ? "POST" : "PUT",
      body: JSON.stringify(payload),
    });
    const saved = value.factor || value;
    const alias = saved.name || saved.id || state.factorID;
    let registered = null;
    if (!state.familyMode && Object.keys(state.parameterValues || {}).length) {
      const libraryValue = await context.api(
        `/api/factor-library/configurations/${encodeURIComponent(alias)}`,
        {
          method: "PUT",
          body: JSON.stringify({
            params_list: [state.parameterValues],
            metadata: {
              factor_dependencies: parameterDependencies(state.parameterValues),
            },
          }),
        },
      );
      registered = libraryValue.factors?.[0] || null;
    }
    // Creating source-backed factors has two server-side steps: register the
    // family source, then register the selected parameter row.  The second
    // response is the only one that contains the frozen Factor v2 identity
    // required by candidate pickers and detail routes.  Return that complete
    // row so the caller never tries to resolve the family class name as a
    // factor reference.
    return registered
      ? {...saved, ...registered, source_code: saved.source_code || payload.source_code}
      : saved;
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
      const familyID = familyMode
        ? factorID
        : loaded.factor_family_alias || loaded.family_alias || factorID;
      const value = await window.FTFactorDetailShared.loadSourceVersion(
        context, loaded, "current", {
          familyID,
          sourceKind: publicMode ? "public" : undefined,
          ownerUsername: loaded.owner_username || context.session.username || "",
        },
      );
      loaded = {...loaded, ...value};
    }
    const temporaryFamilyEdit = mode === "edit" && context.testObjectTemporary
      && loaded.source_kind !== "transient" && !loaded.source_code;
    let selectedFamily = !familyMode && mode === "create" && options.familyRef
      ? data.families.find(item => familyRef(item) === options.familyRef
        || item.factor_family_alias === options.familyRef
        || item.factor_family_name === options.familyRef) || null
      : null;
    if (selectedFamily && !(selectedFamily.params || []).length) {
      try {
        const familySource = await window.FTFactorDetailShared.loadSourceVersion(
          context, selectedFamily, "current", {
            familyID: familyAlias(selectedFamily),
            sourceKind: selectedFamily.factor_kind === "public" ? "public" : undefined,
            ownerUsername: selectedFamily.owner_username || context.session.username || "",
          },
        );
        selectedFamily = {...selectedFamily, ...familySource};
      } catch (_) {
        // The source panel will surface an availability error. Keep the
        // catalog row selectable instead of making the whole editor fail.
      }
    }
    const loadedFamily = temporaryFamilyEdit
      ? data.families.find(item => familyRef(item) === (
        loaded.family_ref
      ) || familyAlias(item) === (
        loaded.factor_family_alias || loaded.family_alias
      )) || null
      : null;
    const state = {
      mode, factorID, familyMode, publicMode,
      sourceMode: familyMode ? "source" : mode === "edit" && !temporaryFamilyEdit
        ? "source" : "family",
      family: familyMode && mode === "edit"
        ? loaded : selectedFamily || loadedFamily,
      latestFamily: familyMode && mode === "edit"
        ? loaded : selectedFamily || loadedFamily,
      sourceCode: loaded.source_code || "",
      inspection: mode === "edit" && !temporaryFamilyEdit ? {
        params: Array.isArray(loaded.parameter_definitions)
          ? loaded.parameter_definitions
          : window.FTFactorDetailShared.parameterRows(loaded),
        math_expr: loaded.math_expr || loaded.formula || "",
        description: loaded.description || loaded.chinese_name || "",
      } : null,
      parameterValues: Object.fromEntries(
        window.FTFactorDetailShared.parameterRows(loaded).map(parameter => [
          parameter.alias,
          parameter.value ?? parameter.default_value ?? "",
        ]),
      ),
      loaded,
      validationError: "",
      validationMessage: "",
      sourceVersionFingerprint: loaded.family_formula_fingerprint || "",
      sourceVersions: null,
      sourceVersionError: "",
      sourceVersionLoading: false,
    };
    const noun = familyMode ? context.t("因子家族") : context.t("因子");
    const titleText = mode === "create"
      ? context.t(`新增${familyMode ? "因子家族" : "因子"}`)
      : loaded.factor_alias || loaded.name || factorID;
    context.setHeading(titleText, noun + context.t("详情"));
    context.updateActiveTab?.({title: titleText});
    const form = document.createElement("form");
    form.className = window.FTFactorDetailShared.pageClass(
      mode, `factor-editor-form ${familyMode ? "factor-family-page" : "factor-page"}`,
    );
    const name = textField(
      context, "因子家族类名",
      persistedFamilyClassName(familyMode ? loaded : state.family || loaded), {
      readOnly: mode === "edit", required: true,
      },
    );
    const chineseName = textField(context, "中文名称", loaded.chinese_name || "");
    const description = textField(context, "说明", loaded.description || "");
    const category = textField(context, "分类", loaded.category || "自编");
    state.onFamilyChanged = family => {
      if (mode === "create" && !familyMode) {
        name.value = persistedFamilyClassName(family);
      }
    };
    const topMount = document.createElement("div");
    topMount.className = "factor-detail-top";
    const overviewMount = document.createElement("div");
    overviewMount.className = "factor-editor-overview";
    overviewMount.append(name, chineseName, description, category);
    const sourceMount = document.createElement("div");
    const parameterMount = document.createElement("div");
    const identityMount = document.createElement("div");
    const jobObjectKind = familyMode ? "family" : "factor";
    const jobObjectRef = familyMode
      ? loaded.family_ref || targetRef : loaded.factor_ref || targetRef;
    const jobs = window.FTFactorObjectJobs.create(context, {
      objectKind: jobObjectKind,
      objectRef: jobObjectRef,
      familyFormulaFingerprint: loaded.family_formula_fingerprint || "",
      selfFormulaFingerprint: loaded.self_formula_fingerprint || "",
      ownerRef: loaded.factor_owner_ref || loaded.owner_ref || "",
      alias: familyMode ? familyAlias(loaded) : "",
    });
    let tabs;
    const status = document.createElement("small");
    status.className = "form-error";
    const redraw = () => {
      topMount.replaceChildren();
      if (state.familyMode && state.mode === "edit") {
        const version = sourceVersionPicker(context, state, redraw);
        if (version) topMount.append(version);
      }
      // The validated formula is part of the editor header, above the detail
      // tabs.  Keep this mount separate from the source panel so validation
      // does not move the formula into the source tab or make it disappear
      // when the tab content is rebuilt.
      const formulaSource = state.inspection || state.family || state.loaded;
      topMount.append(window.FTFactorDetailShared.summary(context, {
        ...(formulaSource || {}),
        math_expr: formulaSource?.math_expr
          || formulaSource?.expression
          || formulaSource?.resolved_math_expr || "",
        description: formulaSource?.description || formulaSource?.desc || "",
      }));
      sourceMount.replaceChildren();
      if (state.familyMode) {
        sourceMount.append(sourceControls(context, state, redraw, {
          fileInput: familyFileInput,
          onChanged: () => tabs?.setDirty("source", true),
        }));
      } else if (state.mode === "create") {
        sourceMount.append(sourceModePicker(context, state, redraw));
        if (state.sourceMode === "family") {
          sourceMount.append(familyPicker(context, data, state, redraw));
          const version = sourceVersionPicker(context, state, redraw);
          if (version) sourceMount.append(version);
        } else {
          sourceMount.append(sourceControls(context, state, redraw, {
            onChanged: () => tabs?.setDirty("source", true),
          }));
        }
      } else {
        sourceMount.append(sourceControls(context, state, redraw, {
          onChanged: () => tabs?.setDirty("source", true),
        }));
      }
      const metadata = sourceMetadata(context, state);
      identityMount.replaceChildren();
      if (metadata) identityMount.append(metadata);
      else identityMount.append(emptyState(context, "暂无身份与来源信息"));
      if (state.sourceVersionLoading) {
        const loading = document.createElement("small");
        loading.className = "factor-editor-source-status";
        loading.textContent = context.t("正在读取源码版本…");
        sourceMount.append(loading);
      }
      if (state.sourceVersionError) {
        const error = document.createElement("small");
        error.className = "form-error factor-editor-source-status";
        error.textContent = state.sourceVersionError;
        sourceMount.append(error);
      }
      parameterMount.replaceChildren();
      const editor = parameterEditor(context, data, state, redraw);
      if (editor) {
        // parameterEditor owns the mutable values object; keep the same
        // object on state so edits made in the shared editor reach the save
        // request without inventing a second parameter form.
        state.parameterValues = editor.values;
        parameterMount.append(editor.root);
      } else parameterMount.append(emptyState(context, state.familyMode
        ? "参数定义将在源码校验后生成" : "当前因子没有参数"));
    };
    const familyFileInput = familyMode ? filePicker(
      context, state, redraw, () => tabs?.setDirty("source", true),
    ) : null;
    const cancelEdit = FTUI.actionButton(context.t("取消编辑"), () => {
      if (!FTTabReturn.returnToSource(context)) {
        context.closeTab?.(context.tabID); context.navigate("/factors");
      }
    }, {variant: "secondary"});
    const submit = FTUI.actionButton(
      context.t(mode === "create" ? "提交" : "保存"),
      () => form.requestSubmit(), {variant: "primary"},
    );
    if (mode === "edit") context.toolbar.append(cancelEdit);
    context.toolbar.append(submit);
    if (familyFileInput) form.append(familyFileInput);
    const overrides = state.familyMode ? {
      overview: {save_mode: "auto"},
      source: {save_mode: "auto"},
      members: {hidden: true},
      parameters: {editable: false},
      jobs: {
        hidden: mode === "create" || context.testObjectTemporary === true,
        onActivate: jobs.load,
      },
    } : {
      // A factor is defined by its frozen family formula and parameter values.
      // Family descriptive metadata belongs to family creation, not factor
      // creation; keep the shared detail surface for factor view/edit only.
      overview: {hidden: mode === "create", save_mode: "auto"},
      source: {save_mode: "auto"},
      parameters: {save_mode: "auto"},
      jobs: {
        hidden: mode === "create" || context.testObjectTemporary === true,
        onActivate: jobs.load,
      },
    };
    tabs = window.FTObjectDetailTabs.create(context, {
      objectKind: state.familyMode ? "family" : "factor",
      mode,
      overrides,
      panels: {
        overview: overviewMount,
        source: sourceMount,
        parameters: parameterMount,
        identity: identityMount,
        jobs: jobs.mount,
      },
    });
    let selectedTab = tabs.current();
    tabs.root.addEventListener("object-detail-tab-change", event => {
      const nextTab = event.detail?.key || tabs.current();
      const previousTab = selectedTab;
      selectedTab = nextTab;
      if (previousTab === "source" && nextTab !== "source") {
        void validateSourceDraft();
      }
    });
    if (mode === "create") {
      const stateKey = `factor-create:${state.familyMode ? "family" : "factor"}`;
      context.pageState?.register?.(stateKey, {
        capture: () => ({
          active_tab: tabs.current(),
          name: name.value,
          chinese_name: chineseName.value,
          description: description.value,
          category: category.value,
          source_mode: state.sourceMode,
          source_code: state.sourceCode,
          parameter_values: state.parameterValues,
        }),
        restore: value => {
          name.value = value?.name || "";
          chineseName.value = value?.chinese_name || "";
          description.value = value?.description || "";
          category.value = value?.category || "";
          state.sourceMode = value?.source_mode || state.sourceMode;
          state.sourceCode = value?.source_code || "";
          state.parameterValues = value?.parameter_values || state.parameterValues;
          tabs.select(value?.active_tab || tabs.current(), false);
        },
      });
    }
    form.append(topMount, tabs.root, status);
    context.content.replaceChildren(form);
    redraw();
    FTFactorAssistance.register(context, {
      state, name, chineseName, description, category, tabs, redraw, markDirty,
    });
    form.addEventListener("input", markDirty);
    form.addEventListener("change", markDirty);
    form.addEventListener("submit", async event => {
      event.preventDefault(); submit.disabled = true; status.textContent = "";
      try {
        if (!await validateSourceDraft()) {
          tabs.select("source", true);
          throw new Error(state.validationError || context.t("因子源码无法通过检查"));
        }
        if ((state.familyMode || state.sourceMode !== "family")
            && !familyClassNameMatches(name.value, state.inspection)) {
          throw new Error(context.t(
            "详情中的因子家族类名必须与源码声明的类名一致",
          ));
        }
        const saved = state.sourceMode === "family"
          ? await saveLibraryFactor(context, state)
          : await saveSourceFactor(context, state, {
            name, chineseName, description, category,
          });
        const result = normalizeSaved(saved, state, context);
        window.FTFactorCatalog?.upsertFactor?.(result);
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
          ? result.family_ref || result.id
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
        submit.disabled = false;
      }
    });

    async function validateSourceDraft() {
      const usesEditableSource = state.familyMode || state.sourceMode !== "family";
      if (!usesEditableSource) {
        tabs.setDirty("source", false);
        return true;
      }
      await inspect(context, state, redraw);
      const valid = Boolean(state.inspection && !state.validationError);
      tabs.setDirty("source", !valid);
      return valid;
    }

    function markDirty(eventOrKey) {
      const panel = typeof eventOrKey === "string" ? null
        : eventOrKey?.target?.closest?.(".object-detail-tab-panel");
      const key = typeof eventOrKey === "string"
        ? eventOrKey : panel?.dataset?.tabKey;
      if (key) tabs.setDirty(key, key === "source");
    }
  }

  function emptyState(context, text) {
    const value = document.createElement("p");
    value.className = "catalog-source-note";
    value.textContent = context.t(text);
    return value;
  }

  function textField(context, labelText, value, options = {}) {
    const input = document.createElement("input");
    input.value = value || "";
    input.readOnly = options.readOnly === true;
    input.required = options.required === true;
    return bindFieldValue(field(labelText, input), input);
  }

  function bindFieldValue(row, input) {
    Object.defineProperty(row, "value", {
      configurable: true,
      get: () => input.value,
      set: value => { input.value = value ?? ""; },
    });
    return row;
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

  window.FTFactorEditor = Object.freeze({
    render, reconcileParameterValues, bindFieldValue, persistedFamilyClassName,
    familyClassNameMatches,
  });
})();
