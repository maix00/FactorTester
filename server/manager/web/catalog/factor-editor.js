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
    const factorRecord = Boolean(
      value?.factor_alias || value?.factor_ref || value?.factor_params,
    );
    if (factorRecord) {
      const storedFamilyName = String(
        value?.family_class_name || value?.factor_family_name
        || value?.factor_family_alias || value?.family_alias || value?.family || "",
      ).trim();
      if (storedFamilyName) return storedFamilyName;
      const factorAliasValue = String(value?.factor_alias || value?.alias || "").trim();
      if (factorAliasValue) return factorAliasValue.split("|", 1)[0];
    }
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
        view: window.FTFactorDetailShared?.familyRowView?.(item)
          || {kind: "factor_family", ref: value},
      }];
    });
  }

  function parameterDefinitions(value, options = {}) {
    const shared = window.FTFactorDetailShared?.parameterRows?.(value, options);
    if (Array.isArray(shared) && shared.length) return shared;
    const candidates = [
      value?.parameter_definitions,
      value?.params,
      value?.factor_params,
      value?.parameters,
    ].filter(candidate => Array.isArray(candidate) && candidate.length);
    return candidates.find(candidate => candidate.some(parameter => (
      parameter && typeof parameter === "object"
      && String(parameter.type || parameter.param_type || "").trim()
        && String(parameter.type || parameter.param_type || "").trim() !== "Parameter"
    ))) || candidates.find(candidate => candidate.some(parameter => (
      parameter && typeof parameter === "object"
      && parameter.default_value !== undefined
    ))) || candidates[0] || [];
  }

  function parameterRows(value, options = {}) {
    return parameterDefinitions(value, options);
  }

  function hasTypedParameters(value, options = {}) {
    return parameterRows(value, options).some(parameter => (
      parameter && parameter.type && parameter.type !== "Parameter"
    ));
  }

  async function resolveFactorForDisplay(context, data, factor, item = {}) {
    let family = item.family
      || window.FTFactorDisplayEnrichment.factorFamilyForFactor(data, factor);
    let merged = window.FTFactorDisplayEnrichment.enrichFactorWithFamily(
      factor, family,
    );
    const hasFormula = Boolean(window.FTFactorDetailShared?.expression?.(merged));
    if (family && (!hasTypedParameters(merged) || !hasFormula)
        && window.FTFactorDetailShared?.loadSourceVersion) {
      try {
        const loaded = await window.FTFactorDetailShared.loadSourceVersion(
          context, family, "current", {
            familyID: familyAlias(family),
            sourceKind: family.factor_kind === "public" || family.source === "public"
              ? "public" : "custom",
            ownerUsername: family.owner_username || context.session?.username || "",
          },
        );
        family = {...family, ...loaded};
        if (item.family) item.family = family;
        merged = window.FTFactorDisplayEnrichment.enrichFactorWithFamily(
          factor, family,
        );
      } catch (_) {
        // The compact factor remains selectable; its frozen identity is still
        // valid even when the optional family source cannot be loaded.
      }
    }
    return merged;
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

  // The picker's candidate source: library families plus this-session on-the-fly
  // families (which survive a redraw via state.onsiteFamilies). Used both for
  // the rendered items and for onChange lookups so a rebuild keeps 当场 + selection.
  function familyPickerItems(data, state) {
    const base = familyItems(data);
    const onsite = (state?.onsiteFamilies || []).map(f => ({
      value: familyRef(f),
      label: familyAlias(f) || familyRef(f),
      family: f,
      onsite: true,
      temporary: true,
    }));
    const seen = new Set(base.map(item => item.value));
    return base.concat(onsite.filter(item => !seen.has(item.value)));
  }

  function familyPicker(context, data, state, redraw) {
    const picker = sharedPicker(context, {
      compact: true,
      name: "factor-family-source",
      title: context.t("因子家族"),
      multi: false,
      items: familyPickerItems(data, state),
      selected: state.family ? [familyRef(state.family)] : [],
      onAddCandidate: async (_context, {add}) => {
        const editingTemporary = state.family?.temporary === true
          || state.family?.source_kind === "transient";
        const open = context.openObject || (childOptions => (
          FTObjectOverlay.open(context, childOptions)
        ));
        await open({
          kind: "factor_family", mode: editingTemporary ? "edit" : "create",
          ref: editingTemporary ? familyRef(state.family) || "temporary" : "new",
          initialValue: editingTemporary ? state.family : null,
          temporary: true,
          onSaved: family => {
            if (!family) return;
            // On-the-fly candidate only — never into the library family list,
            // so it does not linger in 候选 nor appear on later pages.
            add({
              value: familyRef(family),
              label: familyAlias(family) || familyRef(family),
              family,
              temporary: true,
            });
            // Keep the on-the-fly family for this session so a redraw rebuilds
            // the picker with it in 当场 + selected. Dedupe by ref.
            if (!state.onsiteFamilies.some(f => familyRef(f) === familyRef(family))) {
              state.onsiteFamilies.push(family);
            }
            state.family = family;
            state.latestFamily = family;
            state.sourceMode = "source";
            state.sourceCode = family.source_code || "";
            state.inspection = {
              ...family,
              params: parameterDefinitions(family),
            };
            state.parameterValues = defaults(state.inspection.params);
            state.sourceVersionFingerprint =
              family.family_formula_fingerprint || "";
            state.sourceVersions = null;
            state.sourceVersionLoadFailed = false;
            state.sourceVersionError = "";
            state.onFamilyChanged?.(family);
            redraw();
          },
        });
      },
      onTemporaryCandidateRemoved: item => {
        const removedRef = String(item?.value ?? item?.ref ?? "").trim();
        state.onsiteFamilies = (state.onsiteFamilies || []).filter(f => (
          familyRef(f) !== removedRef
        ));
        if (state.family && familyRef(state.family) === removedRef) {
          state.family = null;
          state.latestFamily = null;
        }
      },
      onChange: async values => {
        state.family = familyPickerItems(data, state)
          .find(item => item.value === values[0])?.family || null;
        state.sourceMode = "family";
        state.sourceVersionFingerprint = "";
        state.sourceVersions = null;
        state.sourceVersionLoadFailed = false;
        state.sourceVersionError = "";
        if (state.family && !parameterDefinitions(state.family).length) {
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
        state.parameterValues = defaults(parameterDefinitions(state.family));
        state.inspection = null;
        state.validationError = "";
        state.validationMessage = "";
        redraw();
      },
    });
    return field(context.t("因子家族"), picker.element);
  }

  function sourceVersionPicker(context, state, redraw) {
    if (!state.family
        || state.family.temporary === true
        || state.family.source_kind === "transient") return null;
    const options = window.FTFactorDetailShared.sourceOptions(state.family);
    const picker = window.FTFactorDetailShared.versionPicker(
      context, state.family, {
        ...options,
        payload: state.sourceVersions,
        selected: state.sourceVersionFingerprint || "__current__",
        onLoaded: payload => {
          state.sourceVersions = payload;
          state.sourceVersionLoadFailed = false;
          state.sourceVersionError = "";
          redraw();
        },
        onError: error => {
          state.sourceVersionLoadFailed = true;
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
    // Editing a frozen factor must echo its actual source version, not 未筛选:
    // eagerly load the version list so the frozen fingerprint matches a real
    // version item (onOpen above only lazily loads it on user interaction).
    if (!state.sourceVersions && !state.sourceVersionLoading
      && !state.sourceVersionLoadFailed
      && state.sourceVersionFingerprint) {
      state.sourceVersionLoading = true;
      void window.FTFactorDetailShared.loadSourceVersions(
        context, state.family, options,
      ).then(payload => {
        state.sourceVersions = payload;
        state.sourceVersionLoading = false;
        redraw();
      }).catch(() => {
        state.sourceVersionLoading = false;
        state.sourceVersionLoadFailed = true;
        state.sourceVersionError = window.FTFactorDetailShared.sourceUnavailableText(
          context,
        );
        redraw();
      });
    }
    return field(context.t("源码版本"), picker.element);
  }

  async function selectSourceVersion(context, state, selected, redraw) {
    const fingerprint = selected === "__current__" ? "" : String(selected || "");
    state.sourceVersionFingerprint = fingerprint;
    state.sourceVersionLoadFailed = false;
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
      const nextParameters = parameterDefinitions(payload).length
        ? parameterDefinitions(payload) : parameterDefinitions(state.family);
      const previous = state.parameterValues || {};
      state.parameterValues = Object.fromEntries(nextParameters.map(parameter => {
        const alias = parameter.alias || parameter.name;
        return [alias, previous[alias] ?? parameter.value ?? parameter.default_value ?? ""];
      }).filter(([alias]) => alias));
    } catch (_) {
      state.sourceVersionLoadFailed = true;
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
      parameter.default_value ?? parameter.value ?? "",
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

  // Editing an already-saved factor object echoes the object's parameter
  // rows, where a FactorParam value is stored as its opaque ``factor:v2``
  // ref.  The row's frozen factor_dependencies carry the full record
  // (identity + owner) for that ref — hydrate it so the parameter editor
  // opens the frozen factor (pickable / tree) instead of a bare ref in a
  // manual input.
  function hydrateFactorParamValues(parameters, dependencies = []) {
    const byRef = new Map();
    for (const dependency of dependencies || []) {
      const ref = String(dependency?.ref || dependency?.factor_ref || "").trim();
      if (ref) byRef.set(ref, dependency);
    }
    return Object.fromEntries((parameters || []).map(parameter => {
      const alias = parameter.alias || parameter.name;
      if (!alias) return [];
      const value = parameter.value ?? parameter.default_value ?? "";
      const resolved = typeof value === "string" && value.startsWith("factor:v2:")
        && byRef.has(value)
        ? byRef.get(value) : value;
      return [alias, resolved];
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

  async function materializeFamilyDrafts(context, values = {}, sourceVersions = new Map()) {
    const restoreDependency = async value => {
      if (!value || typeof value !== "object") return value;
      if (Array.isArray(value)) return Promise.all(value.map(restoreDependency));
      let restored = {...value};
      if (value.factor_dependencies?.length) {
        restored.factor_dependencies = await Promise.all(
          value.factor_dependencies.map(restoreDependency),
        );
      }
      if (value.identity?.params) {
        restored.identity = {...value.identity, params: Object.fromEntries(
          await Promise.all(Object.entries(value.identity.params).map(
            async ([key, child]) => [key, await restoreDependency(child)],
          )),
        )};
      }
      if (value.source_kind !== "transient" || value.source_code
          || Number(value.schema_version) !== 2) return restored;
      // Catalog metadata deliberately excludes source bytes. A legacy inline
      // marker may survive registration, but can only be retired after the
      // authorized catalog proves the exact immutable family version exists.
      const identity = value.identity || {};
      const owner = String(value.owner_ref || "").replace(/^principal:/, "");
      const fingerprint = identity.family_formula_fingerprint;
      const key = JSON.stringify([owner, identity.family_alias, fingerprint]);
      if (!sourceVersions.has(key)) {
        sourceVersions.set(key, window.FTFactorDetailShared.loadSourceVersion(
          context, {...value, factor_family_alias: identity.family_alias,
            factor_kind: ["public", "__public_jobs__"].includes(owner) ? "public" : "custom"},
          fingerprint,
        ));
      }
      const source = await sourceVersions.get(key);
      if (!fingerprint || !source.source_code
          || source.family_formula_fingerprint !== fingerprint) {
        throw new Error(context.t("嵌套因子源码版本不匹配"));
      }
      restored = {...restored, source_kind: "factor_library",
        source_origin: "factor_library", temporary: false};
      delete restored.source_code;
      delete restored.transient_factor_id;
      return restored;
    };
    const result = {...values};
    for (const [alias, raw] of Object.entries(result)) {
      if (!raw || raw.__factor_family_draft !== true || !raw.__factor_family) {
        result[alias] = await restoreDependency(raw);
        continue;
      }
      const family = raw.__factor_family;
      const params = await materializeFamilyDrafts(
        context, raw.parameter_values || {}, sourceVersions,
      );
      const transient = family.source_kind === "transient"
        || family.temporary === true;
      const body = transient ? {
        source_code: family.source_code || "",
        params,
      } : {
        resolve_factor: true,
        factor_family_alias: familyAlias(family),
        owner_username: family.owner_username || family.owner_ref
          || context.session?.username || "",
        is_public: family.factor_kind === "public" || family.source === "public",
        params,
      };
      const resolved = await context.api("/api/factor-library/families/validate", {
        method: "POST", body: JSON.stringify(body),
      });
      if (!resolved.valid || !resolved.factor) {
        throw new Error(resolved.error || context.t(`参数 ${alias} 的内嵌因子无法解析`));
      }
      result[alias] = {
        ...resolved.factor,
        factor_alias: resolved.factor.alias,
        factor_family_alias: resolved.factor_family_alias
          || familyAlias(family),
        params,
        parameter_definitions: resolved.params
          || family.params || family.parameter_definitions || [],
        source_kind: transient ? "transient" : "factor_library",
        source_origin: transient ? "test_inline" : "factor_library",
        source_code: transient ? family.source_code || "" : undefined,
        factor_dependencies: parameterDependencies(params),
        temporary: transient,
      };
    }
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
    if (state.sourceMode === "source") return parameterDefinitions(state.inspection);
    return parameterDefinitions(state.family);
  }

  function factorParameterItems(data) {
    const seen = new Set();
    return (data?.factors || []).flatMap(factor => {
      const alias = String(factor?.factor_alias || factor?.alias || "").trim();
      const value = String(factor?.factor_ref || factor?.ref || "").trim();
      if (!alias || !value || seen.has(value)) return [];
      seen.add(value);
      const family = window.FTFactorDisplayEnrichment.factorFamilyForFactor(
        data, factor,
      );
      const enriched = window.FTFactorDisplayEnrichment.enrichFactorWithFamily(
        factor, family,
      );
      return [{
        value, label: alias, factor: enriched, family,
        description: [enriched.owner_alias || enriched.owner_username,
          enriched.factor_family_alias].filter(Boolean).join(" · "),
        view: window.FTFactorDetailShared?.factorRowView?.(enriched)
          || {kind: "factor", ref: value},
      }];
    });
  }

  function parameterEditor(context, data, state, redraw, hooks = {}) {
    const list = parameters(state);
    if (!list.length) return null;
    return window.FTFactorParameterEditor.create(
      context, list, state.parameterValues, {
        factorItems: factorParameterItems(data),
        familyItems: familyItems(data),
        maxFamilyDepth: context.testObjectOverlay === true ? 1 : 12,
        onNestedFamilyTemplate: hooks.onNestedFamilyTemplate,
        onSelectFactor: (factor, item) => resolveFactorForDisplay(
          context, data, factor, item,
        ),
        onValidateFactorAlias: async alias => {
          const normalizedAlias = String(alias || "").trim();
          const registered = (data?.factors || []).find(item => (
            String(item?.factor_alias || item?.alias || "").trim()
              === normalizedAlias
          ));
          if (registered) {
            const family = window.FTFactorDisplayEnrichment.factorFamilyForFactor(
              data, registered,
            );
            const enriched = await resolveFactorForDisplay(
              context, data, registered, {family},
            );
            return {
              valid: true,
              factor_alias: String(
                registered.factor_alias || registered.alias || normalizedAlias,
              ),
              factor: enriched,
              family,
            };
          }
          const familyAliasValue = normalizedAlias.split("|", 1)[0];
          const family = (data?.families || []).find(item => (
            familyAlias(item) === familyAliasValue
          ));
          if (!family) {
            return {valid: false, error: context.t("找不到该 alias 对应的可见因子家族")};
          }
          return context.api("/api/factor-library/families/validate", {
            method: "POST",
            body: JSON.stringify({
              resolve_factor_alias: true,
              factor_alias: normalizedAlias,
              factor_family_alias: familyAliasValue,
              owner_username: family.owner_username || family.workspace_username || "",
              is_public: family.factor_kind === "public" || family.source === "public",
            }),
          });
        },
        onSelectFamily: async family => {
          if (parameterDefinitions(family).length) {
            return family;
          }
          try {
            const loaded = await window.FTFactorDetailShared.loadSourceVersion(
              context, family, "current", {
                familyID: familyAlias(family),
                sourceKind: family.factor_kind === "public" ? "public" : undefined,
                ownerUsername: family.owner_username || context.session?.username || "",
              },
            );
            return {...family, ...loaded};
          } catch (_) {
            return family;
          }
        },
        onCreateFamily: (onSaved, currentFamily) => (
          context.openObject || (childOptions => (
            FTObjectOverlay.open(context, childOptions)
          ))
        )({
          kind: "factor_family", mode: currentFamily ? "edit" : "create",
          ref: currentFamily ? familyRef(currentFamily) || "temporary" : "new",
          initialValue: currentFamily || null, onSaved,
          // A nested family is configuration-local until the owning factor is
          // explicitly submitted. Never publish it as a library family here.
          temporary: true,
        }),
        onChange: nextValues => {
          // FTFactorParameterEditor owns a copy of the values object. Keep
          // the page draft in sync before rendering the outer expression;
          // otherwise the picker visibly changes while the formula keeps the
          // previous FactorParam value.
          if (nextValues && typeof nextValues === "object") {
            state.parameterValues = {...nextValues};
          }
          // parameterEditor is a top-level helper: its render-scope callbacks
          // (markDirty, formula refresh) are injected through hooks instead of
          // relying on ambient variables that do not exist in this scope.
          hooks.markDirty?.("parameters");
          context.pageState?.capture?.();
          hooks.refreshComposition?.(state.parameterValues);
          hooks.refreshFormula?.();
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
    actions.className = "source-panel-actions";
    const file = options.fileInput || filePicker(
      context, state, redraw, options.onChanged,
    );
    if (options.showUpload !== false) {
      const upload = FTUI.iconButton(
        context, "arrow.up.circle", "上传因子源码", () => file.click(),
      );
      actions.append(upload);
    }
    const validate = FTUI.iconButton(context, "checkmark.circle", "校验源码", async () => {
      validate.disabled = true;
      await inspect(context, state, redraw);
      validate.disabled = false;
    });
    validate.disabled = state.inspecting === true;
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
    root.append(FTUI.sourcePanel(context, editor.element, {
      actions: Array.from(actions.children),
    }), status);
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
          mode: state.mode,
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
        factor_dependencies: parameterDependencies(state.parameterValues),
        temporary: true,
      };
    }
    const value = await context.api(
      `/api/factor-library/configurations/${encodeURIComponent(alias)}/factors`,
      {
        method: "POST",
        body: JSON.stringify({
          params: state.parameterValues || {},
          scope_key: state.loaded?.scope_key || state.loaded?.product_group,
          replace_factor_ref: state.mode === "edit"
            ? state.loaded?.factor_ref || state.loaded?.ref : undefined,
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
      if (state.familyMode) {
        return {
          ...payload,
          family_ref: `temporary-family:${crypto.randomUUID()}`,
          factor_family_alias: alias,
          family_class_name: alias,
          name: alias,
          params: state.inspection?.params || [],
          parameter_definitions: state.inspection?.params || [],
          math_expr: state.inspection?.math_expr || "",
          family_formula_fingerprint:
            state.inspection?.family_formula_fingerprint || "",
          source_kind: "transient",
          source_origin: "test_inline",
          temporary: true,
        };
      }
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
        factor_dependencies: parameterDependencies(state.parameterValues),
        temporary: true,
      };
    }
    const sourceFamilyID = state.familyMode
      ? state.factorID
      : state.loaded?.factor_family_alias
        || state.loaded?.family_alias
        || state.inspection?.factor_name
        || state.factorID;
    const endpoint = state.familyMode
      ? state.publicMode
        ? state.mode === "create"
          ? "/api/factor-library/families/public"
          : `/api/factor-library/families/public/${encodeURIComponent(sourceFamilyID)}`
        : state.mode === "create"
          ? "/api/factor-library/families/custom"
          : `/api/factor-library/families/custom/${encodeURIComponent(sourceFamilyID)}`
      : state.mode === "create"
        ? "/api/factor-library/families/custom"
        : `/api/factor-library/families/custom/${encodeURIComponent(sourceFamilyID)}`;
    const value = await context.api(endpoint, {
      method: state.mode === "create" ? "POST" : "PUT",
      body: JSON.stringify(payload),
    });
    const saved = value.factor || value;
    const alias = saved.name || saved.id || state.factorID;
    let registered = null;
    if (!state.familyMode) {
      const libraryValue = await context.api(
        `/api/factor-library/configurations/${encodeURIComponent(alias)}/factors`,
        {
          method: "POST",
          body: JSON.stringify({
            params: state.parameterValues,
            mode: state.mode,
            scope_key: state.loaded?.scope_key || state.loaded?.product_group,
            replace_factor_ref: state.mode === "edit"
              ? state.loaded?.factor_ref || state.loaded?.ref : undefined,
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

  async function refreshPersistedObject(context, state, result) {
    if (context.testObjectTemporary) return result;
    // The write has committed. Read its local registration without waiting
    // for unrelated account-domain conflicts to clear. Catalog GETs already
    // schedule asynchronous sync; explicit header refresh keeps its barrier.
    const data = await window.FTFactorCatalog.load(context, {
      refresh: true, library: true, sync: false,
    });
    if (state.familyMode) return result;
    const targetRef = String(result?.factor_ref || result?.ref || "").trim();
    const targetAlias = String(result?.factor_alias || result?.alias || "").trim();
    const persisted = (data.factors || []).find(item => (
      targetRef && String(item?.factor_ref || item?.ref || "") === targetRef
      || targetAlias && String(item?.factor_alias || item?.alias || "") === targetAlias
    ));
    if (!persisted) {
      throw new Error(context.t("因子保存后未在因子库中登记"));
    }
    return {...result, ...persisted};
  }

  function replacePersistedObjectTab(context, state, result) {
    // Same-tab authoring: the editor lives in the object's own tab and the
    // tab survives the save.  A factor edit can mint a NEW alias and ref, so
    // the destination view URL differs from the editing URL — navigateInPlace
    // lets the current tab adopt the resulting object's canonical view (no
    // second tab, no stale placeholder).
    const ref = state.familyMode
      ? result.family_ref || result.id || result.name || state.factorID
      : result.factor_alias || result.factor_ref || result.name;
    const owner = !state.familyMode
      ? String(result.owner_username || state.loaded?.owner_username || "").trim()
      : "";
    const query = new URLSearchParams();
    if (owner) query.set("owner_username", owner);
    const suffix = query.toString();
    const path = state.familyMode
      ? `/factors/family/${encodeURIComponent(ref)}`
      : `/factors/factor/${encodeURIComponent(ref)}${suffix ? `?${suffix}` : ""}`;
    if (typeof context.navigateInPlace === "function") {
      context.navigateInPlace(path);
    } else {
      context.navigate(path);
    }
  }

  async function render(context, data, targetRef, mode, options = {}) {
    if (!context.session) throw new Error(context.t("登录后才能编辑因子"));
    const familyMode = options.familyMode === true;
    const publicMode = options.publicMode === true;
    let factor = familyMode
      ? data.families.find(item => item.family_ref === targetRef
        || item.factor_family_alias === targetRef)
      : context.testObjectInitialValue || data.factors.find(item => item.factor_ref === targetRef
        || item.ref === targetRef || item.alias === targetRef
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
        context, loaded, familyMode ? "current"
          : loaded.family_formula_fingerprint
            || loaded.identity?.family_formula_fingerprint || "current", {
          familyID,
          sourceKind: publicMode ? "public" : undefined,
          ownerUsername: loaded.owner_username || loaded.factor_owner_ref
            || loaded.owner_ref || context.session.username || "",
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
    if (selectedFamily && !parameterDefinitions(selectedFamily).length) {
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
    const loadedParameters = parameterDefinitions(loaded, {family: loaded});
    const state = {
      mode, factorID, familyMode, publicMode,
      sourceMode: familyMode ? "source" : mode === "edit" && !temporaryFamilyEdit
        ? "source" : "family",
      family: familyMode && mode === "edit"
        ? loaded
        : selectedFamily || loadedFamily || (loaded && (
            loaded.factor_family_alias || loaded.identity?.family_alias
          ) ? {
            factor_family_alias: loaded.factor_family_alias
              || loaded.identity?.family_alias,
            factor_family_name: loaded.factor_family_alias
              || loaded.identity?.family_alias,
            family_ref: loaded.family_ref || loaded.identity?.family_ref || "",
            parameter_definitions: loaded.parameter_definitions
              || loaded.family_parameter_definitions || [],
            math_expr: loaded.math_expr || loaded.formula || "",
            owner_username: loaded.owner_username
              || loaded.owner_ref || loaded.factor_owner_ref || "",
            factor_owner_ref: loaded.factor_owner_ref
              || loaded.owner_ref || loaded.owner_username || "",
            factor_kind: loaded.factor_kind || (loaded.source || ""),
          } : null),
      latestFamily: familyMode && mode === "edit"
        ? loaded : selectedFamily || loadedFamily,
      sourceCode: loaded.source_code || "",
      inspection: mode === "edit" && !temporaryFamilyEdit ? {
        params: loadedParameters,
        math_expr: loaded.math_expr || loaded.formula || "",
        description: loaded.description || loaded.chinese_name || "",
      } : null,
      parameterValues: hydrateFactorParamValues(
        loadedParameters, loaded.factor_dependencies,
      ),
      loaded,
      validationError: "",
      validationMessage: "",
      sourceVersionFingerprint: loaded.family_formula_fingerprint
        || loaded.identity?.family_formula_fingerprint || "",
      sourceVersions: null,
      sourceVersionError: "",
      sourceVersionLoading: false,
      sourceVersionLoadFailed: false,
      // On-the-fly factor families created through the picker "+" this session.
      // They are NOT pushed into data.families (never persist), but must survive
      // a redraw so the 当场 section + selection survive a picker rebuild.
      onsiteFamilies: [],
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
    // Opening the editor first resolves every nested factor (recursively —
    // including factors nested inside factors) to its family template, so
    // the top formula preview can render each nested definition line.
    const nestedTemplates = new Map();
    const nestedTemplateKey = record => JSON.stringify([
      record.owner_ref || record.factor_owner_ref || "",
      record.identity?.family_ref || record.family_ref || "",
      record.identity?.family_alias || record.factor_family_alias || "",
      record.identity?.family_formula_fingerprint || record.family_formula_fingerprint || "",
    ]);
    const resolveNestedTemplates = async values => {
      const records = [];
      const seen = new Set();
      const visit = value => {
        if (!value || typeof value !== "object") return;
        if (Number(value.schema_version) === 2 && (value.ref || value.factor_ref)) {
          const ref = String(value.ref || value.factor_ref);
          if (seen.has(ref)) return;
          seen.add(ref);
          records.push(value);
          for (const dep of value.factor_dependencies || []) visit(dep);
          for (const child of Object.values(value.identity?.params || {})) visit(child);
          return;
        }
        if (value.__factor_family_draft) visit(value.__factor_family);
        for (const dep of value.factor_dependencies || []) visit(dep);
      };
      for (const value of Object.values(values || {})) visit(value);
      const loads = [];
      for (const record of records) {
        const alias = String(
          record.identity?.family_alias || record.factor_family_alias || "",
        ).trim();
        const key = nestedTemplateKey(record);
        if (!alias || nestedTemplates.has(key)
          || loads.some(item => item.key === key)) continue;
        // Catalog summaries can predate the renderer and are not a source
        // template for a frozen version. Load the selected dependency only.
        loads.push({alias, record, key});
      }
      await Promise.all(loads.map(async ({alias, record, key}) => {
        try {
          const ownerRef = String(record.owner_ref || "").trim().replace(/^principal:/, "");
          const isPublic = ["public", "__public_jobs__"].includes(ownerRef);
          const loaded = await window.FTFactorDetailShared.loadSourceVersion(
            context, {
              factor_family_alias: alias,
              factor_family_name: alias,
              family_ref: record.identity?.family_ref || record.family_ref || "",
            }, record.identity?.family_formula_fingerprint
              || record.family_formula_fingerprint || "current", {
              familyID: alias,
              sourceKind: isPublic ? "public" : undefined,
              ownerUsername: isPublic ? "" : ownerRef,
            },
          );
          if (loaded) nestedTemplates.set(key, {...loaded, factor_family_alias: alias});
        } catch (_) {
          // Nested template unavailable: the preview just omits that line.
        }
      }));
    };
    // Attach each frozen record's family template formula so renderPreviewNode
    // can emit the nested definition lines; deeper records (nested inside
    // identity.params / factor_dependencies) are augmented recursively.
    const attachNestedTemplates = values => {
      const out = {...(values || {})};
      const attach = value => {
        if (!value || typeof value !== "object") return value;
        if (value.__factor_family_draft === true && value.__factor_family) {
          return value;
        }
        if (Number(value.schema_version) === 2 && (value.ref || value.factor_ref)) {
          const alias = String(
            value.identity?.family_alias || value.factor_family_alias || "",
          ).trim();
          const family = nestedTemplates.get(nestedTemplateKey(value));
          const params = value.identity?.params || {};
          let paramsChanged = false;
          const nextParams = {};
          for (const [key, child] of Object.entries(params)) {
            const attached = attach(child);
            nextParams[key] = attached;
            paramsChanged = paramsChanged || attached !== child;
          }
          let next = value;
          if (paramsChanged) {
            next = {...next, identity: {...next.identity, params: nextParams}};
          }
          if (family) {
            next = {
              ...next,
              math_expr: family.math_expr || family.formula || family.latex || "",
              factor_family_alias: alias,
              factor_family_name: alias,
              family,
            };
          }
          return next;
        }
        return value;
      };
      for (const [key, value] of Object.entries(out)) out[key] = attach(value);
      return out;
    };
    let previewFrame = 0;
    let refreshParameterComposition = () => {};
    const refreshFormulaPreview = () => {
      if (previewFrame) return;
      const schedule = window.requestAnimationFrame || (callback => setTimeout(callback, 0));
      previewFrame = schedule(() => {
        previewFrame = 0;
        const target = topMount.querySelector?.(".factor-family-formula");
        if (!target) return;
        const formula = window.FTFactorDetailShared.previewExpression(
          state.family || state.inspection || state.loaded,
          attachNestedTemplates(state.parameterValues),
        );
        // 编辑/新建模式：用「因子家族 math_expr(LATEX模板) + 参数列表」在现场（浏览器）做
        // 参数替换 + 嵌套因子叠加，得到预览公式。这与查看模式（渲染后端 resolved_math_expr）
        // 是两条路径：编辑可改嵌套因子，故须前端即时重算。math_expr=模板输入、resolved=输出。
        if (!formula) return;
        if (window.katex) window.FTUI?.renderMath?.(target, formula, {display: true});
        else target.textContent = formula;
      });
    };
    const redraw = () => {
      refreshParameterComposition = () => {};
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
      const liveExpression = !state.familyMode
        ? window.FTFactorDetailShared.previewExpression(
          formulaSource, attachNestedTemplates(state.parameterValues),
        ) : "";
      topMount.append(window.FTFactorDetailShared.summary(context, {
        ...(formulaSource || {}),
        math_expr: liveExpression || formulaSource?.math_expr
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
        sourceMount.append(familyPicker(context, data, state, redraw));
        const version = sourceVersionPicker(context, state, redraw);
        if (version) sourceMount.append(version);
      } else {
        // Edit mode shows the same family picker (+ 当场新建) and the family
        // source-version picker as create mode, then the source editor.
        sourceMount.append(familyPicker(context, data, state, redraw));
        const version = sourceVersionPicker(context, state, redraw);
        if (version) sourceMount.append(version);
        // A factor instance's source code comes from its family template; the
        // parameter tab shows only the family/source-version rows — no Python
        // source editor (that belongs to a family page).
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
      if (!state.familyMode) {
        // Factor instances do not own a source tab. Their family selection
        // (or family creation) + source version is part of the parameter
        // composition flow.  Both create and edit render the same family /
        // source-version rows on the parameter tab (edit included), so
        // changing the family/version means starting a fresh factor.
        parameterMount.append(sourceMount);
      }
      const editor = parameterEditor(context, data, state, redraw, {
        markDirty: name => markDirty(name),
        refreshComposition: values => refreshParameterComposition(values),
        refreshFormula: () => refreshFormulaPreview(),
        onNestedFamilyTemplate: (alias, family, record) => {
          if (!alias || !family) return;
          if (record) nestedTemplates.set(nestedTemplateKey(record), family);
          refreshFormulaPreview();
        },
      });
      if (editor) {
        // parameterEditor owns the mutable values object; keep the same
        // object on state so edits made in the shared editor reach the save
        // request without inventing a second parameter form.
        state.parameterValues = editor.values;
        // Edit/create render the same shared parameter section component as
        // view mode: collapsible header with the family template formula and
        // the 参数/值 toggles (parameterSection helper + localFormula),
        // wrapping the shared editable parameter list.
        const familySource = {
          ...(state.family || state.inspection || state.loaded || {}),
          source_code: state.sourceCode || state.family?.source_code || "",
        };
        const section = window.FTFactorDetailShared.parameterSection(
          context, familySource, [], 0, {content: editor.root},
        );
        refreshParameterComposition = values => section.update(
          values || state.parameterValues || {},
        );
        parameterMount.append(section.root);
      } else parameterMount.append(emptyState(context, state.familyMode
        ? "参数定义将在源码校验后生成" : "当前因子没有参数"));
    };
    const familyFileInput = familyMode ? filePicker(
      context, state, redraw, () => tabs?.setDirty("source", true),
    ) : null;
    // Mode actions come from the shared component: edit → 取消(回同 tab 查看)
    // + 保存; create → 取消 + 提交; overlay save label stays 保存.  The
    // component owns ordering, the same-tab navigation and the route-session
    // guard; the last returned action is the save button so the submit
    // handler can disable it while the request is in flight.
    const editingInline = mode === "edit" && context.testObjectTemporary;
    const viewHref = mode === "edit" && !editingInline
      ? (state.familyMode
        ? `/factors/family/${encodeURIComponent(targetRef)}`
        : `/factors/factor/${encodeURIComponent(targetRef)}${state.loaded?.owner_username
          ? `?${new URLSearchParams({owner_username: state.loaded.owner_username})}` : ""}`)
      : "";
    const actions = window.FTObjectModeActions?.mount?.(context, {
      mode,
      viewHref,
      cancel: mode === "edit" ? !editingInline : undefined,
      onCancel: (mode === "create" || editingInline) ? (() => {
        if (!FTTabReturn.returnToSource(context)) {
          context.closeTab?.(context.tabID);
          if (!context.testObjectOverlay) context.navigate("/factors");
        }
      }) : undefined,
      onSave: () => form.requestSubmit(),
      overlaySaveLabel: "保存",
    }) || [];
    const submit = actions[actions.length - 1];
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
      // A factor is defined by its frozen family formula and parameter
      // values; family descriptive metadata belongs to the family pages and
      // the read-only detail view.  Edit mode must present the same tab
      // form as create mode (parameters and related tabs only) — no extra
      // read-only 详情 tab.
      overview: {hidden: true},
      source: {hidden: true},
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
    if (mode === "create" || mode === "edit") {
      const stateKey = mode === "create"
        ? `factor-create:${state.familyMode ? "family" : "factor"}`
        : `factor-edit:${state.familyMode ? "family" : "factor"}:${targetRef}`;
      context.pageState?.register?.(stateKey, {
        capture: () => ({
          active_tab: tabs.current(),
          name: name.value,
          chinese_name: chineseName.value,
          description: description.value,
          category: category.value,
          source_mode: state.sourceMode,
          family: state.family,
          latest_family: state.latestFamily,
          inspection: state.inspection,
          source_code: state.sourceCode,
          parameter_values: state.parameterValues,
          onsite_families: state.onsiteFamilies,
        }),
        restore: value => {
          name.value = value?.name || "";
          chineseName.value = value?.chinese_name || "";
          description.value = value?.description || "";
          category.value = value?.category || "";
          state.sourceMode = value?.source_mode || state.sourceMode;
          state.family = value?.family || state.family;
          state.latestFamily = value?.latest_family || state.latestFamily;
          state.inspection = value?.inspection || state.inspection;
          state.sourceCode = value?.source_code || "";
          state.parameterValues = value?.parameter_values || state.parameterValues;
          state.onsiteFamilies = Array.isArray(value?.onsite_families)
            ? value.onsite_families : [];
          tabs.select(value?.active_tab || tabs.current(), false);
        },
      });
    }
    form.append(topMount, tabs.root, status);
    context.content.replaceChildren(form);
    if (!state.familyMode) {
      // Resolve nested factor family templates before the first render so
      // the top formula preview carries every nested definition line.
      await resolveNestedTemplates(state.parameterValues);
    }
    redraw();
    FTFactorAssistance.register(context, {
      state, name, chineseName, description, category, tabs, redraw, markDirty,
      parameterDefinitions: () => parameters(state),
    });
    form.addEventListener("input", markDirty);
    form.addEventListener("change", markDirty);
    form.addEventListener("submit", async event => {
      event.preventDefault(); submit.disabled = true; status.textContent = "";
      try {
        state.parameterValues = await materializeFamilyDrafts(
          context, state.parameterValues,
        );
        if (!await validateSourceDraft()) {
          tabs.select(state.familyMode ? "source" : "parameters", true);
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
        let result = normalizeSaved(saved, state, context);
        result = await refreshPersistedObject(context, state, result);
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
        replacePersistedObjectTab(context, state, result);
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
      context.pageState?.capture?.();
      context.checkpointTabSession?.();
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
    familyClassNameMatches, refreshPersistedObject, replacePersistedObjectTab,
    saveSourceFactor, materializeFamilyDrafts,
  });
})();
