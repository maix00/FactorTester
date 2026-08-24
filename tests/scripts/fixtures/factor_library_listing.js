const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

global.window = {};
global.document = {
  createElement(tagName) {
    return {
      tagName: String(tagName || "").toUpperCase(),
      children: [],
      append(...items) { this.children.push(...items); },
      replaceChildren(...items) { this.children = items; },
      addEventListener() {},
      setAttribute() {},
    };
  },
};
window.FTIcons = {node(symbol) { return {symbol}; }};
global.FTIcons = window.FTIcons;
vm.runInThisContext(
  fs.readFileSync("server/manager/web/catalog/factor-model.js", "utf8"),
  {filename: "factor-model.js"},
);
window.FTUI = {
  table(headers, rows) {
    return {shell: {headers, rows}, body: {rows: []}};
  },
  pagedTable(headers, rows, options = {}) {
    const pageSize = options.pageSize || 20;
    const page = options.page || 1;
    const start = (page - 1) * pageSize;
    return {
      shell: {headers, rows: rows.slice(start, start + pageSize)},
      body: {rows: []}, page, pageSize, start,
    };
  },
  empty(title, description) { return {title, description}; },
};
global.FTUI = window.FTUI;
vm.runInThisContext(
  fs.readFileSync("server/manager/web/catalog/factor-list.js", "utf8"),
  {filename: "factor-list.js"},
);

const context = {t: value => value};
const data = {
  principal: "alice",
  groups: [],
  sets: [],
  families: [{
    family_ref: "family:one",
    factor_family_name: "MmRateOfChg",
    factor_family_alias: "ROC",
    chinese_name: "动量变动率",
    description: "使用端点收益率衡量动量的长篇说明",
    categories: ["momentum"],
    owner_alias: "MaxA",
    factor_kind: "public",
    factor_count: 2,
  }, {
    family_ref: "family:two",
    factor_family_name: "PrivateFamily",
    chinese_name: "私有因子",
    owner_alias: "MaxA",
    factor_kind: "custom",
    factor_count: 1,
  }],
  family_scopes: {
    public: {
      families: [{
        family_ref: "family:one",
        factor_family_name: "MmRateOfChg",
        factor_family_alias: "ROC",
        chinese_name: "动量变动率",
        categories: ["momentum"],
        owner_alias: "公共因子库",
        factor_kind: "public",
        factor_count: 2,
      }, {
        family_ref: "family:three",
        factor_family_name: "Volatility",
        factor_family_alias: "volatility",
        chinese_name: "波动率",
        owner_alias: "公共因子库",
        factor_kind: "public",
        factor_count: 1,
      }],
      factors: [],
    },
    mine: {
      families: [{
        family_ref: "family:two",
        factor_family_name: "PrivateFamily",
        chinese_name: "私有因子",
        owner_username: "alice",
        owner_alias: "MaxA",
        factor_kind: "custom",
        factor_count: 1,
      }],
      factors: [{
        factor_ref: "factor:one",
        factor_alias: "MmRateOfChg|P:[CA]|N:20d|$F:1d",
        factor_family_name: "MmRateOfChg",
        factor_family_alias: "ROC",
        chinese_name: "20 日动量变动率",
        description: "使用二十日端点收益率构造的具体因子长篇说明",
        factor_kind: "custom",
        owner_username: "alice",
        owner_alias: "MaxA",
      }],
    },
    subordinates: {
      families: [{
        family_ref: "family:four",
        factor_family_name: "ChildFamily",
        chinese_name: "下级因子",
        categories: ["child-category"],
        owner_username: "child",
        owner_alias: "Child",
        factor_kind: "custom",
        factor_count: 1,
      }, {
        family_ref: "family:five",
        factor_family_name: "OtherFamily",
        owner_username: "other-child",
        owner_alias: "Other Child",
        factor_kind: "custom",
        factor_count: 1,
      }],
      factors: [],
    },
  },
  factors: [{
    factor_ref: "factor:one",
    factor_alias: "MmRateOfChg|P:[CA]|N:20d|$F:1d",
    factor_family_name: "MmRateOfChg",
    factor_family_alias: "ROC",
    chinese_name: "20 日动量变动率",
    description: "使用二十日端点收益率构造的具体因子长篇说明",
    factor_kind: "custom",
    owner_alias: "MaxA",
  }],
};
const mount = {replaceChildren(value) { this.value = value; }};

