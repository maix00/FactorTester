import type { JSONObject } from "./draft.ts";
import { parseDraft, readPath, writePath } from "./draft.ts";

export interface StrategyField { key: string; label: string; type: string; required?: boolean; default?: unknown; minimum?: number; maximum?: number; maximum_from?: string; values?: string[] }
export interface StrategyChoice {
  strategy_ref: string; name: string; library_scope?: string; template_ref?: string; revision_ref?: string;
  current_revision_ref?: string; current_revision?: { revision_ref: string; source_sha256?: string; requirements?: JSONObject };
  configuration_schema?: { fields: StrategyField[] };
}
export const TEMPLATE_PATH = ["analyses", "backtest", "factor_strategy_bindings"];
export const LIBRARY_PATH = ["analyses", "backtest", "strategy_bindings"];

export function strategyDefaults(choice: StrategyChoice): JSONObject {
  return Object.fromEntries((choice.configuration_schema?.fields ?? [])
    .filter((field) => field.default !== undefined).map((field) => [field.key, structuredClone(field.default)]));
}

export function strategySchema(choice: StrategyChoice, values: JSONObject): JSONObject {
  const fields = choice.configuration_schema?.fields ?? [];
  return { type: "object", required: fields.filter((field) => field.required).map((field) => field.key),
    properties: Object.fromEntries(fields.map((field) => {
      const schema: JSONObject = { title: field.label, type: ["integer", "number", "boolean"].includes(field.type) ? field.type : "string" };
      if (schema.type === "string" && field.required) schema.minLength = 1;
      if (field.values) schema.enum = field.values;
      if (field.minimum !== undefined) schema.minimum = field.minimum;
      if (field.maximum !== undefined) schema.maximum = field.maximum;
      if (field.maximum_from && typeof values[field.maximum_from] === "number") schema.maximum = values[field.maximum_from];
      return [field.key, schema];
    })), additionalProperties: false };
}

/** Only references returned by the server enter bindings. No browser identity generation. */
export function appendStrategy(text: string, choice: StrategyChoice, values: JSONObject, id: string, factors: JSONObject[]): string {
  const parsed = parseDraft(text);
  if (!parsed.value) throw new Error("Invalid JSON");
  const isTemplate = !!choice.template_ref;
  const path = isTemplate ? TEMPLATE_PATH : LIBRARY_PATH;
  const current = readPath(parsed.value, path) ?? [];
  if (!Array.isArray(current)) throw new Error("Invalid strategy bindings");
  const other = readPath(parsed.value, isTemplate ? LIBRARY_PATH : TEMPLATE_PATH) ?? [];
  if (!Array.isArray(other)) throw new Error("Invalid strategy bindings");
  if ([...current, ...other].some((item) => item.strategy_id === id || item.target_strategy_id === id)) throw new Error("Duplicate strategy ID");
  const revision = choice.current_revision;
  let binding: JSONObject;
  if (isTemplate) {
    binding = { binding_id: `tr-strategy-binding:${id}`, strategy_id: id, template_ref: choice.template_ref,
      revision_ref: choice.revision_ref, ...templateInputs(choice, values) };
  } else {
    const revisionRef = revision?.revision_ref || choice.current_revision_ref;
    if (!revisionRef) throw new Error("Missing strategy revision");
    binding = { binding_id: `tr-strategy-binding:${id}`, target_strategy_id: id,
      source: { kind: "library", strategy_ref: choice.strategy_ref, revision_ref: revisionRef,
        ...(revision?.source_sha256 ? { source_sha256: revision.source_sha256 } : {}) } };
  }
  let next = writePath(text, path, [...current, binding]);
  if (factors.length) next = attachFrozenFactors(next, factors);
  // Run preparation compiles templates through the canonical strategy binding path.
  if (isTemplate && readPath(parsed.value, LIBRARY_PATH) === undefined) next = writePath(next, LIBRARY_PATH, []);
  return next;
}

export interface StrategyBinding { binding: JSONObject; path: string[]; index: number }
export function configurationStrategies(text: string): StrategyBinding[] {
  const parsed = parseDraft(text).value;
  return [TEMPLATE_PATH, LIBRARY_PATH].flatMap((path) => {
    const values = readPath(parsed, path);
    return Array.isArray(values) ? values.flatMap((binding, index) => binding && typeof binding === "object" ? [{ binding, path, index }] : []) : [];
  });
}
export function patchStrategy(text: string, bindingId: string, patch: JSONObject): string {
  const found = configurationStrategies(text).find(({ binding }) => binding.binding_id === bindingId);
  if (!found) return text;
  const values = readPath(parseDraft(text).value, found.path) as JSONObject[];
  return writePath(text, found.path, values.map((item) => item.binding_id === bindingId ? { ...item, ...patch, binding_id: bindingId } : item));
}
export function attachFrozenFactors(text: string, factors: JSONObject[]): string {
  const values = readPath(parseDraft(text).value, ["shared", "factors"]) ?? [];
  if (!Array.isArray(values)) throw new Error("Invalid frozen factors");
  const merged = new Map(values.map((item: JSONObject) => [String(item.ref), item]));
  for (const factor of factors) {
    if (factor.schema_version !== 2 || typeof factor.ref !== "string" || !factor.identity) throw new Error("Missing frozen factor identity");
    if (!merged.has(factor.ref)) merged.set(factor.ref, factor);
  }
  return writePath(text, ["shared", "factors"], [...merged.values()]);
}

export function templateInputs(choice: StrategyChoice, values: JSONObject): JSONObject {
  const fields = choice.configuration_schema?.fields ?? [];
  return {
    factor_bindings: Object.fromEntries(fields.filter((field) => field.type === "factor_ref").map((field) => [field.key, values[field.key]])),
    product_group_ref: values.product_group_ref,
    parameters: Object.fromEntries(fields.filter((field) => !["factor_ref", "product_group_ref"].includes(field.type)).map((field) => [field.key, values[field.key]])),
  };
}
