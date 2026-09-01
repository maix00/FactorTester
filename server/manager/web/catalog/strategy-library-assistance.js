(() => {
  function register(context, editor, options = {}) {
    if (!window.FTPageAssistance || !editor) return null;
    const documentKind = "strategy_library_draft";
    return FTPageAssistance.register(context, {
      navigation: () => ({
        schema_version: 1, root_id: "page",
        nodes: {
          page: {id: "page", kind: "page", label: "策略编辑", children: ["field:name", "field:description", "field:entrypoint", "field:source_code"]},
          "field:name": {id: "field:name", kind: "field", label: "策略名称", value: editor.state.name, children: []},
          "field:description": {id: "field:description", kind: "field", label: "说明", value: editor.state.description, children: []},
          "field:entrypoint": {id: "field:entrypoint", kind: "field", label: "入口类", value: editor.state.entrypoint, children: []},
          "field:source_code": {id: "field:source_code", kind: "field", label: "Python 源码", value: editor.state.source_code, children: []},
        },
      }),
      schema: () => ({
        type: "object", required: ["schema_version", "document_kind", "name", "source_code"],
        properties: {
          schema_version: {const: 1}, document_kind: {const: documentKind},
          name: {type: "string"}, description: {type: "string"},
          entrypoint: {type: "string"}, source_code: {type: "string"},
          visibility: {enum: ["private", "shared", "public"]},
        }, additionalProperties: false,
      }),
      exportDocument: () => ({
        schema_version: 1, document_kind: documentKind,
        name: editor.state.name, description: editor.state.description,
        entrypoint: editor.state.entrypoint, source_code: editor.state.source_code,
        visibility: editor.state.visibility,
      }),
      validate: document => {
        if (!String(document?.name || "").trim()) throw new Error("策略名称不能为空");
        if (!String(document?.source_code || "").trim()) throw new Error("策略源码不能为空");
      },
      importDocument: document => {
        Object.assign(editor.state, {
          name: String(document.name || ""),
          description: String(document.description || ""),
          entrypoint: String(document.entrypoint || "Strategy"),
          source_code: String(document.source_code || ""),
          visibility: String(document.visibility || editor.state.visibility || "private"),
        });
        editor.sync();
      },
    }, {
      pageKind: `strategy-${options.mode || "edit"}`,
      view: () => ({selected_tab: editor.tabs.current()}),
      ...(options.boundProfileID ? {boundProfileID: options.boundProfileID} : {}),
      ...(options.researchID ? {researchID: options.researchID} : {}),
      ...(options.resolveProfiles ? {resolveProfiles: options.resolveProfiles} : {}),
      ...(options.resolveProfile ? {resolveProfile: options.resolveProfile} : {}),
      ...(options.profileKey ? {profileKey: options.profileKey} : {}),
    });
  }

  window.FTStrategyLibraryAssistance = Object.freeze({register});
})();
