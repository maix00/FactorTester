const assert = require("node:assert/strict");
const fs = require("node:fs");

global.window = globalThis;
class Element {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.listeners = {};
    this.textContent = "";
    this.value = "";
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
}
global.document = {createElement: tagName => new Element(tagName)};
eval(fs.readFileSync(process.argv[2], "utf8"));

const settings = FTICHorizonSettings;
assert.deepEqual(settings.normalizeHorizon({sampling: "scale_aware"}), {
  sampling: "scale_aware",
});
assert.deepEqual(settings.normalizeHorizon({
  sampling: "explicit", bases: ["signal", "1m", "signal"],
  multipliers: [1, "5", 0, 5],
}), {
  sampling: "explicit", bases: ["signal", "1m"], multipliers: [1, 5],
});
assert.deepEqual(settings.normalizeDelays("0, 1，2; 1 -1 invalid"), [0, 1, 2]);
assert.deepEqual(settings.normalizeDelays([]), [0]);
assert.deepEqual(settings.normalizeDecayLags("1, 2，5; 2 0 -1 invalid"), [1, 2, 5]);
assert.deepEqual(settings.normalizeDecayLags(5), [5]);
assert.deepEqual(settings.normalizeDecayLags([]), [5]);

const values = {
  forward_return_horizons: {sampling: "auto"},
  ic_lags: "0, 2, 2",
  ic_decay_lags: 5,
};
settings.normalizeSettingValues({defaults: {
  forward_return_horizons: {control_template: "ic_horizon_grid"},
  ic_lags: {control_template: "ic_delay_grid"},
  ic_decay_lags: {control_template: "ic_decay_grid"},
}}, values);
assert.deepEqual(values, {
  forward_return_horizons: {sampling: "scale_aware"},
  ic_lags: [0, 2],
  ic_decay_lags: [5],
});

let changed;
const decay = settings.renderDecayLags({
  value: [1, 5], context: {t: value => value}, disabled: false,
  onChange: value => { changed = value; },
});
assert.deepEqual(
  decay.children[0].children[1].children.map(item => item.children[0].textContent),
  ["1", "5"],
);
assert.equal(
  decay.children[1].textContent,
  "按每 N 个 IC 观测重采样并比较均值、波动、IR 与 t 统计；不改变入场延迟",
);
const addRow = decay.children[0].children[2];
addRow.children[0].value = "2, 10, 2";
addRow.children[1].listeners.click();
assert.deepEqual(changed, [1, 5, 2, 10]);
decay.children[0].children[1].children[0].children[1].listeners.click();
assert.deepEqual(changed, [5, 2, 10]);
console.log("ok");
