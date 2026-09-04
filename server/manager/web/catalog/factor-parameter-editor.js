(() => {
  "use strict";

  function create(context, parameters = [], initial = {}, options = {}) {
    const shared = window.FTFactorDetailShared?.createParameterList;
    if (shared) {
      return shared(context, parameters, initial, {
        ...options,
        renderValue: (value, parameter, initialValue, values, row) => {
          const alias = String(parameter?.alias || parameter?.name || "").trim();
          if (parameter.type === "FactorParam") {
            row.classList?.add?.("factor-detail-parameter-row-factor");
            const nested = renderReference(context, value, parameter, initialValue, values, options);
            return {control: true, nested};
          }
          const input = document.createElement("input");
          input.type = "text";
          input.readOnly = Boolean(options.readOnly);
          input.value = initialValue;
          input.addEventListener("input", () => {
            values[alias] = input.value;
            options.onChange?.(values, alias);
          });
          value.append(input);
          return {control: true};
        },
      });
    }
    throw new Error("FTFactorDetailShared.createParameterList is required");
  }

  function renderReference(context, row, parameter, initialValue, values, options) {
    const alias = String(parameter.alias || parameter.name).trim();
    const columns = [...(parameter.options || [])];
    const factors = [...(options.factorItems || [])];
    const families = [...(options.familyItems || [])];
    const control = document.createElement("div");
    control.className = "factor-param-reference-control";
    const sourceControl = document.createElement("div");
    sourceControl.className = "factor-param-active-source";
    const input = document.createElement("input");
    const display = value => {
      if (value && typeof value === "object") {
        return String(value.alias ?? value.factor_alias ?? value.value ?? "").trim();
      }
      return String(value ?? "").trim();
    };
    const reference = value => {
      if (value && typeof value === "object") {
        return String(value.ref ?? value.factor_ref ?? value.value ?? "").trim();
      }
      return String(value ?? "").trim();
    };
    const selectionValue = value => {
      if (value && typeof value === "object") {
        return String(value.value ?? value.ref ?? value.family_ref
          ?? value.factor_ref ?? value.id ?? "").trim();
      }
      return String(value ?? "").trim();
    };
    const allowFamilyComposition = Number(options.depth || 0)
      < Number(options.maxFamilyDepth ?? 12);
    const sourceTypes = [
      {
        value: "manual", label: context.t("填写"),
        description: context.t("手动填写 ColumnRef、因子 alias 或常量"),
      },
      {
        value: "column", label: context.t("Column"),
        description: context.t("从 DataColumn 候选中选择"),
      },
      {
        value: "factor", label: context.t("因子库"),
        description: context.t("从当前可见因子中选择"),
      },
    ];
    if (allowFamilyComposition) {
      sourceTypes.push({
        value: "family", label: context.t("因子家族"),
        description: context.t("选择因子家族并填写其嵌套参数"),
      });
    }
    let columnPicker;
    let factorPicker;
    let familyPicker;
    let sourcePicker;
    const initialFactor = factors.find(candidate => {
      const candidateValue = selectionValue(candidate.value ?? candidate.ref);
      const candidateFactor = candidate.factor || candidate;
      const candidateAlias = display(candidateFactor);
      return candidateValue && (
        candidateValue === reference(initialValue)
        || candidateAlias === display(initialValue)
      );
    });
    const initialFactorValue = initialFactor?.factor || initialFactor;
    if (isFrozenFactor(initialFactorValue) && (
      !isFrozenFactor(initialValue)
      || initialFactorValue !== initialValue
      || (Array.isArray(initialFactorValue.parameter_definitions)
        && !Array.isArray(initialValue?.parameter_definitions))
    )) {
      initialValue = initialFactorValue;
      values[alias] = initialValue;
    }
    // When the current frozen reference is not among the visible library
    // rows (different product-group scope, freshly saved combination, …),
    // carry it as its own choice so the 因子库 source stays selectable and
    // the value never falls back into a hand-typed box.
    const factorChoices = [...factors];
    if (isFrozenFactorValue(initialValue) && !factorChoices.some(item => (
      selectionValue(item.value ?? item.ref) === reference(initialValue)
    ))) {
      const frozenRef = reference(initialValue) || display(initialValue) || alias;
      factorChoices.push({
        value: frozenRef,
        label: display(initialValue) || alias,
        factor: initialValue && typeof initialValue === "object"
          ? initialValue
          : {ref: frozenRef, alias: display(initialValue) || alias},
        family: null,
      });
    }
    let activeSource = "";
    // Preserve the value's origin: a factor-library reference (opaque
    // ``factor:v2`` ref or a frozen v2 record) reopens on the 因子库 source;
    // hand-typed aliases/columns stay manual/column; on-the-fly family
    // compositions stay family.  Never degrade any of them into the others.
    const frozenInitial = isFrozenFactorValue(initialValue);
    if (familyDraft(initialValue)) {
      activeSource = "family";
    } else if (frozenInitial) {
      activeSource = "factor";
    } else if (factorChoices.some(item => selectionValue(item.value ?? item.ref)
      === reference(initialValue))) {
      activeSource = "factor";
    } else if (columns.some(item => selectionValue(item.value) === selectionValue(initialValue))) {
      activeSource = "column";
    } else if (display(initialValue)) {
      activeSource = "manual";
    }
    let renderSourceControl = () => {};
    const setValue = (value, source, {retainSource = false} = {}) => {
      const empty = value === undefined || value === null || value === "";
      values[alias] = empty ? "" : value;
      activeSource = empty ? (retainSource ? source : "") : source;
      input.value = ["column", "manual"].includes(source) ? display(values[alias]) : "";
      input.setCustomValidity("");
      const shown = display(values[alias]);
      columnPicker?.setValues?.(source === "column" && shown ? [shown] : []);
      const selectedRef = reference(values[alias]);
      factorPicker?.setValues?.(source === "factor" && selectedRef ? [selectedRef] : []);
      familyPicker?.setValues?.(source === "family" && familyDraft(value)
        ? [familyRef(value.__factor_family)] : []);
      sourcePicker?.setValues?.(activeSource ? [activeSource] : []);
      renderSourceControl();
      renderNested();
      options.onChange?.(values, alias);
    };
    const sourceValue = source => {
      if (activeSource !== source) return "";
      if (source === "column" && !columns.some(item => (
        selectionValue(item.value) === selectionValue(values[alias])
      ))) return "";
      if (source === "factor" && !factorChoices.some(item => (
        selectionValue(item.value ?? item.ref) === reference(values[alias])
      ))) return "";
      if (source === "family" && !familyDraft(values[alias])) return "";
      return values[alias];
    };
    sourcePicker = picker(
      context, `factor-param-source-${alias}`, context.t("填写类型"),
      sourceTypes, activeSource ? [activeSource] : [], selected => {
        const source = selectionValue(selected?.[0]);
        if (!sourceTypes.some(item => item.value === source)) {
          setValue("", "");
          return;
        }
        setValue(sourceValue(source), source, {retainSource: true});
      },
      {disabled: options.readOnly === true},
    );
    columnPicker = picker(context, `factor-param-column-${alias}`, context.t("DataColumn"),
      columns, activeSource === "column" ? [initialValue] : [],
      selected => setValue(selected?.[0] || "", "column"),
      {disabled: options.readOnly === true});
    const selectFactor = selected => {
      const selectedRef = selectionValue(selected?.[0]);
      const item = factorChoices.find(candidate => (
        selectionValue(candidate.value ?? candidate.ref) === selectedRef
      ));
        if (!item) {
          setValue("", "factor");
          return;
        }
        const factor = item.factor || item;
        const resolved = options.onSelectFactor?.(factor, item);
        if (resolved && typeof resolved.then === "function") {
          return resolved.then(value => {
            const next = value || factor;
            if (item.factor) item.factor = next;
            setValue(next, "factor");
          });
        }
        const next = resolved || factor;
        if (item.factor) item.factor = next;
        setValue(next, "factor");
        return undefined;
      };
    factorPicker = picker(context, `factor-param-factor-${alias}`, context.t("因子库"),
      factorChoices, activeSource === "factor" ? [reference(initialValue)] : [], selectFactor,
      {disabled: options.readOnly === true});
    if (allowFamilyComposition) {
      familyPicker = picker(
        context, `factor-param-family-${alias}`, context.t("因子家族"),
        families, familyDraft(initialValue) ? [familyRef(initialValue.__factor_family)] : [],
        async selected => {
          const selectedValue = selectionValue(selected?.[0]);
          const item = families.find(candidate => (
            selectionValue(candidate.value ?? candidate.ref) === selectedValue
          ));
          if (!item) { setValue("", "family"); return; }
          const selectedFamily = await options.onSelectFamily?.(item.family) || item.family;
          setValue(makeFamilyDraft(selectedFamily), "family");
        },
        {disabled: options.readOnly === true},
      );
    }
    input.type = "text";
    const initialText = display(initialValue);
    input.value = activeSource === "manual" || activeSource === "column"
      ? initialText : "";
    input.placeholder = context.t("填写");
    input.addEventListener("input", () => {
      const raw = input.value.trim().toUpperCase();
      const matched = columns.find(item => String(item.value || "").toUpperCase() === raw);
      input.setCustomValidity("");
      if (matched) setValue(String(matched.value), "column");
      else if (!raw) setValue("", "manual", {retainSource: true});
      else {
        activeSource = "manual";
        values[alias] = input.value;
        factorPicker?.setValues?.([]);
        familyPicker?.setValues?.([]);
        sourcePicker?.setValues?.(["manual"]);
        renderNested();
        options.onChange?.(values, alias);
      }
    });
    input.addEventListener("change", async () => {
      const raw = input.value.trim();
      if (!raw || columns.some(item => String(item.value || "").toUpperCase() === raw.toUpperCase())) return;
      const constant = numericConstant(raw);
      if (constant !== null) {
        setValue(constant, "manual");
        return;
      }
      try {
        const resolved = await options.onValidateFactorAlias?.(raw);
        if (!resolved?.valid || !resolved.factor_alias) throw new Error(
          resolved?.error || context.t("因子 alias 无法解析"),
        );
        const factor = resolved.factor || String(resolved.factor_alias);
        const enriched = options.onSelectFactor?.(factor, resolved);
        if (enriched && typeof enriched.then === "function") {
          await enriched.then(value => setValue(value || factor, "manual"));
        } else {
          setValue(enriched || factor, "manual");
        }
      } catch (error) {
        input.setCustomValidity(error?.message || context.t("请输入有效的 ColumnRef 或因子 alias"));
        input.reportValidity();
      }
    });
    let createFamily = null;
    if (allowFamilyComposition) {
      createFamily = actionButton(context, context.t(
        familyDraft(values[alias]) ? "编辑因子家族" : "新增因子家族",
      ), async () => {
        const currentFamily = familyDraft(values[alias])
          ? values[alias].__factor_family : null;
        await options.onCreateFamily?.(family => {
          if (!family) return;
          if (!families.some(item => selectionValue(item.value ?? item.ref) === familyRef(family))) {
            families.push({
              value: familyRef(family), label: familyLabel(family), family,
              description: context.t("本次配置中当场新建"),
            });
            familyPicker?.setItems?.(families);
          }
          setValue(makeFamilyDraft(family), "family");
          createFamily.textContent = context.t("编辑因子家族");
        }, currentFamily);
      }, {variant: "secondary"});
      createFamily.classList?.add?.("factor-param-create-family");
    }
    const nestedMount = document.createElement("div");
    nestedMount.className = "factor-param-nested-factor-mount";
    // A frozen record only carries identity.params; parameter types and
    // defaults belong to the referenced factor family.  Load that family's
    // current template (source-backed definitions) so the nested table shows
    // real 参数类型/默认值 columns instead of guessing from the record.
    const loadNestedFamilyDefinitions = draft => {
      const identity = draft.identity || {};
      const familyAlias = String(
        identity.family_alias || draft.factor_family_alias || "",
      ).trim();
      const loader = window.FTFactorDetailShared?.loadSourceVersion;
      if (!familyAlias || typeof loader !== "function") return Promise.resolve(null);
      const ownerRef = String(draft.owner_ref || "").trim().replace(/^principal:/, "");
      const isPublic = ["public", "__public_jobs__"].includes(ownerRef);
      return loader(context, {
        factor_family_alias: familyAlias,
        factor_family_name: familyAlias,
        family_ref: identity.family_ref || draft.family_ref || "",
      }, "current", {
        familyID: familyAlias,
        sourceKind: isPublic ? "public" : undefined,
        ownerUsername: isPublic ? "" : ownerRef,
      }).then(loaded => ({
        ...(loaded || {}),
        factor_family_alias: familyAlias,
        factor_family_name: familyAlias,
      })).catch(() => null);
    };
    let nestedFamilyPending = false;
    const renderNested = () => {
      if (nestedMount.replaceChildren) nestedMount.replaceChildren();
      else nestedMount.children = [];
      const draft = values[alias];
      if (isFrozenFactor(draft) && ["factor", "manual"].includes(activeSource)) {
        const shared = window.FTFactorDetailShared;
        // Parameter types/defaults live on the referenced factor family.
        // Prefer what the current context already carries (the library
        // choice's family, or an attached template); otherwise load that
        // family once — never guess types from the frozen record.
        const choice = factorChoices.find(item => (
          selectionValue(item.value ?? item.ref) === reference(draft)
          || item.factor === draft
        ));
        const savedParams = draft.identity?.params || draft.parameter_values || {};
        const template = draft.family || draft.__factor_family
          || choice?.family || null;
        const definitionRows = (template
          ? shared?.parameterRows?.(draft, {family: template}) || []
          : shared?.parameterRows?.(draft) || [])
          .map(row => {
            const saved = savedParams[row.alias];
            return saved === undefined ? row : {...row, value: saved};
          });
        const renderSection = rowsValue => {
          const section = shared.parameterSection(
            context, {...draft, family: template}, rowsValue,
            (options.depth || 0) + 1,
          );
          section.root.dataset.parameterAlias = alias;
          nestedMount.append(section.root);
        };
        const identityRows = () => Object.entries(savedParams).map(([name, saved]) => ({
          alias: name, value: saved,
        })).filter(row => row.alias && !/^\$/.test(row.alias));
        if (definitionRows.length) {
          renderSection(definitionRows);
          return;
        }
        // No template attached yet: load the referenced factor family so the
        // 参数类型/默认值 columns are correct.  Until it arrives, do not
        // render a table that would mislabel types.
        if (!nestedFamilyPending) {
          nestedFamilyPending = true;
          void loadNestedFamilyDefinitions(draft).then(loadedFamily => {
            nestedFamilyPending = false;
            if (values[alias] !== draft) return;
            if (nestedMount.replaceChildren) nestedMount.replaceChildren();
            else nestedMount.children = [];
            if (loadedFamily) {
              const upgraded = (shared?.parameterRows?.(draft, {family: loadedFamily}) || [])
                .map(row => {
                  const saved = savedParams[row.alias];
                  return saved === undefined ? row : {...row, value: saved};
                });
              if (upgraded.length) {
                const section = shared.parameterSection(
                  context, {...draft, family: loadedFamily}, upgraded,
                  (options.depth || 0) + 1,
                );
                section.root.dataset.parameterAlias = alias;
                nestedMount.append(section.root);
                return;
              }
            }
            const rows = identityRows();
            if (rows.length) renderSection(rows);
          }).catch(() => {
            nestedFamilyPending = false;
            if (values[alias] !== draft) return;
            if (nestedMount.replaceChildren) nestedMount.replaceChildren();
            else nestedMount.children = [];
            const rows = identityRows();
            if (rows.length) renderSection(rows);
          });
        }
        return;
      }
      // A hand-typed value (manual source) is parsed into its visible form:
      // an alias renders a read-only parameter table; a numeric constant is
      // shown as ConstExpr; a data column as ColumnRef — so the reference is
      // inspectable before any validation round-trip.
      if (activeSource === "manual" && typeof draft === "string"
        && draft.trim()) {
        const text = draft.trim();
        if (text.includes("|")) {
          const analysis = parseFactorAlias(text);
          const aliasRows = analysis && Object.keys(analysis.params).length
            ? Object.entries(analysis.params).map(([name, value]) => ({
              alias: name, value,
            })) : [];
          if (aliasRows.length) {
            const section = window.FTFactorDetailShared.parameterSection(
              context, {...draft, family: null}, aliasRows,
              (options.depth || 0) + 1,
            );
            section.root.dataset.parameterAlias = alias;
            nestedMount.append(section.root);
          }
        } else {
          const previewKind = numericConstant(text) !== null ? "const"
            : columns.some(item => selectionValue(item.value) === text)
              || /^[A-Za-z_][A-Za-z0-9_.]*$/.test(text) ? "column" : null;
          if (previewKind) {
            const preview = document.createElement("div");
            preview.className = "factor-param-manual-preview";
            preview.textContent = previewKind === "const"
              ? `ConstExpr ${numericConstant(text)}` : `ColumnRef ${text}`;
            nestedMount.append(preview);
          }
        }
      }
      if (!familyDraft(draft)) return;
      const family = draft.__factor_family;
      const nestedValues = draft.parameter_values || {};
      const nested = create(
        context, familyParameters(family), nestedValues, {
          ...options,
          depth: (options.depth || 0) + 1,
          onChange: () => {
            section?.update?.(nested.values);
            options.onChange?.(values, alias);
          },
        },
      );
      draft.parameter_values = nested.values;
      const section = window.FTFactorDetailShared.parameterSection(
        context, family, [], (options.depth || 0) + 1,
        {content: nested.root, values: draft.parameter_values || {}},
      );
      section.root.dataset.parameterAlias = alias;
      nestedMount.append(section.root);
    };
    renderSourceControl = () => {
      if (sourceControl.replaceChildren) sourceControl.replaceChildren();
      else sourceControl.children = [];
      if (!activeSource) return;
      if (activeSource === "manual") {
        sourceControl.append(input);
        return;
      }
      if (activeSource === "column") {
        sourceControl.append(columnPicker.element || columnPicker);
        return;
      }
      if (activeSource === "factor") {
        sourceControl.append(factorPicker.element || factorPicker);
        return;
      }
      if (activeSource === "family" && familyPicker) {
        const familySource = document.createElement("div");
        familySource.className = "factor-param-family-source";
        familySource.append(familyPicker.element || familyPicker);
        if (createFamily) familySource.append(createFamily);
        sourceControl.append(familySource);
      }
    };
    control.append(sourcePicker.element || sourcePicker, sourceControl);
    row.append(control);
    renderNested();
    renderSourceControl();
    return nestedMount;
  }

  function parameterType(context, parameter) {
    const root = document.createElement("span");
    root.className = "factor-detail-parameter-type";
    const name = document.createElement("span");
    name.textContent = String(parameter.type || parameter.param_type || "Parameter");
    root.append(name);
    const help = String(parameter.input_help || parameter.desc
      || parameter.value_space_desc || context.t("填写该参数类型允许的值。"))
      .trim();
    root.append(" ", (window.FTUI?.helpIcon || window.FTHelp?.create)(help, {
      ariaLabel: context.t("查看参数类型说明"),
    }));
    return root;
  }

  function displayValue(value) {
    if (value === undefined || value === null || value === "") return "—";
    if (typeof value === "object") {
      return String(value.alias || value.factor_alias || value.value || JSON.stringify(value));
    }
    return String(value);
  }

  function numericConstant(value) {
    const text = String(value || "").trim();
    if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(text)) {
      return null;
    }
    const parsed = Number(text);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function picker(context, name, title, items, selected, onChange, pickerOptions = {}) {
    return (window.FTTestObjectPicker || window.FTMultiSelectFilter).create(context, {
      compact: true, multi: false,
      name, title, items, selected, onChange,
      disabled: pickerOptions.disabled === true,
    });
  }

  function familyDraft(value) {
    return Boolean(value && typeof value === "object"
      && value.__factor_family_draft === true && value.__factor_family);
  }

  function isFrozenFactor(value) {
    return Boolean(value && typeof value === "object"
      && value.schema_version === 2
      && (value.ref || value.factor_ref)
      && (value.alias || value.factor_alias));
  }

  // A factor-library reference may arrive either as the opaque ``factor:v2``
  // ref string (as stored in identity.params) or as its frozen v2 record.
  function isFrozenFactorValue(value) {
    if (typeof value === "string") return value.startsWith("factor:v2:");
    return isFrozenFactor(value);
  }

  // Parse a display alias like ``SgChgPct|P:[CA]|M:0.6|B:1|N:200d|$F:1d``
  // into {family, params}; engine-internal keys ($F/$Rev) are dropped.
  function parseFactorAlias(alias) {
    const text = String(alias || "").trim();
    const segments = text.split("|").map(part => part.trim()).filter(Boolean);
    if (segments.length < 2) return null;
    const params = {};
    for (const segment of segments.slice(1)) {
      const separator = segment.indexOf(":");
      if (separator <= 0) continue;
      const key = segment.slice(0, separator).trim();
      const value = segment.slice(separator + 1).trim();
      if (key && !key.startsWith("$")) params[key] = value;
    }
    return {family: segments[0], params};
  }

  function familyParameters(family) {
    const shared = window.FTFactorDetailShared?.parameterRows?.(family);
    if (Array.isArray(shared) && shared.length) return shared;
    const candidates = [
      family?.parameter_definitions,
      family?.params,
      family?.factor_params,
      family?.parameters,
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

  function makeFamilyDraft(family) {
    return {
      __factor_family_draft: true,
      __factor_family: family,
      parameter_values: Object.fromEntries(
        familyParameters(family).map(parameter => [
          parameter.alias || parameter.name,
          parameter.value ?? parameter.default_value ?? "",
        ]).filter(([alias]) => alias),
      ),
    };
  }

  function familyRef(value) {
    return String(value?.family_ref || value?.factor_family_alias
      || value?.family_alias || value?.name || "").trim();
  }

  function familyLabel(value) {
    return String(value?.factor_family_alias || value?.family_alias
      || value?.family_class_name || value?.name || "因子家族").trim();
  }

  function actionButton(context, label, onClick) {
    if (FTUI.actionButton) {
      return FTUI.actionButton(label, onClick, {variant: "secondary"});
    }
    if (context.button) return context.button(label, onClick, label);
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.addEventListener("click", onClick);
    return button;
  }

  window.FTFactorParameterEditor = Object.freeze({create});
})();
