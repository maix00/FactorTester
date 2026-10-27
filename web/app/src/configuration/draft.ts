/** The JSON text is the sole editable draft; parsed values are projections. */
export type JSONObject = Record<string, unknown>;
export type Path = string[];
export interface Draft { text: string; savedText: string; revision: number; source?: "json" | "form" | "load" | "save" }

export function parseDraft(text: string): { value: JSONObject; error?: never } | { error: string; value?: never } {
  try {
    const value: unknown = JSON.parse(text);
    if (value === null || Array.isArray(value) || typeof value !== "object") return { error: "objectRequired" };
    return { value: value as JSONObject };
  } catch (error) { return { error: error instanceof Error ? error.message : String(error) }; }
}

export function createDraft(payload: JSONObject, revision: number): Draft {
  const text = JSON.stringify(payload, null, 2);
  return { text, savedText: text, revision, source: "load" };
}

export function readPath(value: unknown, path: Path): unknown {
  return path.reduce<unknown>((current, key) => (
    current !== null && typeof current === "object" ? (current as JSONObject)[key] : undefined
  ), value);
}

export function writePath(text: string, path: Path, value: unknown): string {
  const parsed = parseDraft(text);
  if (parsed.error || !parsed.value) throw new Error(parsed.error);
  if (path.some((key) => ["__proto__", "prototype", "constructor"].includes(key))) throw new Error("unsafePath");
  const root = structuredClone(parsed.value);
  if (!path.length) return JSON.stringify(value, null, 2);
  let target = root;
  for (const key of path.slice(0, -1)) {
    const child = target[key];
    if (child === undefined) target[key] = {};
    else if (child === null || typeof child !== "object" || Array.isArray(child)) throw new Error("invalidParent");
    target = target[key] as JSONObject;
  }
  const key = path[path.length - 1];
  if (value === undefined) delete target[key];
  else target[key] = structuredClone(value);
  return JSON.stringify(root, null, 2);
}

/** A save acknowledgment must not erase edits made while the request ran. */
export function acknowledgeSave(current: Draft, submittedText: string, payload: JSONObject, revision: number): Draft {
  const savedText = JSON.stringify(payload, null, 2);
  return { text: current.text === submittedText ? savedText : current.text, savedText, revision,
    source: current.text === submittedText ? "save" : current.source };
}

export function fieldSchema(schema: JSONObject, path: Path): JSONObject {
  let current = schema;
  for (const key of path) {
    const properties = current.properties as Record<string, JSONObject> | undefined;
    current = properties?.[key] ?? {};
  }
  return current;
}
