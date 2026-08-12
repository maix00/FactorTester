const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

global.window = {};
global.structuredClone = value => JSON.parse(JSON.stringify(value));

const [stateModule, uploadModule] = process.argv.slice(2);
vm.runInThisContext(fs.readFileSync(stateModule, "utf8"), {
  filename: stateModule,
});
global.FTTestInputState = window.FTTestInputState;
vm.runInThisContext(fs.readFileSync(uploadModule, "utf8"), {
  filename: uploadModule,
});

const state = {};
const context = {t: value => value};
const dependencyDescriptor = {
  extensions: [".csv", ".py", ".txt", ".yaml"],
  analyses: ["backtest"],
  default_purpose: "strategy_configuration",
  purpose_by_extension: {".py": "strategy_dependency"},
  content_types: {".csv": "text/csv", ".py": "text/x-python", ".yaml": "application/yaml"},
  purposes: [
    {value: "strategy_configuration", label: "策略配置", path_prefix: "strategy-configs"},
    {value: "strategy_dependency", label: "策略依赖", path_prefix: "strategy-configs"},
    {value: "data_mapping", label: "数据映射", path_prefix: "data-mappings"},
  ],
};

(async () => {
  await window.FTTestSourceUpload.importDependency(context, state, {
    name: "dynamic-hold.yaml",
    text: async () => "target_leverage: 0.4\n",
  }, "", dependencyDescriptor);
  await window.FTTestSourceUpload.importDependency(context, state, {
    name: "risk_gate.py",
    text: async () => "def allow(context):\n    return True\n",
  }, "", dependencyDescriptor);
  await window.FTTestSourceUpload.importDependency(context, state, {
    name: "exchange-symbols.csv",
    text: async () => "source,target\nA,B\n",
  }, "data_mapping", dependencyDescriptor);

  const dependencies = window.FTTestInputState.requestBody(
    state,
  ).run_input_dependencies;
  assert.deepEqual(dependencies.map(item => ({
    path: item.path,
    purpose: item.purpose,
    analyses: item.analyses,
  })), [
    {
      path: "strategy-configs/dynamic-hold.yaml",
      purpose: "strategy_configuration",
      analyses: ["backtest"],
    },
    {
      path: "strategy-configs/risk_gate.py",
      purpose: "strategy_dependency",
      analyses: ["backtest"],
    },
    {
      path: "data-mappings/exchange-symbols.csv",
      purpose: "data_mapping",
      analyses: ["backtest"],
    },
  ]);

  await assert.rejects(
    () => window.FTTestSourceUpload.importDependency(context, state, {
      name: "unknown.txt", text: async () => "value",
    }, "executable_plugin", dependencyDescriptor),
    /用途无效/,
  );

  await assert.rejects(
    () => window.FTTestSourceUpload.importDependency(context, state, {
      name: "native.dylib", text: async () => "not executable",
    }, "", dependencyDescriptor),
    /受支持的文本文件/,
  );
  console.log("ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
