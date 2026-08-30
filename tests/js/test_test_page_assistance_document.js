const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = globalThis;
global.FTTestConfigurationCompiler = {
  authoringSettings: (_manifest, values) => ({...values}),
  authoringMountedTabs: (_manifest, _settings, saved) => [...(saved || [])],
  authoringItemMountedTabs: (manifest, item, saved) => {
    const defaults = manifest.strategy_editor?.inner_default_tabs || [];
    const manual = manifest.strategy_editor?.inner_manual_tabs || [];
    const mounted = new Set(defaults.map(tab => tab.key));
    for (const key of saved || []) mounted.add(key);
    for (const tab of manual) {
      if (item[tab.item_field] !== tab.item_default) mounted.add(tab.key);
    }
    return [...defaults, ...manual].map(tab => tab.key).filter(key => mounted.has(key));
  },
  executionSettings: (_manifest, values) => ({...values}),
  derivedSettingsKeys: () => ["execution", "local_settings", "settings"],
  authoringConfiguration: (configuration, kind) => {
    const result = structuredClone(configuration);
    delete result.analyses[kind].local_settings;
    delete result.analyses[kind].settings;
    return result;
  },
  executableConfiguration: (configuration, kind) => {
    const result = structuredClone(configuration);
    result.analyses[kind].execution = {
      settings: {...(result.ui?.[kind]?.settings || {})},
    };
    delete result.analyses[kind].settings;
    return result;
  },
};
global.FTTestConfiguration = {
  configurationPayload: state => ({
    schema_version: 3,
    shared: state.workspace.configuration.payload.shared,
    run_fields: {output_requests: [...state.outputRequests]},
    analyses: {
      [state.kind]: {
        ...state.analysis,
        local_settings: {factor_mode: state.values.factor_mode},
      },
    },
    ui: {
      [state.kind]: {
        settings: {...state.values},
        mounted_tabs: [...state.settingsMountedTabs],
      },
    },
  }),
};
global.FTTestProducts = {
  groupID: value => value?.group_ref || value?.product_path_selection_id || "",
  projection: value => ({
    product_path_selection_id: value.group_ref,
    product_group_template_id: value.group_ref,
    label: value.name,
    selected_paths: [...(value.paths || [])],
    paths: [...(value.paths || [])],
  }),
};
let registeredAdapter = null;
global.FTPageAssistance = {
  register: (_context, adapter) => { registeredAdapter = adapter; return adapter; },
};
let restored = 0;
global.FTTestState = {
  applyWorkspaceConfiguration: state => {
    state.analysis = state.workspace.configuration.payload.analyses[state.kind];
    restored += 1;
  },
  seedSavedCatalogs: () => { restored += 1; },
  defaultRunValues: manifest => Object.fromEntries(
    (manifest.run_fields || []).filter(field => field.placement !== "outputs")
      .map(field => [field.key, structuredClone(field.default)]),
  ),
  registeredRunValues: state => Object.fromEntries(
    (state.manifest.run_fields || []).map(field => [field.key,
      field.placement === "outputs" ? state.outputRequests : state.runValues[field.key]]),
  ),
  applyRegisteredRunValues: (state, values) => {
    state.runValues = {task_name: values.task_name || ""};
    state.outputRequests = [...(values.output_requests || [])];
    state.outputRequestsExplicit = Array.isArray(values.output_requests);
  },
};
vm.runInThisContext(
  fs.readFileSync("server/manager/web/workbench/test-page-assistance.js", "utf8"),
  {filename: "test-page-assistance.js"},
);