window.FTFactorList.render(context, data, mount, {
  page: "families", scope: "public", query: "", groupRef: "*",
});
assert.equal(mount.value.className, "factor-family-scope-panel public");
assert.equal(mount.value.children[0].textContent, "公共因子家族");
assert.deepStrictEqual(mount.value.children[1].headers, [
  "原类名", "说明", "分类", "来源", "所有者", "因子数",
]);
assert.strictEqual(mount.value.children[1].rows.length, 2);
assert.strictEqual(mount.value.children[1].rows[0][0], "MmRateOfChg");
assert.strictEqual(mount.value.children[1].rows[0][1], "动量变动率");

window.FTFactorList.render(context, data, mount, {
  page: "families", scope: "mine", query: "private", groupRef: "*",
});
assert.equal(mount.value.children[0].textContent, "我的因子家族");
assert.equal(mount.value.children[1].headers[0], "原类名");
assert.strictEqual(mount.value.children[1].rows[0][0], "PrivateFamily");

window.FTFactorList.render(context, data, mount, {
  page: "families", scope: "subordinates", query: "", groupRef: "*",
});
assert.equal(mount.value.children[0].textContent, "下级用户因子家族");
assert.strictEqual(mount.value.children[1].rows.length, 2);
assert.strictEqual(mount.value.children[1].rows[0][0], "ChildFamily");

window.FTFactorList.render(context, data, mount, {
  page: "families", scope: "subordinates", query: "other-child", groupRef: "*",
});
assert.strictEqual(mount.value.children[1].rows.length, 1);
assert.strictEqual(mount.value.children[1].rows[0][0], "OtherFamily");

const manyFamilies = Array.from({length: 21}, (_, index) => ({
  family_ref: `family:page-${index}`,
  factor_family_name: `PagedFamily${index}`,
  factor_kind: "public",
}));
const pagedData = {
  ...data,
  family_scopes: {
    ...data.family_scopes,
    public: {families: manyFamilies, factors: []},
  },
};
window.FTFactorList.render(context, pagedData, mount, {
  page: "families", scope: "public", query: "", groupRefs: ["*"],
  tablePage: 1,
});
assert.strictEqual(mount.value.children[1].rows.length, 20);
window.FTFactorList.render(context, pagedData, mount, {
  page: "families", scope: "public", query: "", groupRefs: ["*"],
  tablePage: 2,
});
assert.strictEqual(mount.value.children[1].rows.length, 1);
assert.strictEqual(mount.value.children[1].rows[0][0], "PagedFamily20");

window.FTFactorList.render(context, {...data, visitor: true}, mount, {
  page: "families", scope: "public", query: "", groupRef: "*",
});
assert.equal(mount.value.children[0].textContent, "公共因子家族");
assert.equal(mount.value.children[1].rows.length, 2);

const deleted = [];
window.FTUI.actionButton = (label, handler) => ({
  textContent: label,
  children: [],
  listeners: {click: handler},
  classList: {add() {}},
  replaceChildren(...items) { this.children = items; },
  setAttribute() {},
});
window.FTFactorList.render(context, data, mount, {
  page: "families", scope: "mine", query: "", groupRefs: ["*"],
  canModify: true, onDelete: item => deleted.push(item.family_ref),
});
assert.equal(mount.value.children[1].headers.at(-1), "操作");
const familyAction = mount.value.children[1].rows[0].at(-1);
assert.equal(familyAction.children[0].symbol, "trash");
familyAction.listeners.click({stopPropagation() {}});
assert.deepStrictEqual(deleted, ["family:two"]);

window.FTFactorList.render(context, data, mount, {
  page: "factors", scope: "mine", query: "", groupRef: "*",
});
assert.deepStrictEqual(mount.value.headers, [
  "因子", "原类名", "说明", "来源", "所有者", "产品组",
]);
assert.strictEqual(mount.value.rows[0][1], "MmRateOfChg");
assert.strictEqual(mount.value.rows[0][2], "20 日动量变动率");
console.log("ok");
