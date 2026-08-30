(() => {
  function register(context, options) {
    const {mode, state, tabs} = options;
    return FTPageAssistance.register(context, {
      navigation: () => ({
        schema_version: 1,
        root_id: "page",
        nodes: {
          page: {
            id: "page", kind: "page",
            label: `${mode === "edit" ? "编辑" : "新建"}因子集合`,
            children: ["field:set_id", "field:alias", "field:description", "field:members"],
          },
          "field:set_id": {id: "field:set_id", kind: "field", label: "集合标识", value: state.setID, children: []},
          "field:alias": {id: "field:alias", kind: "field", label: "因子集合", value: state.alias, children: []},
          "field:description": {id: "field:description", kind: "field", label: "说明", value: state.description, children: []},
          "field:members": {id: "field:members", kind: "field", label: "因子", value: structuredClone(state.members || []), children: []},
        },
      }),
      schema: () => ({
        type: "object",
        required: ["schema_version", "document_kind", "set_id", "alias", "members"],
        properties: {
          schema_version: {const: 1},
          document_kind: {const: "factor_set_draft"},
          set_id: {type: "string"}, alias: {type: "string"},
          description: {type: "string"},
          members: {type: "array", items: {type: "string"}},
        },
        additionalProperties: false,
      }),
      exportDocument: () => ({
        schema_version: 1, document_kind: "factor_set_draft",
        set_id: state.setID, alias: state.alias,
        description: state.description,
        members: structuredClone(state.members || []),
      }),
      validate: document => {
        if (!String(document?.set_id || "").trim()) throw new Error("集合标识不能为空");
        if (!String(document?.alias || "").trim()) throw new Error("因子集合名称不能为空");
        if (!Array.isArray(document?.members) || !document.members.length) {
          throw new Error("请至少选择一个因子");
        }
      },
      importDocument: document => options.onImport?.(document),
    }, {
      pageKind: `factor-set-${mode}`,
      view: () => ({selected_tab: tabs.current()}),
    });
  }

  window.FTFactorSetAssistance = Object.freeze({register});
})();