for (const kind of ["backtest", "ic"]) {
  const state = {
    kind,
    workspace: {configuration: {payload: {schema_version: 3, shared: {factors: []}}}},
    manifest: {
      research_configuration_schema_version: 3,
      defaults: {factor_mode: {tab_key: "factor-execution"}},
      modules: [
        {key: "factor-execution", label: "因子执行"},
        {key: "product-selection", label: "产品组"},
      ],
      field_contracts: {settings: {
        factor_mode: {module: "factor-execution", label: "因子模式"},
        product_path_selection: {module: "product-selection", label: "产品组"},
      }},
      analysis_graph: {authoring_contract: {configuration_group_schema: {
        type: "object",
        required: [
          "config_group_id", "batch_id", "name", "factor_ref",
          "product_scope_ref", "entry_delay_bars", "horizon", "methods",
          "return_price_basis",
        ],
        properties: {
          config_group_id: {type: "string", title: "配置组 ID"},
          entry_delay_bars: {type: "integer", minimum: 0, title: "入场延迟"},
        },
        additionalProperties: false,
      }}},
      configuration_item_contract: {schema_version: 1,
        item_kind: kind === "ic" ? "configuration-group" : "strategy",
        collection_key: kind === "ic" ? "configuration_groups" : "groups",
        min_items: 1, max_items: kind === "ic" ? 1 : undefined,
        create_template: kind === "ic" ? {
          config_group_id: "<unique-configuration-group-id>",
          factor_ref: "<factor-ref>",
        } : {
          id: "<unique-strategy-id>", factor_candidate_refs: ["<factor-ref>"],
        },
        field_sources: kind === "ic" ? {
          factor_ref: "field:factor_candidates",
          product_scope_ref: "field:product_path_selection",
        } : {
          factor_candidate_refs: "field:factor_candidates",
          product_path_selection: "field:product_path_selection",
        },
        schema: kind === "ic" ? {
          type: "object",
          required: [
            "config_group_id", "batch_id", "name", "factor_ref",
            "product_scope_ref", "entry_delay_bars", "horizon", "methods",
            "return_price_basis",
          ],
          properties: {
            config_group_id: {type: "string", title: "配置组 ID"},
            entry_delay_bars: {type: "integer", minimum: 0, title: "入场延迟"},
          },
        } : {
        type: "object",
        required: [
          "id", "factor_candidate_refs", "product_path_selection",
          "splitCount", "groupIndex",
        ],
        properties: {
          id: {type: "string", title: "策略 ID"},
          factor_candidate_refs: {type: "array", title: "因子候选"},
          product_path_selection: {type: "object", title: "产品组"},
          splitCount: {type: "integer", title: "分组数"},
          groupIndex: {type: "integer", title: "分组序号"},
        },
      }},
      strategy_editor: {
        inner_default_tabs: [
          {key: kind === "ic" ? "__configuration__" : "__strategy__"},
          {key: "factor"}, {key: "product_path_selection"},
        ],
        inner_manual_tabs: kind === "ic" ? [
          {key: "delay", item_field: "entry_delay_bars", item_default: 0},
        ] : [],
      },
      run_fields: [
        {key: "task_name", label: "任务名称", placement: "run_identity", default: ""},
        {key: "output_requests", label: "结果与生成物", placement: "outputs",
          template_policy: "include", default: []},
      ],
    },
    values: {factor_mode: "native"},
    analysis: kind === "backtest"
      ? {groups: [{
        id: "strategy-1", factor_candidate_refs: [`factor:v2:${"a".repeat(43)}`],
        product_path_selection_id: "product-group:1",
        splitCount: 5, groupIndex: 1,
      }]}
      : {configuration_groups: [{
        config_group_id: "ic-1", batch_id: "batch-1", name: "IC 配置 1",
        factor_ref: `factor:v2:${"a".repeat(43)}`,
        product_scope_ref: "product-group:1", entry_delay_bars: 0,
        horizon: {sampling: "scale_aware"}, methods: ["rank"],
        return_price_basis: "next_open_to_open_adjusted",
      }]},
    settingsMountedTabs: ["factor-execution"],
    outputRequests: ["equity_curve"],
    runValues: {task_name: `${kind} task`},
    groups: [{
      group_ref: "product-group:1", name: "中国期货日盘",
      paths: ["Product/Futures/CNFutures/_products/A.DCE"],
    }],
    selectedICConfigurationGroupIDs: kind === "ic" ? ["ic-1"] : [],
  };
  const document = FTTestPageAssistance.documentFor(state);
  assert.equal(document.document_kind, "research_configuration");
  assert.deepEqual(document.analyses, [kind]);
  assert.equal(document.configuration.schema_version, 3);
  assert.equal(document.configuration.analyses[kind].local_settings, undefined);
  assert.equal(document.configuration.ui[kind].settings.factor_mode, "native");
  assert.deepEqual(document.configuration.run_fields.output_requests, ["equity_curve"]);
  assert.equal(document.configuration.ui[kind].output_requests, undefined);
  assert.equal(document.run_fields.task_name, `${kind} task`);
  assert.deepEqual(document.run_fields.output_requests, ["equity_curve"]);
  assert.equal(
    FTTestPageAssistance.schemaFor(state)["x-run-spec-shape"],
    "RunRequest(configuration + registered run_fields)",
  );
  assert.equal(
    FTTestPageAssistance.schemaFor(state)["x-canonical-settings-path"],
    `configuration.ui.${kind}.settings`,
  );
  assert.equal(
    FTTestPageAssistance.schemaFor(state).properties.configuration
      .properties.schema_version.const,
    3,
    "page assistance uses the backend-registered ResearchConfiguration version",
  );
  const navigation = FTTestPageAssistance.navigationFor(state);
  const collection = navigation.nodes.configurations;
  assert.equal(
    collection.collection_path,
    `configuration.analyses.${kind}.${kind === "ic" ? "configuration_groups" : "groups"}`,
  );
  assert.deepEqual(
    collection.required_fields,
    state.manifest.configuration_item_contract.schema.required,
  );
  assert.deepEqual(
    collection.create_template,
    state.manifest.configuration_item_contract.create_template,
    "the Agent receives the backend-registered canonical item skeleton",
  );
  assert.deepEqual(
    collection.field_sources,
    state.manifest.configuration_item_contract.field_sources,
  );
  if (kind === "ic") {
    const groupSchema = FTTestPageAssistance.schemaFor(state).properties
      .configuration.properties.analyses.properties.ic.properties
      .configuration_groups;
    assert.equal(groupSchema.maxItems, 1);
    assert(groupSchema.items.required.includes("entry_delay_bars"));
    const groupNode = navigation.nodes["configuration:ic-1"];
    assert(groupNode.children.includes("configuration:ic-1:field:entry_delay_bars"));
    assert.equal(
      navigation.nodes["configuration:ic-1:field:entry_delay_bars"].label,
      "入场延迟",
    );
  }
  if (kind === "backtest") {
    assert.deepEqual(document.configuration.analyses.backtest.groups[0]
      .product_path_selection, {
      product_path_selection_id: "product-group:1",
      product_group_template_id: "product-group:1",
      label: "中国期货日盘",
      selected_paths: ["Product/Futures/CNFutures/_products/A.DCE"],
      paths: ["Product/Futures/CNFutures/_products/A.DCE"],
    });
    assert.equal(document.configuration.analyses.backtest.groups[0]
      .product_path_selection_id, undefined);
    assert.equal(document.configuration.analyses.backtest.product_selections[
      "product-group:1"
    ].label, "中国期货日盘");
  }
  assert.equal(navigation.nodes["tab:factor-execution"].mounted, true);
  assert.equal(navigation.nodes["tab:product-selection"].mounted, false);
  assert.deepEqual(
    navigation.nodes["tab:product-selection"].children,
    ["field:product_path_selection"],
    "unmounted tabs expose backend-registered fields without loading UI candidates",
  );
}

