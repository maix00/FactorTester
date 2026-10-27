import React, { useEffect, useRef, useState } from "react";
import { Alert, Select } from "antd";
import { useTranslation } from "react-i18next";
import { FactorPicker } from "../components/library-picker.tsx";
import { request } from "./api.ts";
import { parseDraft, readPath, writePath, type JSONObject } from "./draft.ts";
import { attachFrozenFactors } from "./strategies.ts";

export function TestInputs({ analysis, text, onChange }: { analysis: string; text: string; onChange: (text: string) => void }): React.ReactElement {
  const { t } = useTranslation();
  const [groups, setGroups] = useState<JSONObject[]>([]), [error, setError] = useState("");
  useEffect(() => { const controller = new AbortController();
    request("/api/product-library/product-groups?view=summary", { signal: controller.signal }).then((data) => setGroups(data.groups || [])).catch((reason) => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, []);
  const latest = useRef(text); latest.current = text;
  const value = parseDraft(text).value;
  const group = (readPath(value, ["analyses", "ic", "configuration_groups"]) as JSONObject[] | undefined)?.[0];
  const settings = ["analyses", analysis, "execution", "settings"];
  const factorRef = analysis === "ic" ? group?.factor_ref : readPath(value, [...settings, "factor_ref"]);
  const productRef = analysis === "ic" ? group?.product_scope_ref : readPath(value, [...settings, "product_path_selection_id"]);
  const update = (patch: JSONObject, next = latest.current): string => {
    if (analysis === "ic") return writePath(next, ["analyses", "ic", "configuration_groups"], [{ config_group_id: "ic-1", horizon: { sampling: "explicit", bases: ["signal"], multipliers: [1] }, entry_delay_bars: 0, methods: ["rank"], return_price_basis: "next_open_to_open_adjusted", ...group, ...patch }]);
    for (const [key, item] of Object.entries(patch)) next = writePath(next, [...settings, key], item);
    return next;
  };
  return <div className="tr-config-field-editor"><div className="tr-config-setting-row"><label>{t("catalog.factors")}</label><div className="tr-config-setting-control"><FactorPicker value={typeof factorRef === "string" ? factorRef : undefined} onSelect={(factor) => {
    const next = attachFrozenFactors(latest.current, [factor]);
    onChange(update(analysis === "ic" ? { factor_ref: factor.ref } : { factor_ref: factor.ref, factor_alias: factor.alias, factor_family_alias: readPath(factor, ["identity", "family_alias"]) || factor.factor_family_alias }, next));
  }} /></div></div>
  <div className="tr-config-setting-row"><label>{t("configuration.strategyFields.product_group_ref")}</label><div className="tr-config-setting-control"><Select showSearch optionFilterProp="label" aria-label={t("configuration.strategyFields.product_group_ref")} value={typeof productRef === "string" ? productRef : undefined} options={groups.map((row) => ({ value: String(row.ref || row.group_ref || row.id), label: String(row.name || row.title || row.id) }))} onChange={(ref) => onChange(update(analysis === "ic" ? { product_scope_ref: ref } : { product_path_selection_id: ref }))} /></div></div>
  {error ? <Alert type="error" message={error} /> : null}</div>;
}
