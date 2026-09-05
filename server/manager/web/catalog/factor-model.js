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
    if (item.kind === "factor") {
      return [item.value.ref || item.value.factor_ref].filter(Boolean);
    }
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

  const searchTexts = new WeakMap();
  const familyTexts = new WeakMap();
  function matches(value, query) {
    if (!query) return true;
    if (!value || typeof value !== "object") return false;
    let text = searchTexts.get(value);
    if (text === undefined) {
      text = JSON.stringify(value).toLowerCase();
      searchTexts.set(value, text);
    }
    return text.includes(String(query).toLowerCase());
  }

  function familySearchText(value) {
    const item = value || {};
    return [
      familyName(item),
      item.factor_family_alias,
      description(item),
      item.owner_alias,
      item.owner_username,
      ...(Array.isArray(item.categories) ? item.categories : []),
    ].filter(item => String(item || "").trim()).join(" ").toLowerCase();
  }

  function matchesFamily(value, query) {
    if (!query) return true;
    let text = familyTexts.get(value);
    if (text === undefined) {
      text = familySearchText(value);
      familyTexts.set(value, text);
    }
    return text.includes(String(query).toLowerCase());
  }

  function familyName(value) {
    return value?.schema_version === 2
      ? String(value?.identity?.family_alias || "")
      : value.factor_family_name
      || value.factor_family_alias
      || value.family
      || value.chinese_name
      || "";
  }

  function description(value) {
    // Lists need the compact human name declared by FactorFamily.desc.
    // The projection exposes that value as chinese_name; description is the
    // longer prose reserved for the detail page.
    return String(
      value?.chinese_name || value?.title_zh || value?.desc
      || value?.description || "",
    ).trim();
  }

  function factorExpression(value, options = {}) {
    // math_expr = 因子家族_LATEX模板_（自包含，\textcolor{red}{alias} 占位，未叠加）
    // resolved_math_expr = 参数解析+嵌套因子叠加后的完整公式（查看模式渲染）
    // instance=true → 优先 resolved_math_expr（叠加后）；否则 math_expr（模板）。
    const keys = options.instance === true
      ? ["resolved_math_expr", "math_expr", "formula", "latex", "factor_expr", "expression"]
      : ["math_expr", "formula", "latex", "factor_expr", "expression", "resolved_math_expr"];
    for (const key of keys) {
      const candidate = value?.[key];
      if (typeof candidate === "string" && candidate.trim()) return candidate.trim();
    }
    return "";
  }

  function sourceMetadata(value) {
    const item = value || {};
    const frozen = frozenFactorIdentity(item);
    if (frozen) return {
      factor_owner_ref: frozen.ownerRef,
      factor_params: frozen.params,
      family_formula_fingerprint: frozen.familyFormulaFingerprint,
      self_formula_fingerprint: frozen.selfFormulaFingerprint,
    };
    const owner = item.factor_owner_ref || item.owner_ref
      || item.owner_username || item.profile_id || "";
    const params = item.factor_params ?? item.params ?? [];
    const result = {
      factor_owner_ref: owner,
      factor_params: params,
    };
    for (const key of ["family_formula_fingerprint", "self_formula_fingerprint"]) {
      const fingerprint = String(item[key] || "").trim();
      if (fingerprint) result[key] = fingerprint;
    }
    return result;
  }

  function withSourceMetadata(value) {
    return {...(value || {}), ...sourceMetadata(value)};
  }

  function owner(value) {
    return value?.schema_version === 2
      ? String(value.owner_ref || "")
      : value.owner_alias || value.owner_username || value.profile_id || "";
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

  function frozenFactorIdentity(value) {
    const item = value && typeof value === "object" ? value : {};
    const identity = item.identity && typeof item.identity === "object"
      ? item.identity : null;
    if (item.schema_version !== 2 || !identity) return null;
    const factorRef = String(item.ref || "").trim();
    const alias = String(item.alias || "").trim();
    const family = String(identity.family_alias || "").trim();
    const ownerRef = String(item.owner_ref || "").trim();
    const familyFormulaFingerprint = String(
      identity.family_formula_fingerprint || "",
    ).trim();
    const selfFormulaFingerprint = String(
      identity.self_formula_fingerprint || "",
    ).trim();
    if (!/^factor:v2:[A-Za-z0-9_-]{43}$/.test(factorRef)
        || !alias || !family || !ownerRef
        || !/^[0-9a-f]{64}$/.test(familyFormulaFingerprint)
        || !/^[0-9a-f]{64}$/.test(selfFormulaFingerprint)) return null;
    const record = {
      schema_version: 2,
      ref: factorRef,
      alias,
      owner_ref: ownerRef,
      identity: structuredClone(identity),
    };
    return {
      factorRef, alias, family, ownerRef,
      familyFormulaFingerprint, selfFormulaFingerprint,
      record,
      params: identity.params || {},
    };
  }

  function objectChoice(value) {
    const item = value && typeof value === "object" ? value : {};
    const ref = String(item.ref || "").trim();
    const alias = String(item.alias || "").trim();
    if (item.schema_version !== 2 || !ref || !alias
        || !item.identity || typeof item.identity !== "object") return null;
    const frozen = frozenFactorIdentity(item);
    return frozen ? {value: ref, label: alias, record: frozen.record} : null;
  }

  window.FTFactorModel = Object.freeze({
    frozenFactorIdentity,
    objectChoice,
    description,
    factorExpression,
    sourceMetadata,
    withSourceMetadata,
    familyName,
    groupLabels,
    groupRef,
    matches,
    matchesFamily,
    mergeFactorSets,
    owner,
    productGroupNames,
    productGroupRefs,
    subjectGroups,
  });
})();
