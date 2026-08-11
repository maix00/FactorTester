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

(async () => {
  await window.FTTestSourceUpload.importDependency(context, state, {
    name: "dynamic-hold.yaml",
    text: async () => "target_leverage: 0.4\n",
  });
  await window.FTTestSourceUpload.importDependency(context, state, {
    name: "risk_gate.py",
    text: async () => "def allow(context):\n    return True\n",
  });

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
  ]);

  await assert.rejects(
    () => window.FTTestSourceUpload.importDependency(context, state, {
      name: "native.dylib", text: async () => "not executable",
    }),
    /受支持的文本文件/,
  );
  console.log("ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