const canonicalState = {
  kind: "ic",
  manifest: {defaults: {
    start_date: {}, end_date: {}, start_time: {}, end_time: {},
  }, configuration_item_contract: {collection_key: "configuration_groups"},
  strategy_editor: {
    inner_default_tabs: [
      {key: "__configuration__"}, {key: "factor"}, {key: "product_path_selection"},
    ],
    inner_manual_tabs: [
      {key: "delay", item_field: "entry_delay_bars", item_default: 0},
    ],
  }},
  values: {
    start_date: "", end_date: "", start_time: "00:00", end_time: "23:59",
  },
};
const canonical = FTTestPageAssistance.canonicalDocument(canonicalState, {
  configuration: {
    analyses: {ic: {configuration_groups: [
      {config_group_id: "ic-1", entry_delay_bars: 2},
      {config_group_id: "ic-2", entry_delay_bars: 0},
    ]}},
    ui: {ic: {settings: {
      start_date: "2024-01-01", end_date: "2025-01-31",
      start_time: "09:00", end_time: "15:00",
    }}},
  },
});
assert.deepEqual(canonical.configuration.ui.ic.settings, {
  start_date: "2024-01-01", end_date: "2025-01-31",
  start_time: "09:00", end_time: "15:00",
});
assert.deepEqual(
  canonical.configuration.analyses.ic.execution.settings,
  canonical.configuration.ui.ic.settings,
  "the applied page state and executable RunSpec use one canonical value set",
);
assert.deepEqual(
  canonical.configuration.analyses.ic.configuration_groups[0].editor_mounted_tabs,
  ["__configuration__", "factor", "product_path_selection", "delay"],
  "a non-default item field mounts its registered inner tab",
);
assert.deepEqual(
  canonical.configuration.analyses.ic.configuration_groups[1].editor_mounted_tabs,
  ["__configuration__", "factor", "product_path_selection"],
  "an untouched default does not mount an optional inner tab",
);

