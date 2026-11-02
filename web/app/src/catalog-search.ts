/** Match the same product fields that the directory shows, without changing server pagination. */
export function catalogSearchMatches(query: string, displayed: string[], extra: unknown[] = []): boolean {
  const needle = query.trim().toLocaleLowerCase();
  return !needle || [...displayed, ...extra].some(value =>
    typeof value === "string" && value.toLocaleLowerCase().includes(needle));
}

/** Select the registered resource, never an unrelated array in the same response. */
export function catalogRows(payload: Record<string, unknown>, domain: string, tab: string): Record<string, unknown>[] {
  const key = domain === "strategies" ? tab === "strategyFamilies" ? "families" : "items"
    : domain === "factors" ? tab === "sets" ? "items" : tab
    : tab;
  const rows = payload[key];
  if (!Array.isArray(rows)) throw new Error(`Missing catalog resource: ${key}`);
  return rows;
}

export function catalogIdentity(row:Record<string,any>):string {
 return String(row.target_ref||row.group_ref||row.ref||row.factor_ref||row.strategy_ref||row.template_ref||row.family_ref||row.set_ref||row.id||row.family_id||row.bundle_id||row.source_name||row.factor_family_alias||row.alias||row.name||"");
}
export function catalogTitle(row:Record<string,any>):string {
 return String(row.family_name||row.bundle_name||row.source_name||row.title_zh||row.name||row.title||row.factor_family_name||row.factor_alias||row.alias||catalogIdentity(row));
}

export function familyConfigurationKey(row:Record<string,any>):string {
 const alias=String(row.factor_family_alias||row.name||"");
 if(alias.includes(":"))return alias;
 const owner=row.source==="public"||row.factor_kind==="public"||String(row.owner_username||"").startsWith("__")?"public":String(row.owner_username||"");
 return owner?`${owner}:${alias}`:alias;
}
