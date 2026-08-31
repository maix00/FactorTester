const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

global.window = {};
global.URLSearchParams = URLSearchParams;
global.FTTestProducts = {
  groupID: value => value?.id || '',
  groupLabel: value => value?.label || '',
};

const read = relative => fs.readFileSync(path.resolve(__dirname, `../../${relative}`), 'utf8');
vm.runInThisContext(read('server/manager/web/workbench/run-batch/model.js'));

const groups = [
  {config_group_id: 'ic-1', name: '第一组'},
  {config_group_id: 'ic-2', name: '第二组'},
];
const batchState = {
  kind: 'ic',
  analysis: {configuration_groups: groups},
  selectedICConfigurationGroupIDs: [],
};
assert.deepEqual(
  window.FTTestRunBatchModel.taskGroups(batchState),
  groups,
  'RunSpec preview includes every registered IC group without editor selection',
);

const factor = {
  ref: 'factor:v2:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
  alias: 'Example',
  identity: {family_alias: 'Example', self_formula_fingerprint: 'formula'},
};
const secondFactor = {
  ref: 'factor:v2:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
  alias: 'Second',
  identity: {family_alias: 'Second', self_formula_fingerprint: 'formula-2'},
};
global.FTTestFactors = {
  selectedFactor: state => state.factors[0],
  selectedFamily: () => ({alias: 'Example'}),
};
window.FTFactorModel = {frozenFactorIdentity: value => ({record: value})};
window.FTICConfigurationGroupModel = {
  selected: current => [current.analysis.configuration_groups[0]],
};

vm.runInThisContext(read('server/manager/web/workbench/test-configuration.js'));

const factorScopeState = {
  kind: 'ic',
  analysis: {configuration_groups: [
    {factor_ref: factor.ref}, {factor_ref: secondFactor.ref},
  ]},
  factors: [factor, secondFactor],
  savedFactors: [],
  values: {factor_candidates: [factor, secondFactor]},
};
assert.deepEqual(
  window.FTTestConfiguration.executionFactors(factorScopeState),
  [factor, secondFactor],
  'IC execution freezes factors from every registered group, not editor selection',
);

const urls = [];
const state = {
  kind: 'ic',
  workspace: {},
  analysis: {configuration_groups: [{factor_ref: factor.ref}]},
  factors: [factor],
  savedFactors: [],
  values: {factor_candidates: [factor]},
};
const context = {
  t: value => value,
  api: async (url, init) => {
    urls.push({url, init});
    return {workspace: {
      workspace_id: 'workspace-1',
      configuration: {configuration_id: 'configuration-1', revision: 0},
    }};
  },
};

(async () => {
  const workspace = await window.FTTestConfiguration.ensureWorkspace(context, state);
  assert.equal(workspace.workspace_id, 'workspace-1');
  assert.deepEqual(urls.map(value => value.url), ['/api/test-authoring/workspaces']);
  console.log('PASS: IC preview uses registered groups and repairs partial workspace state');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
