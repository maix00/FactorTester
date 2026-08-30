(() => {
  function documentFor(state) {
    const payload = FTTestConfigurationCompiler.authoringConfiguration(
      window.FTTestConfiguration.configurationPayload(
        state, null, {allowIncomplete: true},
      ),
      state.kind,
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
    const configurationSchemaVersion = Number(
      state.manifest?.research_configuration_schema_version,
    );
    if (!Number.isInteger(configurationSchemaVersion)
        || configurationSchemaVersion < 1) {
      throw new Error("test manifest is missing the configuration schema version");
    }
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
      "x-forbidden-properties": FTTestConfigurationCompiler.derivedSettingsKeys(),
      properties: {
        groups: {
          type: "array", minItems: 1,
          items: structuredClone(itemSchema),
        },
      },
    } : {
      type: "object",
      required: ["configuration_groups"],
      "x-forbidden-properties": FTTestConfigurationCompiler.derivedSettingsKeys(),
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
            schema_version: {const: configurationSchemaVersion},
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

  function canonicalDocument(state, source) {
    const document = structuredClone(source);
    const ui = document.configuration?.ui?.[state.kind];
    if (ui && typeof ui === "object") {
      ui.mounted_tabs = FTTestConfigurationCompiler.authoringMountedTabs(
        state.manifest, ui.settings || {}, ui.explicit_mounted_tabs,
      );
      ui.mount_policy_version = 2;
    }
    document.configuration = FTTestConfigurationCompiler.executableConfiguration(
      document.configuration, state.kind, state.manifest,
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
      ...(analysis.execution?.settings || {}),
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
    const itemContract = manifest.configuration_item_contract || {};
    const groupContract = itemContract.schema;
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
      collection_path: `configuration.analyses.${state.kind}.${
        itemContract.collection_key
      }`,
      item_kind: itemContract.item_kind,
      required_fields: structuredClone(groupContract?.required || []),
      create_template: structuredClone(itemContract.create_template || {}),
      field_sources: structuredClone(itemContract.field_sources || {}),
      batch_contract: structuredClone(itemContract.batch_contract || {}),
      item_schema: structuredClone(groupContract || {}),
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
        const configurationSchemaVersion = Number(
          state.manifest?.research_configuration_schema_version,
        );
        if (document?.document_kind !== "research_configuration"
            || document?.configuration?.schema_version !== configurationSchemaVersion
            || !document.configuration.analyses?.[state.kind]) {
          throw new Error("测试配置文档与当前测试类型不兼容");
        }
        if (state.kind === "backtest"
            && !document.configuration.analyses.backtest.groups?.length) {
          throw new Error("回测配置至少需要一个策略");
        }
        const analysis = document.configuration.analyses[state.kind];
        for (const key of FTTestConfigurationCompiler.derivedSettingsKeys()) {
          if (Object.prototype.hasOwnProperty.call(analysis, key)) {
            throw new Error(
              `测试设置 ${key} 是由页面注册字段生成的只读运行配置`,
            );
          }
        }
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
