import assert from "node:assert/strict";
import test from "node:test";

const saved = new Map<string, string>();
(globalThis as any).localStorage = {
  getItem: (key: string) => saved.get(key) ?? null,
  setItem: (key: string, value: string) => saved.set(key, value),
};
saved.set("tr.language", "en");
(globalThis as any).document = { documentElement: { lang: "" } };

test("shared resources translate nav and jobs keys", async () => {
  const { default: i18n } = await import("./i18n.ts");
  assert.equal(i18n.t("nav.research"), "Research");
  assert.equal(i18n.t("brand.name"), "TradeResearch");
  assert.equal(i18n.t("configuration.strategyFields.signal"), "Signal factor");
  await i18n.changeLanguage("zh");
  assert.equal(i18n.t("nav.research"), "研究");
  assert.equal(i18n.t("brand.name"), "TradeResearch");
  assert.equal(i18n.t("configuration.strategyFields.signal"), "信号因子");
  assert.equal(i18n.t("jobs.task"), "任务");
  assert.equal(i18n.t("missing.key", { defaultValue: "fallback" }), "fallback");
});
