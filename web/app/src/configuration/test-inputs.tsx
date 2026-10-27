import React, { useEffect, useId, useRef, useState } from "react";
import Form from "@rjsf/antd";
import validator from "@rjsf/validator-ajv8";
import type { RJSFSchema } from "@rjsf/utils";
import { NO_DEFAULTS } from "./form-options.ts";
import { Alert, Select } from "antd";
import { useTranslation } from "react-i18next";
import { FactorPicker } from "../components/library-picker.tsx";
import { request } from "./api.ts";
import { parseDraft, readPath, writePath, type JSONObject } from "./draft.ts";
import { attachFrozenFactors } from "./strategies.ts";

export function TestInputs({ analysis, text, onChange, schema, defaults }: { schema?: JSONObject; defaults?: JSONObject; analysis: string; text: string; onChange: (text: string) => void }): React.ReactElement {
  const { t } = useTranslation();
  const id = useId();
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
    if (analysis === "ic") return writePath(next, ["analyses", "ic", "configuration_groups"], [{ config_group_id: "ic-1", ...defaults, ...group, ...patch }]);
    for (const [key, item] of Object.entries(patch)) next = writePath(next, [...settings, key], item);
    return next;
  };
  return <div className="tr-config-field-editor"><div className="tr-config-setting-row"><label>{t("catalog.factors")}</label><div className="tr-config-setting-control"><FactorPicker value={typeof factorRef === "string" ? factorRef : undefined} onSelect={(factor) => {
    const next = attachFrozenFactors(latest.current, [factor]);
    onChange(update(analysis === "ic" ? { factor_ref: factor.ref } : { factor_ref: factor.ref, factor_alias: factor.alias, factor_family_alias: readPath(factor, ["identity", "family_alias"]) || factor.factor_family_alias }, next));
  }} /></div></div>
  <div className="tr-config-setting-row"><label>{t("configuration.strategyFields.product_group_ref")}</label><div className="tr-config-setting-control"><Select showSearch optionFilterProp="label" aria-label={t("configuration.strategyFields.product_group_ref")} value={typeof productRef === "string" ? productRef : undefined} options={groups.map((row) => ({ value: String(row.ref || row.group_ref || row.id), label: String(row.name || row.title || row.id) }))} onChange={(ref) => onChange(update(analysis === "ic" ? { product_scope_ref: ref } : { product_path_selection_id: ref }))} /></div></div>
  {analysis === "ic" && schema ? Object.entries(schema.properties as Record<string, JSONObject> || {}).map(([key, field]) => {
    const current = (group || defaults || {})[key];
    return <div className="tr-config-setting-row" key={key}><label htmlFor={`tr-input-${id}-${key}${key === "horizon" ? "_sampling" : ""}`}>{String(field.title || key)}</label><div className="tr-config-setting-control"><Form idPrefix={`tr-input-${id}-${key}`} schema={field as RJSFSchema} formData={current}
      validator={validator} experimental_defaultFormStateBehavior={NO_DEFAULTS} uiSchema={{ "ui:label": false, "ui:title": "", "ui:description": "", "ui:options": { expandable: false }, "ui:submitButtonOptions": { norender: true } }}
      onChange={(event) => { let value = event.formData; if (key === "horizon" && value?.sampling === "scale_aware") value = { sampling: "scale_aware" }; if (JSON.stringify(value) !== JSON.stringify(current)) onChange(update({ [key]: value })); }}><span /></Form></div></div>;
  }) : null}
  {error ? <Alert type="error" message={error} /> : null}</div>;
}
