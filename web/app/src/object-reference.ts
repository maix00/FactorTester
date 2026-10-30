/** Object identities must come from the enclosing record, never a display label. */
export type ObjectKind = "user" | "profile" | "product" | "productGroup" | "factor" | "factorFamily" | "strategy" | "strategyFamily";
export interface ObjectReferenceValue {
  kind: ObjectKind;
  ref: string;
  label?: string;
  owner?: string;
  profileKey?: string;
}

/** Recognize explicit schema fields; arbitrary strings are not treated as links. */
export function referenceForField(key: string, value: unknown, parent: Record<string, unknown> = {}): ObjectReferenceValue | null {
  if (typeof value !== "string" || !value.trim() || value === "—") return null;
  const ref = value.trim();
  const owner = typeof parent.owner_username === "string" ? parent.owner_username :
    typeof parent.owner_ref === "string" ? parent.owner_ref : undefined;
  if (["owner", "owner_ref", "owner_username", "principal_ref", "username", "author_ref", "authorized_users", "shared_principals"].includes(key)) {
    // Public-catalog sentinels describe a library scope, not a user account.
    return ref.startsWith("__") ? null : { kind: "user", ref };
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
  };
  if (["template_ref", "strategy_family_ref", "strategy_family_refs"].includes(key)) return { kind: "strategyFamily", ref };
  if (key === "strategy_ref" || key === "strategy_refs") return { kind: "strategy", ref };
  return null;
}

/** Resolve an exact family identity. An ambiguous alias must never select a different owner's family. */
export function matchingFamily(rows: Record<string, unknown>[], ref: string, owner?: string): Record<string, unknown> | null {
  const matches = rows.filter(row => {
    const ids = [row.family_ref, row.ref, row.factor_family_alias, row.family_alias, row.alias];
    return ids.some(id => id === ref) && (!owner || row.owner_username === owner || row.owner_ref === owner);
  });
  return matches.length === 1 ? matches[0] : null;
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
