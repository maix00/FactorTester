(() => {
  function groupRef(value) {
    const explicit = String(value?.group_ref || "").trim();
    if (explicit) return explicit;
    const id = String(value?.id || "").trim();
    return id ? `product-group:${id}` : "";
  }

  function productGroupNames(groups) {
    return new Map((groups || []).flatMap(group => {
      const ref = groupRef(group);
      return ref ? [[ref, group.name || ref]] : [];
    }));
  }

  function subjectGroups(groups) {
    const index = new Map();
    for (const group of groups || []) {
      const ref = groupRef(group);
      if (!ref) continue;
      const subjects = [
        ...(Array.isArray(group.factor_refs) ? group.factor_refs : []),
        ...(Array.isArray(group.factor_set_refs) ? group.factor_set_refs : []),
      ];
      for (const subjectRef of subjects) {
        if (!index.has(subjectRef)) index.set(subjectRef, []);
        if (!index.get(subjectRef).includes(ref)) index.get(subjectRef).push(ref);
      }
    }
    return index;
  }

  function subjectRefs(item) {
    if (item.kind === "factor") return [item.value.factor_ref].filter(Boolean);
    return [item.value.target_ref, item.value.set_ref].filter(Boolean);
  }

  function productGroupRefs(item, groupsBySubject) {
    const result = [];
    for (const subjectRef of subjectRefs(item)) {
      for (const group of groupsBySubject.get(subjectRef) || []) {
        if (!result.includes(group)) result.push(group);
      }
    }
    return result;
  }

  function groupLabels(item, names, groupsBySubject, unboundLabel) {
    const refs = productGroupRefs(item, groupsBySubject);
    if (!refs.length) return [unboundLabel];
    return refs.map(ref => names.get(ref) || ref);
  }

  function matches(value, query) {
    return !query || JSON.stringify(value || {}).toLowerCase().includes(query);
  }

  function familyName(value) {
    return value.chinese_name
      || value.factor_family_alias
      || value.factor_family_name
      || "";
  }

  function factorExpression(value) {
    for (const key of ["math_expr", "formula", "latex", "factor_expr", "expression"]) {
      const candidate = value?.[key];
      if (typeof candidate === "string" && candidate.trim()) return candidate.trim();
    }
    return "";
  }

  function owner(value) {
    return value.owner_alias || value.owner_username || value.profile_id || "";
  }

  function mergeFactorSets(serverItems, localItems) {
    const server = Array.isArray(serverItems) ? serverItems : [];
    const local = Array.isArray(localItems) ? localItems : [];
    const values = server.map(item => ({...item, visibility: "server"}));
    const exact = new Map(values
      .filter(item => item.target_ref)
      .map((item, index) => [item.target_ref, index]));
    for (const item of local) {
      const index = item.target_ref ? exact.get(item.target_ref) : undefined;
      if (index !== undefined) {
        values[index] = {...values[index], ...item, visibility: "synced"};
      } else {
        values.push({...item, visibility: "local"});
      }
    }
    return values;
  }

  function decodeBase64URL(value) {
    const padded = String(value || "").replace(/-/g, "+").replace(/_/g, "/")
      .padEnd(Math.ceil(String(value || "").length / 4) * 4, "=");
    const bytes = Uint8Array.from(atob(padded), character => character.charCodeAt(0));
    return new TextDecoder().decode(bytes);
  }

  function ownerRef(scope) {
    const match = /^([a-z][a-z0-9_]*)-(.+)$/i.exec(scope);
    return match ? `${match[1]}:${match[2]}` : scope;
  }

  function aliasParams(alias) {
    return String(alias || "").split("|").slice(1).map(part => {
      const separator = part.indexOf(":");
      return {
        alias: separator < 0 ? part : part.slice(0, separator),
        value: separator < 0 ? "" : part.slice(separator + 1),
        redacted: false,
      };
    }).filter(item => item.alias);
  }

  function decodeFrozenFactorRef(targetRef) {
    const parts = String(targetRef || "").split(":");
    if (parts.length !== 7 || parts[0] !== "factor" || parts[1] !== "v1") return null;
    try {
      const alias = decodeBase64URL(parts[4]);
      return {
        factorRef: targetRef,
        alias,
        family: alias.split("|", 1)[0],
        ownerRef: ownerRef(parts[2]),
        gitCommit: parts[5],
        gitBlob: parts[6],
        relativePath: decodeBase64URL(parts[3]),
        params: aliasParams(alias),
      };
    } catch (_) {
      return null;
    }
  }

  window.FTFactorModel = Object.freeze({
    decodeFrozenFactorRef,
    factorExpression,
    familyName,
    groupLabels,
    groupRef,
    matches,
    mergeFactorSets,
    owner,
    productGroupNames,
    productGroupRefs,
    subjectGroups,
  });
})();
