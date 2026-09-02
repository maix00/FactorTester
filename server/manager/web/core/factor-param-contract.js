(() => {
  const contract = {
    scalar: "数值常量填写 JSON number；恢复为 ConstExpr，不创建依赖对象。",
    column: "DataColumn/ColumnRef 填注册 alias 字符串，例如 CA、V、TO、OI。",
    library_factor: {
      value: "完整 factor:v2 冻结对象，不能只填 alias/ref 字符串。",
      source_kind: "factor_library",
      persistence: "参数只保存 ref；完整对象平铺进入 factor_dependencies。",
    },
    inline_from_library_family: {
      value: "完整 factor:v2 冻结对象",
      temporary: true, source_kind: "factor_library",
      source_origin: "test_inline",
      persistence: "不登记独立因子；按冻结家族版本恢复。",
    },
    inline_from_source: {
      value: "完整 factor:v2 冻结对象并包含 source_code",
      temporary: true, source_kind: "transient",
      source_origin: "test_inline",
      persistence: "不登记独立因子；源码随外层对象或测试配置冻结。",
    },
    family_composition: {
      editor: "选择可见因子家族或当场新建临时因子家族后，递归填写该家族参数；不要把界面草稿标记当作持久格式。",
      result: "提交前必须解析成完整 factor:v2 冻结对象；临时家族源码只随外层因子或测试配置冻结，不写入因子库。",
      choices: "手填常量/alias、DataColumn、因子库因子、因子家族四路互斥。",
    },
    nesting: "每层 factor_dependencies 按 ref 平铺去重；禁止循环依赖。",
    signal_align: "内层因子的 $F、$Rev 与 SignalAlign 属于其冻结语义；嵌入外层后保留，并按 SignalAlign 规则在信号时间点之间 forward-fill 到外层时间轴。不得删除或改写内层 $F。",
    display: "编辑器和摘要始终显示 alias；ref 与冻结对象仅用于传输、存储和恢复。",
    outer_contexts: {
      factor_library: "外层因子登记进因子库；参数 ref 与平铺依赖图写入该因子配置。",
      test_configuration_inline: "外层因子只写入当前测试配置 temporary_objects；不会登记进因子库。",
    },
  };

  window.FTFactorParamContract = Object.freeze({
    schema: () => structuredClone(contract),
  });
})();
