import assert from "node:assert/strict";
import test from "node:test";

const saved = new Map<string, string>();
(globalThis as any).localStorage = {
  getItem: (key: string) => saved.get(key) ?? null,
  setItem: (key: string, value: string) => saved.set(key, value),
};
(globalThis as any).document = { documentElement: { lang: "" } };

test("Intl formatting follows the selected language and explicit time zone", async () => {
  saved.set("tr.language", "en");
  const { default: i18n } = await import("./i18n.ts");
  const { formatDate, formatMoney, formatNumber } = await import("./format.ts");
  assert.equal(formatNumber(1234.5, { maximumFractionDigits: 1 }), "1,234.5");
  assert.match(formatMoney(1234.5, "USD"), /1,234\.50/);
  const date = formatDate("2026-10-25T12:00:00Z", { timeZone: "UTC", dateStyle: "short" });
  assert.match(date, /10\/25\/26/);
  await i18n.changeLanguage("zh");
  assert.match(formatDate("2026-10-25T12:00:00Z", { timeZone: "UTC", dateStyle: "short" }), /2026\/10\/25/);
});


test("Manager Unix seconds and explicit milliseconds show the same instant", async () => {
  const { formatDate } = await import("./format.ts");
  const options = { timeZone: "UTC", dateStyle: "short", timeStyle: "medium" } as const;
  const millis = Date.parse("2026-10-28T16:16:09Z");
  const expected = formatDate(new Date(millis), options);
  assert.equal(formatDate(millis / 1000, options), expected);
  assert.equal(formatDate(millis, options, "milliseconds"), expected);
  assert.equal(formatDate("2026-10-28T16:16:09Z", options), expected);
  assert.equal(formatDate("bad timestamp", options), "—");
});
