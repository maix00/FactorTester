(() => {
  function register(context, {tabID, title, source}) {
    return FTPageAssistance.register(context, {
      navigation: () => ({
        schema_version: 1, root_id: "page", nodes: {
          page: {
            id: "page", kind: "page", label: "自定义补充分析",
            children: ["field:title", "field:source"],
          },
          "field:title": {
            id: "field:title", kind: "field", label: "标题",
            value: title.value, children: [],
          },
          "field:source": {
            id: "field:source", kind: "field", label: "Python 源码",
            value: source.value, children: [],
          },
        },
      }),
      schema: () => ({
        type: "object", required: ["schema_version", "document_kind", "title", "source"],
        properties: {
          schema_version: {const: 1}, document_kind: {const: "custom_analysis_draft"},
          title: {type: "string"}, source: {type: "string"},
        },
        additionalProperties: false,
      }),
      exportDocument: () => ({
        schema_version: 1, document_kind: "custom_analysis_draft",
        title: title.value, source: source.value,
      }),
      validate: document => {
        if (!String(document?.source || "").trim()) throw new Error("辅助分析源码不能为空");
      },
      importDocument: document => {
        title.value = String(document.title || "");
        source.value = String(document.source || "");
        title.dispatchEvent(new Event("input", {bubbles: true}));
        source.dispatchEvent(new Event("input", {bubbles: true}));
      },
    }, {pageKind: "job-custom-analysis", view: () => ({analysis_tab_id: tabID})});
  }

  window.FTCustomAnalysisAssistance = Object.freeze({register});
})();
