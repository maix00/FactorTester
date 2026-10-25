import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

const saved = new Map<string, string>();
(globalThis as any).localStorage = {
  getItem: (key: string) => saved.get(key) ?? null,
  setItem: (key: string, value: string) => saved.set(key, value),
};
(globalThis as any).document = { documentElement: { lang: "" } };

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return files(path);
    return /\.(tsx?|test\.ts)$/.test(name) && !name.endsWith(".test.ts") ? [path] : [];
  });
}

test("literal translation keys exist in both languages", async () => {
  const { resources } = await import("./i18n.ts");
  const keys = new Set<string>();
  for (const path of files(join(process.cwd(), "src"))) {
    const text = readFileSync(path, "utf8");
    for (const match of text.matchAll(/\bt\("([a-zA-Z0-9_.]+)"/g)) keys.add(match[1]);
  }
  const has = (value: object, key: string): boolean => {
    const found = key.split(".").reduce<unknown>((current, part) => (
      current !== null && typeof current === "object"
        ? (current as Record<string, unknown>)[part]
        : undefined
    ), value);
    return typeof found === "string";
  };
  for (const language of ["zh", "en"] as const) {
    for (const key of keys) assert.ok(has(resources[language].common, key), `${language}:${key}`);
  }
});
