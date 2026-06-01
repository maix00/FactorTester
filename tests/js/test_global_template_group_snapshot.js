/**
 * Regression test for single-factor setting templates:
 * group settings preserve per-combination fee maps and group/LS references.
 */

var assert = require('assert');
var root = require('path').join(__dirname, '../..');

function makeElement(id, value) {
    return {
        id: id,
        value: value || '',
        checked: false,
        textContent: '',
        innerHTML: '',
        style: {},
        classList: { contains: function() { return false; }, remove: function() {} },
        addEventListener: function() {},
        dispatchEvent: function() {},
        querySelector: function() { return null; },
        querySelectorAll: function() { return []; },
        getAttribute: function() { return null; },
        setAttribute: function() {},
    };
}

function htmlEscaper() {
    return {
        _text: '',
        set textContent(v) { this._text = String(v); },
        get innerHTML() {
            return this._text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        },
    };
}

var elements = {};
[
    'global-tpl-list', 'global-tpl-save-status', 'global-tpl-load-status',
    'global-tpl-save-name', 'global-tpl-save-btn', 'global-tpl-summary-row',
    'global-tpl-drawer', 'start_year', 'start_month', 'start_day',
    'start_hour', 'start_minute', 'end_year', 'end_month', 'end_day',
    'end_hour', 'end_minute', 'timezone_input', 'is_trading_day',
    'is_cn_futures_day', 'is_cn_futures_night', 'current_settings',
    'factor_table_body', 'parameter_module', 'ic-freq-table-body',
].forEach(function(id) { elements[id] = makeElement(id); });

elements.start_year.value = '2025';
elements.start_month.value = '01';
elements.start_day.value = '02';
elements.start_hour.value = '09';
elements.start_minute.value = '00';
elements.end_year.value = '2025';
elements.end_month.value = '03';
elements.end_day.value = '04';
elements.end_hour.value = '15';
elements.end_minute.value = '00';
elements.timezone_input.value = 'Asia/Shanghai';

global.window = global;
global.factorFamilyAlias = 'TestFF';
global.MutationObserver = function() { this.observe = function() {}; };
global.Event = function(type) { this.type = type; };
global.document = {
    readyState: 'complete',
    createElement: htmlEscaper,
    getElementById: function(id) { return elements[id] || null; },
    querySelector: function() { return null; },
    querySelectorAll: function() { return []; },
    addEventListener: function() {},
};
var appliedSubmissions = [{
    id: 'tester-old',
    label: '旧测试器',
    product_group: '旧产品组',
    selected_paths: ['Root/Old'],
    paths: ['Root/Old'],
    factor_tester_serial: '#tester-old',
    product_count: 2,
    products: ['rb', 'hc'],
}];
var serverSubmissions = [];
var createdTesterId = null;
var fetchEvents = [];
global._getCurrentSubmissions = function() { return appliedSubmissions; };
global._applySubmissions = function(newSubmissions) { appliedSubmissions = Array.isArray(newSubmissions) ? newSubmissions : []; };
global.fetch = async function(url, options) {
    var urlText = String(url);
    var body = {};
    if (options && options.body) {
        try { body = JSON.parse(options.body); } catch (e) { body = {}; }
    }
    fetchEvents.push({ url: urlText, body: body });
    if (urlText.indexOf('/api/single_factor_setting_templates/') !== -1) {
        return { json: async function() { return { success: true, templates: [] }; } };
    }
    if (urlText.indexOf('/set_time_range') !== -1) {
        return { json: async function() { return { page_uuid: 'p1' }; } };
    }
    if (urlText.indexOf('/clear_all_submissions') !== -1) {
        serverSubmissions = [];
        return { json: async function() { return { success: true, submissions: [] }; } };
    }
    if (urlText.indexOf('/submit_selected_products') !== -1) {
        assert.strictEqual(body.page_uuid, 'p1', 'template apply must restore time/page_uuid before recreating testers');
        createdTesterId = body.id_time;
        serverSubmissions.push({
            id: body.id_time,
            label: '',
            product_group: body.group_name || '',
            selected_paths: body.selected_paths || [],
            factor_tester_serial: '#' + body.id_time,
            product_count: 2,
            products: ['rb', 'hc'],
        });
        return { json: async function() { return { success: true, submissions: serverSubmissions.slice() }; } };
    }
    if (urlText.indexOf('/rename_submission') !== -1) {
        serverSubmissions.forEach(function(s) {
            if (String(s.id) === String(body.id_time)) s.label = body.new_name || '';
        });
        return { json: async function() { return { success: true, submissions: serverSubmissions.slice() }; } };
    }
    if (urlText.indexOf('/api/list_submissions') !== -1) {
        return { json: async function() { return { success: true, submissions: serverSubmissions.slice() }; } };
    }
    return { json: async function() { return { success: true, submissions: [] }; } };
};

