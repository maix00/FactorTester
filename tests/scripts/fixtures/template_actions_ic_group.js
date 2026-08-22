const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
global.window = {};
global.prompt = () => "template";
global.FTTestLazyCode = {loadGroup: async () => {}};
const icGroup = {config_group_id: "icg-one", product_scope_ref: "product-group:day"};
global.FTICConfigurationGroupModel = {selected: () => [icGroup]};
global.FTTestProducts = {selectedGroups: () => [{id: "wrong-product"}]};
window.FTICConfigurationGroupModel = global.FTICConfigurationGroupModel;
window.FTTestProducts = global.FTTestProducts;
let savedGroup;
global.FTTestConfiguration = {save: async (_context, _state, group) => { savedGroup = group; }};
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {filename: process.argv[2]});
const state = {
  kind: "ic", templates: [], selectedICConfigurationGroupIDs: ["icg-one"],
  workspace: {workspace_id: "ws", configuration: {revision: 1}},
};
const context = {t: x => x, api: async () => ({template: {configuration_id: "t"}})};
(async () => {
  await window.FTTestTemplateActions.create(context, state).save();
  assert.equal(savedGroup, icGroup, "IC templates must save the selected configuration group");
  global.FTICConfigurationGroupModel.selected = () => [icGroup, {...icGroup, config_group_id: "icg-two"}];
  await assert.rejects(
    window.FTTestTemplateActions.create(context, state).save(),
    /只能选择一个配置组|selected configuration group/,
    "Slice 1 must reject a second selected IC configuration group",
  );
  console.log("ok");
})().catch(error => { console.error(error); process.exitCode = 1; });
