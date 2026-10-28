/** Presentation rows keep backend field identities and values unchanged. */
export type ProductFieldRow = {
  key: string;
  value: unknown;
  type?: string;
  label?: string;
  note?: string;
  source?: string;
};
export function productFieldRows(fields: unknown): ProductFieldRow[] {
  if (!fields || typeof fields !== "object" || Array.isArray(fields)) return [];
  return Object.entries(fields).map(([key, field]) => {
    if (field && typeof field === "object" && !Array.isArray(field) && "value" in field) {
      return { ...(field as Omit<ProductFieldRow, "key">), key };
    }
    return { key, value: field };
  });
}
