(() => {
  function documentFor(state) {
    const payload = window.FTTestConfiguration.configurationPayload(
      state, null, {allowIncomplete: true},
    );
    return {
      schema_version: 1,
      document_kind: "research_configuration",
      analyses: [state.kind],
      configuration: payload,
      run_fields: FTTestState.registeredRunValues(state),
    };
  }

  function schemaFor(state) {
    const runProperties = Object.fromEntries(
      (state.manifest?.run_fields || []).map(field => [field.key, {
        ...(field.value_descriptor?.editor === "number" ? {type: "number"} : {}),
        description: field.label || field.key,
      }]),
    );
    const itemContract = state.manifest?.configuration_item_contract;
    const itemSchema = itemContract?.schema;
    if (!itemSchema) {
      throw new Error("test manifest is missing its configuration-item contract");
    }
    const analysisSchema = state.kind === "backtest" ? {
      type: "object",
      required: ["groups"],
      properties: {
        groups: {
          type: "array", minItems: 1,
          items: structuredClone(itemSchema),
        },
      },
    } : {
      type: "object",
      required: ["configuration_groups"],
      properties: {
        configuration_groups: {
          type: "array",
          minItems: Number(itemContract.min_items) || 1,
          maxItems: Number(itemContract.max_items) || undefined,
          items: structuredClone(itemSchema),
        },
      },
    };
    return {
      type: "object",
      required: [
        "schema_version", "document_kind", "analyses", "configuration", "run_fields",
      ],
      properties: {
        schema_version: {const: 1},
        document_kind: {const: "research_configuration"},
        analyses: {type: "array", items: {enum: [state.kind]}},
        run_fields: {
          type: "object", properties: runProperties, additionalProperties: false,
        },
        configuration: {
          type: "object", required: ["schema_version", "analyses"],
          properties: {
            analyses: {
              type: "object", required: [state.kind],
              properties: {[state.kind]: analysisSchema},
            },
          },
        },
      },
      additionalProperties: false,
      "x-factor-tester-field-registry": structuredClone(state.manifest || {}),
      "x-run-spec-shape": "RunRequest(configuration + registered run_fields)",
      "x-canonical-settings-path": `configuration.ui.${state.kind}.settings`,
    };
  }

  function semanticKey(value) {
    return String(value || "").replace(/[^a-zA-Z0-9]/g, "").toLowerCase();
  }

  function sameValue(left, right) {
    return JSON.stringify(left) === JSON.stringify(right);
  }

  function canonicalDocument(state, source) {
    const document = structuredClone(source);
    const configuration = document.configuration || {};
    const analysis = configuration.analyses?.[state.kind];
    if (!analysis || typeof analysis !== "object") return document;
    configuration.ui = configuration.ui || {};
    const ui = configuration.ui[state.kind] || (configuration.ui[state.kind] = {});
    const settings = ui.settings && typeof ui.settings === "object"
      ? ui.settings : (ui.settings = {});
    const localSettings = analysis.local_settings
      && typeof analysis.local_settings === "object"
      ? analysis.local_settings : {};
    const currentAuthoring = FTTestConfigurationCompiler.authoringSettings(
      state.manifest, state.values || {},
    );
    const currentExecution = FTTestConfigurationCompiler.executionSettings(
      state.manifest, currentAuthoring,
    );
    const incomingExecution = FTTestConfigurationCompiler.executionSettings(
      state.manifest, settings,
    );
    for (const [fieldKey, field] of Object.entries(state.manifest?.defaults || {})) {
      if (field?.execution_policy === "authoring_only") continue;
      const storageKey = field?.serialization?.storage_key || fieldKey;
      const hasUI = Object.prototype.hasOwnProperty.call(incomingExecution, storageKey);
      const hasLocal = Object.prototype.hasOwnProperty.call(localSettings, storageKey);
      if (!hasUI && !hasLocal) continue;
      if (!hasLocal) continue;
      if (!hasUI) {
        settings[fieldKey] = structuredClone(localSettings[storageKey]);
        continue;
      }
      const current = currentExecution[storageKey];
      const uiValue = incomingExecution[storageKey];
      const localValue = localSettings[storageKey];
      if (sameValue(uiValue, localValue)) continue;
      const uiChanged = !sameValue(uiValue, current);
      const localChanged = !sameValue(localValue, current);
      if (localChanged && !uiChanged) {
        settings[fieldKey] = structuredClone(localValue);
        continue;
      }
      if (uiChanged && !localChanged) continue;
      throw new Error(`测试设置 ${fieldKey} 在页面字段与运行配置中不一致`);
    }
    analysis.local_settings = FTTestConfigurationCompiler.executionSettings(
      state.manifest, settings,
    );
    return document;
  }

  function navigationFor(state) {
    const document = documentFor(state);
    const manifest = state.manifest || {};
    const analysis = document.configuration?.analyses?.[state.kind] || {};
    const ui = document.configuration?.ui?.[state.kind] || {};
    const mounted = new Set((ui.mounted_tabs || []).map(semanticKey));
    const values = {
      ...(analysis.local_settings || {}),
      ...(ui.settings || {}),
      ...(document.run_fields || {}),
    };
    const contracts = manifest.field_contracts?.settings || manifest.defaults || {};
    const chips = Array.isArray(manifest.chip_fields) ? manifest.chip_fields : [];
    const modules = Array.isArray(manifest.modules) ? manifest.modules : [];
    const nodes = {};
    const tabIDs = [];
    for (const module of modules) {
      const key = String(module.key || "").trim();
      if (!key) continue;
      const tabID = `tab:${key}`;
      tabIDs.push(tabID);
      const fieldIDs = [];
      for (const [fieldKey, contract] of Object.entries(contracts)) {
        const owner = contract?.module || contract?.tab_key;
        if (semanticKey(owner) !== semanticKey(key)) continue;
        const fieldID = `field:${fieldKey}`;
        fieldIDs.push(fieldID);
        nodes[fieldID] = {
          id: fieldID,
          kind: "field",
          label: contract.label || fieldKey,
          field_key: fieldKey,
          value: values[fieldKey] === undefined
            ? null : structuredClone(values[fieldKey]),
          value_descriptor: structuredClone(contract.value_descriptor || {}),
          rules: structuredClone(contract.rules || []),
          candidate_source: contract.value_descriptor?.candidate_source || null,
          children: [],
        };
      }
      nodes[tabID] = {
        id: tabID,
        kind: "tab",
        label: module.label || key,
        summary: mounted.has(semanticKey(key)) ? "mounted" : "available",
        mounted: mounted.has(semanticKey(key)),
        chips: chips.filter(chip => (
          semanticKey(chip.module) === semanticKey(key)
        )).map(chip => ({
          key: chip.key,
          label: chip.label || chip.key,
          field_node: `field:${chip.key}`,
        })),
        children: fieldIDs,
      };
    }
    const groups = state.kind === "backtest"
      ? analysis.groups || [] : analysis.configuration_groups || [];
    const groupContract = manifest.configuration_item_contract?.schema;
    const groupIDs = groups.map((group, index) => {
      const key = String(
        group.id || group.config_group_id || group.name || index,
      );
      const id = `configuration:${key}`;
      const fieldIDs = Object.entries(groupContract?.properties || {}).map(
        ([fieldKey, descriptor]) => {
          const fieldID = `${id}:field:${fieldKey}`;
          nodes[fieldID] = {
            id: fieldID,
            kind: "field",
            label: descriptor.title || fieldKey,
            field_key: fieldKey,
            required: (groupContract.required || []).includes(fieldKey),
            value_descriptor: structuredClone(descriptor),
            value: group[fieldKey] === undefined
              ? null : structuredClone(group[fieldKey]),
            children: [],
          };
          return fieldID;
        },
      );
      nodes[id] = {
        id,
        kind: state.kind === "backtest" ? "strategy" : "configuration-group",
        label: group.name || group.label || key,
        summary: `${Object.keys(group).length} registered values`,
        configuration_ref: key,
        children: fieldIDs,
      };
      return id;
    });
    nodes.configurations = {
      id: "configurations",
      kind: "collection",
      label: state.kind === "backtest" ? "策略" : "配置组",
      summary: `${groupIDs.length}`,
      children: groupIDs,
    };
    nodes.page = {
      id: "page",
      kind: "page",
      label: state.kind === "backtest" ? "回测配置" : "IC 测试配置",
      summary: `${mounted.size} mounted tabs`,
      children: [...tabIDs, "configurations"],
    };
    return {schema_version: 1, root_id: "page", nodes};
  }

  function register(context, state, refresh) {
    const existing = state.pageAssistanceRegistration;
    if (existing && existing.pageState === context.pageState) return existing.controller;
    const controller = FTPageAssistance.register(context, {
      prepare: () => FTTestLazyCode.loadGroup("workbench-run-submit"),
      navigation: () => navigationFor(state),
      schema: () => schemaFor(state),
      exportDocument: () => documentFor(state),
      validate: document => {
        if (document?.document_kind !== "research_configuration"
            || document?.configuration?.schema_version !== 2
            || !document.configuration.analyses?.[state.kind]) {
          throw new Error("测试配置文档与当前测试类型不兼容");
        }
        if (state.kind === "backtest"
            && !document.configuration.analyses.backtest.groups?.length) {
          throw new Error("回测配置至少需要一个策略");
        }
        const analysis = document.configuration.analyses[state.kind];
        const misplaced = (state.manifest?.run_fields || [])
          .map(field => field.key)
          .filter(key => Object.prototype.hasOwnProperty.call(analysis, key));
        if (misplaced.length) {
          throw new Error(
            `任务提交字段必须写入文档顶层 run_fields: ${misplaced.join(", ")}`,
          );
        }
        canonicalDocument(state, document);
      },
      importDocument: document => {
        const canonical = canonicalDocument(state, document);
        state.workspace = state.workspace || {workspace_id: ""};
        state.workspace.configuration = {
          ...(state.workspace.configuration || {}),
          payload: structuredClone(canonical.configuration),
        };
        FTTestState.applyWorkspaceConfiguration(state);
        FTTestState.seedSavedCatalogs(state);
        FTTestState.applyRegisteredRunValues(state, document.run_fields || {});
        if (state.kind === "backtest") {
          window.FTBacktestGroupModel?.initialize?.(state);
        }
        state.settingsInitialized = false;
      },
      afterApply: refresh,
    }, {
      pageKind: `${state.kind}-configuration`,
      view: () => ({selected_settings_tab: state.settingsTabKey || ""}),
    });
    state.pageAssistanceRegistration = {pageState: context.pageState, controller};
    return controller;
  }

  window.FTTestPageAssistance = Object.freeze({
    canonicalDocument, documentFor, navigationFor, register, schemaFor,
  });
})();
