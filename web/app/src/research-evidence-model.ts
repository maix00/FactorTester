export type ApplicabilityField = {name:string; section?:string; type:string; exposed?:boolean; label_zh?:string};
export type ApplicabilityDraft = Record<string, string>;

/** Preserve non-exposed fields; only edit fields declared by the server contract. */
export function applicabilityDraft(initial: Record<string, unknown>, fields: ApplicabilityField[]): ApplicabilityDraft {
  const draft: ApplicabilityDraft = {};
  for (const field of fields.filter(item => item.exposed !== false)) {
    const value = initial[field.name];
    if (field.type === "string_array") draft[field.name] = Array.isArray(value) ? value.join("\n") : "";
    else if (field.type === "reference") draft[field.name] = typeof value === "string" ? value : "";
    else if (field.type === "time_window") {
      const window = value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
      draft[`${field.name}.start`] = String(window.start || ""); draft[`${field.name}.end`] = String(window.end || "");
    }
  }
  return draft;
}

export function applicabilityValue(initial: Record<string, unknown>, fields: ApplicabilityField[], draft: ApplicabilityDraft): Record<string, unknown> {
  const result = structuredClone(initial);
  for (const field of fields.filter(item => item.exposed !== false)) {
    if (field.type === "string_array") {
      const values = (draft[field.name] || "").split("\n").map(item => item.trim()).filter(Boolean);
      if (values.length) result[field.name] = values; else delete result[field.name];
    } else if (field.type === "reference") {
      const value = (draft[field.name] || "").trim();
      if (value) result[field.name] = value; else delete result[field.name];
    } else if (field.type === "time_window") {
      const start = (draft[`${field.name}.start`] || "").trim(), end = (draft[`${field.name}.end`] || "").trim();
      if (start || end) result[field.name] = { ...(start ? {start} : {}), ...(end ? {end} : {}) }; else delete result[field.name];
    }
  }
  return result;
}
