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
    // FactorParam is now a single multi-type single-select: the candidate pool
    // is DataColumn / 手填排他(manual) / 因子 — no family source.  Family
    // composition remains only as a value shape (see renderNested), never as a
    // selectable 来源.
    const sourceTypes = [
      {
        value: "manual", label: context.t("手填排他"),
        description: context.t("手动填写 ConstExpr、DataColumn alias 或因子 alias"),
      },
      {
        value: "column", label: context.t("DataColumn"),
        description: context.t("从 DataColumn 候选中选择"),
      },
      {
        value: "factor", label: context.t("因子"),
        description: context.t("从当前可见因子中选择，或当场新建"),
      },
    ];
    // Family composition is no longer a FactorParam source; keep the value
    // shape handled below but never surface the 因子家族 来源/编辑 UI.
    const allowFamilyComposition = false;
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
    // Only references present in the visible library rows are 因子库
    // sources.  A frozen combination that is not in the library (freshly
    // saved parameters, another scope) reopens as its alias on the manual
    // source instead of claiming a library origin it does not have.
    const factorChoices = [...factors];
    let activeSource = "";
    // Preserve the value's origin: a factor-library reference (opaque
    // ``factor:v2`` ref or a frozen v2 record) reopens on the 因子库 source;
    // hand-typed aliases/columns stay manual/column; on-the-fly family
    // compositions stay family.  Never degrade any of them into the others.
    const frozenInitial = isFrozenFactorValue(initialValue);
    // A value is a 因子库 source when its ref (or its alias, e.g. for rows
    // echoed through a different digest) matches a visible library row.
    // Matching is done per nesting level, recursively, as levels open.
    const inLibraryRows = value => factorChoices.some(item => {
      const candidateFactor = item.factor || item;
      return selectionValue(item.value ?? item.ref) === reference(value)
        || String(item.label || display(candidateFactor) || "").trim()
          === String(display(value) || "").trim();
    });
    if (familyDraft(initialValue)) {
      activeSource = "family";
    } else if (frozenInitial && inLibraryRows(initialValue)) {
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
    // Unified multi-type single-select: DataColumn + 因子 candidates grouped as
    // 「候选(DataColumn)」「候选(因子)」, 手填排他 via exclusiveManual, no family
    // source.  Selecting a value resolves its source and drives setValue.
    const candidateItems = [
      ...columns.map(c => {
        const id = selectionValue(c.value ?? c);
        return {
          value: id,
          label: String(c.label || c.alias || c.value || c).trim() || id,
          type: "column", typeLabel: context.t("DataColumn"), column: c,
        };
      }),
      ...factors.map(f => {
        const factor = f.factor || f;
        const id = selectionValue(f.value ?? f.ref ?? factor);
        return {
          value: id,
          label: display(factor) || id,
          type: "factor", typeLabel: context.t("因子"), factor,
          view: window.FTFactorDetailShared?.factorRowView?.(factor)
            || {kind: "factor", ref: id},
        };
      }),
    ].filter(item => item.value);
    let valuePicker;
    valuePicker = (window.FTTestObjectPicker || window.FTMultiSelectFilter).create(context, {
      compact: true, multi: false,
      name: `factor-param-${alias}`,
      title: context.t("参数值"),
      items: candidateItems,
      selected: [selectionValue(values[alias])].filter(Boolean),
      loading: Boolean(options.loading),
      loadingText: context.t("正在读取参数候选…"),
      groupByType: true,
      exclusiveManual: {
        label: context.t("手填排他"),
        placeholder: context.t("填写 ConstExpr、DataColumn alias 或因子 alias"),
      },
      onAddCandidateForType: (type, _ctx, {add}) => {
        if (type !== "factor") return; // a DataColumn cannot be created on the fly
        const open = value => {
          if (!value) return;
          const id = selectionValue(value);
          add({
            value: id, label: display(value) || id, factor: value,
            type: "factor", typeLabel: context.t("因子"),
            view: window.FTFactorDetailShared?.factorRowView?.(value)
              || {kind: "factor", ref: id},
          });
          setValue(value, "factor");
        };
        if (typeof options.onCreateFactor === "function") {
          void options.onCreateFactor(open);
        } else if (window.FTTestLazyCode?.openObjectEditor) {
          void window.FTTestLazyCode.openObjectEditor(context, {
            kind: "factor", mode: "create", ref: "new", onSaved: open,
            testState: options.testState, temporary: true,
          });
        }
      },
      // 手填排他 (exclusiveManual): resolve a typed value into ConstExpr /
      // DataColumn / 因子 alias.  An alias resolves through the host so any
      // nested factor-family source versions are fixed at parse time.
      onChange: async values => {
        const v = selectionValue(values[0]);
        if (!v) { setValue("", ""); return; }
        const colItem = candidateItems.find(item => (
          item.type === "column" && item.value === v
        ));
        if (colItem) { setValue(v, "column"); return; }
        const facItem = candidateItems.find(item => (
          item.type === "factor" && item.value === v
        ));
        if (facItem) {
          const factor = facItem.factor || facItem;
          // Library / on-the-fly factor selection resolves through the host so
          // nested family source versions are fixed at selection time.
          const resolved = options.onSelectFactor?.(factor, facItem);
          if (resolved && typeof resolved.then === "function") {
            await resolved.then(next => setValue(next || factor, "factor"));
          } else {
            setValue(resolved || factor, "factor");
          }
          return;
        }
        // Hand-typed exclusive value.
        const constant = numericConstant(v);
        if (constant !== null) { setValue(constant, "manual"); return; }
        if (columns.some(item => selectionValue(item.value) === v)) {
          setValue(v, "column");
          return;
        }
        try {
          const resolved = typeof options.onValidateFactorAlias === "function"
            ? await options.onValidateFactorAlias(v) : null;
          if (resolved?.valid && (resolved.factor || resolved.factor_alias)) {
            setValue(resolved.factor || String(resolved.factor_alias), "manual");
            return;
          }
        } catch (_error) { /* fall through to a literal manual value */ }
        setValue(v, "manual");
      },
    });
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
    let editingFactor = false;
    const editingParams = {};
    let onTheFlyFactor = null;
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
        // The tree header renders the family template LaTeX and the family
        // alias as title; the frozen record alone carries neither, so build
        // the section value from the attached/loaded family template.
        const familyAliasOf = String(
          draft.identity?.family_alias || draft.factor_family_alias
          || draft.factor_family_name || String(draft.alias || "").split("|")[0]
          || (template?.factor_family_alias) || "",
        ).trim();
        const sectionValue = templateValue => ({
          ...draft,
          family: templateValue || null,
          factor_family_alias: familyAliasOf,
          factor_family_name: familyAliasOf,
          math_expr: templateValue?.math_expr || templateValue?.formula
            || templateValue?.latex || "",
        });
        // Even when the reference exists in the library, the nested
        // parameter list offers an edit entry (next to the 参数值 column
        // heading) that switches the value into 因子家族来源 mode (editable
        // family composition); saving goes through the existing on-the-fly
        // freeze path.
        // Report the referenced family template so the outer editor's top
        // formula preview can render the nested definition lines too (the
        // frozen record carries only identity params, no template formula).
        const reportNestedFamily = fam => {
          if (fam && typeof options.onNestedFamilyTemplate === "function") {
            options.onNestedFamilyTemplate(familyAliasOf, fam);
          }
        };
        if (choice?.family) reportNestedFamily(choice.family);
        let currentTemplate = template;
        const unlockFamilyEditing = () => {
          const family = currentTemplate;
          if (!family) return;
          // Make sure the family appears among the 因子家族 candidates so
          // the picker actually shows it as selected.
          if (!families.some(item => (
            selectionValue(item.value ?? item.ref) === familyRef(family)
          ))) {
            families.push({
              value: familyRef(family),
              label: familyLabel(family),
              family,
              description: context.t("本次配置中当场新建"),
            });
            familyPicker?.setItems?.(families);
          }
          const composed = makeFamilyDraft(family);
          composed.parameter_values = {
            ...(composed.parameter_values || {}),
            ...(draft.identity?.params || draft.parameter_values || {}),
          };
          setValue(composed, "family");
        };
        // Pencil → create a backup on-the-fly factor, then let edits mutate
        // that factor in place and sync its alias back to the selected display.
        const unlockFactorEditing = () => {
          editingFactor = true;
          const base = draft && typeof draft === "object" ? draft : {};
          const saved = draft?.identity?.params || draft?.parameter_values || {};
          const identity = {...(draft?.identity || {}), params: {...saved}};
          const familyMeta = draft?.family
            || {factor_family_alias: draft?.identity?.family_alias || draft?.factor_family_alias};
          onTheFlyFactor = {
            ...base,
            identity,
            params: Object.entries(saved)
              .filter(([key]) => key && !key.startsWith("$"))
              .map(([key, value]) => ({alias: key, value})),
            parameter_values: {...saved},
            family: familyMeta,
            temporary: true,
            source_origin: base.source_origin || "test_inline",
            alias: base.alias || base.factor_alias
              || composeFactorAlias(familyMeta, saved),
          };
          onTheFlyFactor.factor_alias = onTheFlyFactor.alias;
          setValue(onTheFlyFactor, "factor");
          renderNested();
        };
        const unlockLabel = context.t("编辑");
        const editEntry = window.FTUI?.iconButton
          ? window.FTUI.iconButton(
            context, "square.and.pencil", unlockLabel, unlockFactorEditing,
            {className: "factor-param-nested-edit"},
          )
          : (() => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "icon-action-button factor-param-nested-edit";
            button.textContent = "✎";
            button.title = unlockLabel;
            button.addEventListener("click", unlockFactorEditing);
            return button;
          })();
        const definitionRows = (template
          ? shared?.parameterRows?.(draft, {family: template}) || []
          : shared?.parameterRows?.(draft) || [])
          .map(row => {
            const saved = savedParams[row.alias];
            return saved === undefined ? row : {...row, value: saved};
          });
        const renderSection = (rowsValue, templateValue) => {
          // When the pencil has converted the factor into an on-the-fly
          // (editable) factor, the value column becomes editable inputs that
          // write back to the factor's identity params.
          const renderValue = (cell, param, initVal, vals, row) => {
            if (!editingFactor) return undefined;
            const edit = document.createElement("input");
            edit.value = initVal;
            edit.addEventListener("input", () => {
              editingParams[param.alias] = edit.value;
              if (onTheFlyFactor) {
                // Mutate the backup on-the-fly factor in place.
                onTheFlyFactor.identity.params[param.alias] = edit.value;
                onTheFlyFactor.parameter_values[param.alias] = edit.value;
                onTheFlyFactor.params = Object.entries(onTheFlyFactor.identity.params)
                  .filter(([key]) => key && !key.startsWith("$"))
                  .map(([key, value]) => ({alias: key, value}));
                // Recompute the alias and sync it into the picker display.
                const familyMeta = onTheFlyFactor.family
                  || {factor_family_alias: onTheFlyFactor.identity.family_alias};
                const alias = composeFactorAlias(familyMeta, onTheFlyFactor.identity.params);
                onTheFlyFactor.alias = alias;
                onTheFlyFactor.factor_alias = alias;
                const ref = reference(onTheFlyFactor);
                const idx = candidateItems.findIndex(item => (
                  item.type === "factor" && item.value === ref
                ));
                if (idx >= 0 && candidateItems[idx]) candidateItems[idx].label = alias;
                valuePicker?.setItems?.(candidateItems, true);
              }
              options.onChange?.(values, alias);
            });
            cell.append(edit);
            return {control: true};
          };
          const section = shared.parameterSection(
            context,
            sectionValue(templateValue === undefined ? template : templateValue),
            rowsValue, (options.depth || 0) + 1,
            {valueHeaderExtra: editEntry, renderValue},
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
                currentTemplate = loadedFamily;
                reportNestedFamily(loadedFamily);
                renderSection(upgraded, loadedFamily);
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
              context, {
                ...draft, family: null,
                factor_family_alias: analysis.family || "",
                factor_family_name: analysis.family || "",
              }, aliasRows,
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
      // Single multi-type value picker (DataColumn / 手填排他 / 因子).
      if (valuePicker) sourceControl.append(valuePicker.element || valuePicker);
    };
    control.append(sourceControl);
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

  // Compose a factor alias (e.g. `SgChgPct|P:[CA]|M:0.6|B:1|N:200d`) from a
  // family template and its parameter values, preserving the template order.
  function composeFactorAlias(family, params) {
    const familyAlias = String(
      family?.factor_family_alias || family?.family_alias || family || "",
    ).trim();
    const order = (family?.parameter_definitions || [])
      .map(p => p?.alias || p?.name).filter(Boolean);
    const entries = Object.entries(params || {})
      .filter(([key]) => key && !key.startsWith("$"));
    let ordered = entries;
    if (order.length) {
      const seen = new Set(order);
      const rest = entries.filter(([key]) => !seen.has(key));
      ordered = [
        ...order.filter(key => params[key] !== undefined).map(key => [key, params[key]]),
        ...rest,
      ];
    }
    return [familyAlias, ...ordered.map(([key, value]) => `${key}:${value}`)]
      .filter(Boolean).join("|");
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
