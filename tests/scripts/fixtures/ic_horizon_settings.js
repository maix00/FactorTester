const assert = require("node:assert/strict");
const fs = require("node:fs");

global.window = globalThis;
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
console.log("ok");
