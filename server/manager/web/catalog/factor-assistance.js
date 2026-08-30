(() => {
  function register(context, options) {
    const {state, name, chineseName, description, category, tabs, redraw, markDirty} = options;
    return FTPageAssistance.register(context, {
      navigation: () => ({
        schema_version: 1,
        root_id: "page",
        nodes: {
          page: {
            id: "page", kind: "page",
            label: `${state.mode === "edit" ? "编辑" : "新建"}${state.familyMode ? "因子家族" : "因子"}`,
            children: ["section:metadata", "section:source", "section:parameters"],
          },
          "section:metadata": {
            id: "section:metadata", kind: "section", label: "基本信息",
            children: ["field:name", "field:chinese_name", "field:description", "field:category"],
          },
          "section:source": {
            id: "section:source", kind: "section", label: "Python 源码",
            children: ["field:source_mode", "field:source_code"],
          },
          "section:parameters": {
            id: "section:parameters", kind: "section", label: "参数",
            children: ["field:parameter_values"],
          },
          "field:name": {id: "field:name", kind: "field", label: "名称", value: name.value, children: []},
          "field:chinese_name": {id: "field:chinese_name", kind: "field", label: "中文名", value: chineseName.value, children: []},
          "field:description": {id: "field:description", kind: "field", label: "描述", value: description.value, children: []},
          "field:category": {id: "field:category", kind: "field", label: "类别", value: category.value, children: []},
          "field:source_mode": {id: "field:source_mode", kind: "field", label: "源码方式", value: state.sourceMode, children: []},
          "field:source_code": {id: "field:source_code", kind: "field", label: "源码", value: state.sourceCode, children: []},
          "field:parameter_values": {id: "field:parameter_values", kind: "field", label: "参数值", value: structuredClone(state.parameterValues || {}), children: []},
        },
      }),
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
        redraw(); markDirty("source");
      },
    }, {
      pageKind: `${state.familyMode ? "factor-family" : "factor"}-${state.mode}`,
      view: () => ({selected_tab: tabs.current()}),
    });
  }

  window.FTFactorAssistance = Object.freeze({register});
})();
