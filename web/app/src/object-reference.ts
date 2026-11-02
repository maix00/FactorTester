/** Object identities must come from the enclosing record, never a display label. */
export type ObjectKind = "user" | "profile" | "product" | "productGroup" | "factor" | "factorFamily" | "strategy" | "strategyFamily";
export interface ObjectReferenceValue {
  kind: ObjectKind;
  ref: string;
  label?: string;
  owner?: string;
  profileKey?: string;
  familyAlias?: string;
  versionRef?: string;
}

/** Display names never replace the address used to open an object. */
export function objectReferenceLabel(value: ObjectReferenceValue, session: {username?:string;alias?:string} | null): string {
  if (value.kind === "user") {
    const explicit = value.label?.trim();
    const label = explicit && explicit !== value.ref ? explicit :
      value.ref && value.ref === session?.username && session.alias?.trim() ? session.alias.trim() : explicit || value.ref;
    // Presentation only: old qualified user refs encode organization@alias@id.
    // Keep the actual ref intact; neither identity nor authority is resolved here.
    const qualified = /^[^@\s]+@([^@]+)@[0-9]+$/.exec(label);
    return qualified ? qualified[1] : label;
  }
  if (value.label && value.label !== value.ref) return value.label;
  return value.label || value.ref;
}

/** Recognize explicit schema fields; arbitrary strings are not treated as links. */
export function referenceForField(key: string, value: unknown, parent: Record<string, unknown> = {}): ObjectReferenceValue | null {
  if (typeof value !== "string" || !value.trim() || value === "—") return null;
  const ref = value.trim();
  const owner = typeof parent.owner_username === "string" ? parent.owner_username :
    typeof parent.owner_ref === "string" ? parent.owner_ref : undefined;
  if (["owner", "owner_ref", "owner_username", "principal_ref", "username", "author_ref", "authorized_users", "shared_principals"].includes(key)) {
    // Public-catalog sentinels describe a library scope, not a user account.
    const aliasKey = ["owner", "owner_ref", "owner_username"].includes(key) ? "owner_alias" :
      key === "principal_ref" ? "principal_alias" : key === "author_ref" ? "author_alias" : "user_alias";
    const label = parent[aliasKey];
    return ref.startsWith("__") ? null : { kind: "user", ref,
      ...(typeof label === "string" && label.trim() ? {label:label.trim()} : {}) };
  }
  if (["profile_ref", "profile_id", "profile_key", "profile_refs"].includes(key)) return {
    kind: "profile", ref, owner,
    profileKey: key === "profile_key" ? ref : typeof parent.profile_key === "string" ? parent.profile_key : undefined,
  };
  if (["product_ref", "product_name", "product_refs"].includes(key)) return { kind: "product", ref };
  if (["product_group_ref", "product_group_refs"].includes(key) || ((key === "group_ref" || key === "product_path_selection_id" || key === "product_scope_ref") && ref.startsWith("product-group:"))) return { kind: "productGroup", ref };
  if (key === "factor_ref" || key === "factor_refs" || ref.startsWith("factor:v2:")) return { kind: "factor", ref, owner };
  if (key === "factor_family_ref" || key === "factor_family_alias" || (key === "family_ref" && ("factor_ref" in parent || "factor_family_alias" in parent))) return {
    kind: "factorFamily", ref,
    owner: typeof parent.family_owner_username === "string" ? parent.family_owner_username : undefined,
    ...(typeof parent.factor_family_alias === "string" ? {familyAlias:parent.factor_family_alias} : {}),
    ...(typeof parent.family_formula_fingerprint === "string" ? {versionRef:parent.family_formula_fingerprint} : {}),
  };
  if (["template_ref", "strategy_family_ref", "strategy_family_refs"].includes(key)) return { kind: "strategyFamily", ref };
  if (key === "strategy_ref" || key === "strategy_refs") return { kind: "strategy", ref };
  return null;
}

/** Resolve an exact family identity. An ambiguous alias must never select a different owner's family. */
export function matchingFamily(rows: Record<string, unknown>[], ref: string, owner?: string, frozen?:{alias?:string;version?:string}): Record<string, unknown> | null {
  const matches = rows.filter(row => {
    const ids = [row.family_ref, row.ref, row.factor_family_alias, row.family_alias, row.alias];
    return ids.some(id => id === ref) && (!owner || row.owner_username === owner || row.owner_ref === owner);
  });
  if(matches.length === 1)return matches[0];
  // Frozen heads require explicit source identity and full revision, never a display label.
  if(matches.length || !owner || !frozen?.alias || !/^[0-9a-f]{64}$/i.test(frozen.version||""))return null;
  const sources=rows.filter(row => [row.factor_family_alias,row.family_alias,row.alias].includes(frozen.alias) && (row.owner_username===owner||row.owner_ref===owner));
  return sources.length===1?sources[0]:null;
}

/** Only canonical IDs with a real detail endpoint become remote requests. */
export function objectDetailURL(value: ObjectReferenceValue): string | null {
  const ref = encodeURIComponent(value.ref);
  switch (value.kind) {
    case "profile": return value.profileKey ? `/api/client/profile-directory/profile?${new URLSearchParams({ scope: "servers", profile_key: value.profileKey })}` : null;
    case "productGroup": return `/api/product-library/product-groups/${ref}`;
    case "factor": return `/api/factor-library/factors/detail?factor_ref=${ref}${value.owner ? `&owner_username=${encodeURIComponent(value.owner)}` : ""}`;
    case "factorFamily": return "/api/factor-library/families";
    case "strategy": return `/api/strategy-library/strategies/${ref}?include_source=0`;
    case "strategyFamily": return `/api/strategy-library/factor-strategies/${ref}`;
    default: return null;
  }
}