const importState = {
  kind: "backtest", workspace: null,
  manifest: {research_configuration_schema_version: 3}, values: {}, analysis: {},
  settingsMountedTabs: [], outputRequests: [], selectedICConfigurationGroupIDs: [],
  lazy: Object.fromEntries(["factors", "products", "categories", "templates", "outputs"]
    .map(key => [key, {status: "ready", error: "stale", promise: Promise.resolve()}])),
  productReferenceHydration: {status: "ready", error: "", promise: null},
  settingsTabLoads: {product_path_selection: {status: "ready"}},
  settingsLoadedTabs: new Set(["product_path_selection"]),
};
const configurationRuntime = global.FTTestConfiguration;
delete global.FTTestConfiguration;
let loadedGroup = "";
global.FTTestLazyCode = {
  loadGroup: group => {
    loadedGroup = group;
    global.FTTestConfiguration = configurationRuntime;
    return Promise.resolve();
  },
};
FTTestPageAssistance.register({}, importState, () => { restored += 1; });
assert.throws(() => registeredAdapter.validate({
  document_kind: "research_configuration",
  configuration: {
    schema_version: 3,
    analyses: {backtest: {groups: [{}], local_settings: {start_date: "2024-01-01"}}},
  },
  run_fields: {},
}), /local_settings.*只读运行配置/);
assert.equal(
  global.FTTestConfiguration, undefined,
  "registering the page must not eagerly require the deferred configuration runtime",
);
registeredAdapter.prepare();
assert.equal(loadedGroup, "workbench-run-submit");
assert.equal(global.FTTestConfiguration, configurationRuntime);
registeredAdapter.importDocument({
  document_kind: "research_configuration",
  configuration: {schema_version: 3, shared: {}, analyses: {backtest: {groups: []}}, ui: {}},
  run_fields: {},
});
assert.equal(restored, 2, "document state is restored before the deferred page rebuild");
for (const record of Object.values(importState.lazy)) {
  assert.deepEqual(record, {status: "idle", error: "", promise: null});
}
assert.equal(importState.productReferenceHydration.status, "idle");
assert.deepEqual(Object.keys(importState.settingsTabLoads), []);
assert.equal(importState.settingsLoadedTabs.size, 0);
registeredAdapter.afterApply();
assert.equal(restored, 3, "the existing workspace restore helpers rebuild the page");
assert.deepEqual(importState.analysis, {groups: [], execution: {settings: {}}});

console.log("PASS: test assistance edits the same configuration shape frozen by RunSpec");