global.GroupTest = {
    datamodel: {},
    state: { emit: function() {}, on: function() {}, off: function() {} },
    log: function() {},
    ui: { mountTab: function(name) { this.mounted = name; } },
};

require(root + '/static/js/modules/single_factor_test/group_test/datamodel/groups.js');
require(root + '/static/js/modules/single_factor_test/group_test/datamodel/ls_configs.js');
require(root + '/static/js/modules/single_factor_test/group_test/datamodel/registrations.js');
require(root + '/static/js/modules/single_factor_test/group_test/datamodel/settings_snapshot.js');
var originalConsoleLog = console.log;
console.log = function() {};
require(root + '/static/js/modules/single_factor_test/global_template_module.js');
console.log = originalConsoleLog;

(async function() {
    var groups = GroupTest.datamodel.groups;
    var bgId = groups.add({
        id: 'bg_saved',
        name: 'A1',
        shortAlias: 'A1',
        testerId: 'tester-old',
        factorAlias: 'F',
        groupCount: 3,
        groupIndex: 1,
        feeMode: 'per_product',
        feeMap: { rb: { close_ratio: 0.2 } },
    });
    var dgId = groups.add({
        id: 'dg_saved',
        name: 'D1',
        isDerived: true,
        baseGroupId: bgId,
        productMask: { rb: true },
    });
    var ls = GroupTest.datamodel.ls_configs.add({
        id: 'ls_saved',
        name: 'LS1',
        longGroupId: bgId,
        shortGroupId: dgId,
    });
    GroupTest.datamodel.registrations.register(ls.id, dgId, 'long', 1);
    var dirtyCommitted = false;
    global.GT_CONFIG_REGISTRY = {
        hasDirty: function() { return !dirtyCommitted; },
        commitDirty: function() {
            dirtyCommitted = true;
            GroupTest.datamodel.groups.update(bgId, { rebalanceMode: 'recycle' });
            return true;
        },
    };

    var snap = await window._collectSnapshot();
    assert.strictEqual(dirtyCommitted, true);
    assert(!Object.prototype.hasOwnProperty.call(snap, 'fee_modifications'));
    assert.strictEqual(snap.submissions[0].id, 'tester-old');
    assert.strictEqual(Object.keys(snap.group_settings.baseGroups[0].feeMap.rb).length, 1);
    assert.strictEqual(snap.group_settings.baseGroups[0].feeMap.rb.close_ratio, 0.2);
    assert.strictEqual(snap.group_settings.derivedGraph[0].baseGroupId, 'bg_saved');
    assert.strictEqual(snap.group_settings.lsConfigs[0].longGroupId, 'bg_saved');
    assert.strictEqual(snap.group_settings.baseGroups[0].rebalanceMode, 'recycle');
    var summaryHtml = window._snapshotRegistry.summarizeAll(snap);
    assert(summaryHtml.indexOf('产品类别筛选') !== -1);
    assert(summaryHtml.indexOf('分组测试') !== -1);
    assert(summaryHtml.indexOf('A1') !== -1);
    assert(summaryHtml.indexOf('分品种费率') !== -1);

    groups._reset();
    GroupTest.datamodel.ls_configs._reset();
    GroupTest.datamodel.registrations._reset();
    fetchEvents = [];
    await window._applySnapshot(snap, 'tpl1');

    var restored = GroupTest.datamodel.settings.snapshot();
    assert.strictEqual(restored.baseGroups[0].id, 'bg_saved');
    assert.strictEqual(restored.baseGroups[0].testerId, createdTesterId);
    assert.notStrictEqual(restored.baseGroups[0].testerId, 'tester-old');
    assert.strictEqual(appliedSubmissions.length, 1);
    assert.strictEqual(appliedSubmissions[0].id, createdTesterId);
    assert.strictEqual(Object.keys(restored.baseGroups[0].feeMap.rb).length, 1);
    assert.strictEqual(restored.baseGroups[0].feeMap.rb.close_ratio, 0.2);
    assert.strictEqual(restored.derivedGraph[0].baseGroupId, 'bg_saved');
    assert.strictEqual(restored.lsConfigs[0].id, 'ls_saved');
    assert.strictEqual(restored.lsConfigs[0].shortGroupId, 'dg_saved');
    assert.strictEqual(restored.registrations[0].lsConfigId, 'ls_saved');
    assert.strictEqual(restored.registrations[0].registrations[0].groupId, 'dg_saved');
    var setTimeIndex = fetchEvents.findIndex(function(e) { return e.url.indexOf('/set_time_range') !== -1; });
    var submitIndex = fetchEvents.findIndex(function(e) { return e.url.indexOf('/submit_selected_products') !== -1; });
    assert(setTimeIndex >= 0 && submitIndex >= 0 && setTimeIndex < submitIndex, 'time_data must apply before submissions');
    console.log('global template group snapshot OK');
})().catch(function(err) {
    console.error(err);
    process.exit(1);
});
