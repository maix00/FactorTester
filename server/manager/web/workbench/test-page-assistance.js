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
    };
  }

  function schemaFor(state) {
    const analysisSchema = state.kind === "backtest" ? {
      type: "object",
      required: ["groups"],
      properties: {
        groups: {
          type: "array", minItems: 1,
          items: {
            type: "object",
            required: [
              "id", "factor_candidate_refs", "product_path_selection",
              "splitCount", "groupIndex",
            ],
            properties: {
              id: {type: "string", minLength: 1},
              factor_candidate_refs: {
                type: "array", minItems: 1,
                items: {type: "string", minLength: 1},
              },
              product_path_selection: {type: "object"},
              splitCount: {type: "integer", minimum: 1},
              groupIndex: {type: "integer", minimum: 1},
            },
          },
        },
      },
    } : {type: "object"};
    return {
      type: "object",
      required: ["schema_version", "document_kind", "analyses", "configuration"],
      properties: {
        schema_version: {const: 1},
        document_kind: {const: "research_configuration"},
        analyses: {type: "array", items: {enum: [state.kind]}},
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
      "x-run-spec-shape": "RunSpec.configuration",
    };
  }

  function register(context, state, refresh) {
    return FTPageAssistance.register(context, {
      prepare: () => FTTestLazyCode.loadGroup("workbench-run-submit"),
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
      },
      importDocument: document => {
        state.workspace = state.workspace || {workspace_id: ""};
        state.workspace.configuration = {
          ...(state.workspace.configuration || {}),
          payload: structuredClone(document.configuration),
        };
        FTTestState.applyWorkspaceConfiguration(state);
        FTTestState.seedSavedCatalogs(state);
        if (state.kind === "backtest") {
          window.FTBacktestGroupModel?.initialize?.(state);
        }
        state.settingsInitialized = false;
        refresh();
      },
    }, {
      pageKind: `${state.kind}-configuration`,
      view: () => ({selected_settings_tab: state.settingsTabKey || ""}),
    });
  }

  window.FTTestPageAssistance = Object.freeze({documentFor, register, schemaFor});
})();
