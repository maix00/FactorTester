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
    return {
      type: "object",
      required: ["schema_version", "document_kind", "analyses", "configuration"],
      properties: {
        schema_version: {const: 1},
        document_kind: {const: "research_configuration"},
        analyses: {type: "array", items: {enum: [state.kind]}},
        configuration: {type: "object", required: ["schema_version", "analyses"]},
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
      },
      importDocument: document => {
        state.workspace = state.workspace || {workspace_id: ""};
        state.workspace.configuration = {
          ...(state.workspace.configuration || {}),
          payload: structuredClone(document.configuration),
        };
        FTTestState.applyWorkspaceConfiguration(state);
        FTTestState.seedSavedCatalogs(state);
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
