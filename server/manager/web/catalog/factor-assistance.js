(() => {
  function register(context, options) {
    const {state, name, chineseName, description, category, tabs, redraw, markDirty} = options;
    return FTPageAssistance.register(context, {
      schema: () => ({
        type: "object",
        required: ["schema_version", "document_kind", "name", "source"],
        properties: {
          schema_version: {const: 1},
          document_kind: {const: state.familyMode ? "factor_family_draft" : "factor_draft"},
          name: {type: "string"}, chinese_name: {type: "string"},
          description: {type: "string"}, category: {type: "string"},
          source: {type: "object", required: ["mode", "code"]},
          parameter_values: {type: "object"},
        },
        additionalProperties: false,
      }),
      exportDocument: () => ({
        schema_version: 1,
        document_kind: state.familyMode ? "factor_family_draft" : "factor_draft",
        name: name.value, chinese_name: chineseName.value,
        description: description.value, category: category.value,
        source: {mode: state.sourceMode, code: state.sourceCode},
        parameter_values: structuredClone(state.parameterValues || {}),
      }),
      validate: document => {
        if (!String(document?.name || "").trim()) throw new Error("因子名称不能为空");
        if (!String(document?.source?.code || "").trim()) throw new Error("因子源码不能为空");
      },
      importDocument: document => {
        name.value = String(document.name || "");
        chineseName.value = String(document.chinese_name || "");
        description.value = String(document.description || "");
        category.value = String(document.category || "");
        state.sourceMode = String(document.source?.mode || state.sourceMode);
        state.sourceCode = String(document.source?.code || "");
        state.parameterValues = structuredClone(document.parameter_values || {});
        redraw(); markDirty();
      },
    }, {
      pageKind: state.familyMode ? "factor-family-create" : "factor-create",
      view: () => ({selected_tab: tabs.current()}),
    });
  }

  window.FTFactorAssistance = Object.freeze({register});
})();
