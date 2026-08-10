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
assert.equal(decay.children[0].children[1].value, "1, 5");
assert.equal(
  decay.children[1].textContent,
  "用于 IC 序列自相关与衰减诊断，不改变入场延迟",
);
decay.children[0].children[1].value = "2, 10, 2";
decay.children[0].children[1].listeners.change();
assert.deepEqual(changed, [2, 10]);
console.log("ok");
