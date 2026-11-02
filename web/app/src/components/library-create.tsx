import React, { useEffect, useRef, useState } from "react";
import { Button, Form, Input, Select, Switch } from "antd";
import { useTranslation } from "react-i18next";
import {useAuth} from "../auth.tsx";
import { request } from "../configuration/api.ts";
import {factorParameterValues,parameterDefaults,factorSourceKey} from "../factor-parameters.ts";
import {FactorParameters} from "./factor-parameters.tsx";
import {familyConfigurationKey} from "../catalog-search.ts";
import {notify} from "../notifications/core.ts";
import { DetailsCancelButton, DetailsPanel } from "./details-panel.tsx";
import { useCompactLayout } from "../configuration/layout.ts";
import type { JSONObject } from "../configuration/draft.ts";

export function LibraryCreate({ kind, onCreated, onCancel, strategy, factor, embedded=false }: { embedded?:boolean; factor?:JSONObject; strategy?: JSONObject; kind: "factor" | "strategy"; onCreated: (value: JSONObject) => void; onCancel: () => void }): React.ReactElement {
  const { t } = useTranslation();
  const {session}=useAuth();
  const mobile = useCompactLayout();
  const finish = (value: JSONObject): void => { if (mobile && !strategy && !factor && history.state?.trDetail) history.back(); onCreated(value); };
  const [families, setFamilies] = useState<JSONObject[]>([]), [family, setFamily] = useState(factor?factorSourceKey(factor):"");
  const initialRevision = (strategy?.current_revision || {}) as JSONObject;
  const [name, setName] = useState(String(strategy?.name || "")), [source, setSource] = useState(String(initialRevision.source_code || "")), [entry, setEntry] = useState(String(initialRevision.entrypoint || "Strategy")), [params, setParams] = useState(JSON.stringify(factor ? factorParameterValues(factor.params||((factor.identity||{}) as JSONObject).params) : initialRevision.requirements || {}, null, 2));
  const [description, setDescription] = useState(String(strategy?.description || "")), [visibility, setVisibility] = useState(String(strategy?.visibility || "private"));
  const [parametersPending,setParametersPending]=useState(false);
  const [jsonMode,setJsonMode]=useState(false);
  const selectedFamily=families.find(row=>familyConfigurationKey(row)===family);
  const definitions=(factor?.parameter_definitions||selectedFamily?.parameter_definitions||selectedFamily?.params||[]) as JSONObject[];
  let parameterValues:JSONObject={};let validParameters=true;try{parameterValues=JSON.parse(params);validParameters=!!parameterValues&&typeof parameterValues==="object"&&!Array.isArray(parameterValues);}catch{validParameters=false;}
  const [busy, setBusy] = useState(false);const pending=useRef(false);
  useEffect(() => {
    if (kind !== "factor") return;
    const controller = new AbortController();
    request("/api/factor-library/families", { signal: controller.signal }).then((data) => setFamilies(data.families ?? []))
      .catch((reason) => { if (!controller.signal.aborted) notify({code:"family.options.load",type:"error",message:reason.message}); });
    return () => controller.abort();
  }, [kind]);
  const save = async (): Promise<void> => {
    if(pending.current||parametersPending)return;pending.current=true;setBusy(true);
    try {
      const values = JSON.parse(params);
      if (!values || typeof values !== "object" || Array.isArray(values)) throw new Error(t("editor.objectRequired"));
      if (kind === "strategy") {
        const result = await request(strategy?.strategy_ref ? `/api/strategy-library/strategies/${encodeURIComponent(String(strategy.strategy_ref))}` : "/api/strategy-library/strategies", { method: strategy?.strategy_ref ? "PATCH" : "POST", body: JSON.stringify({ name, description, entrypoint: entry, source_code: source, visibility, requirements: values }) });
        finish(result.strategy);
      } else {
        const result = await request(`/api/factor-library/configurations/${encodeURIComponent(family)}/factors`, { method: "POST", body: JSON.stringify({ params: values, mode: factor ? "edit" : "create",...(factor?{replace_factor_ref:factor.ref||factor.factor_ref,product_group:factor.product_group||factor.scope_key}: {}) }) });
        const frozen = result.factor || result.factors?.[0];
        if (!frozen?.ref && !frozen?.factor_ref) throw new Error(t("editor.missingIdentity"));
        // Resolve the exact registered version; no browser identity reconstruction.
        const registeredOwner=String(frozen.owner_username||session?.username||"");
        const detail = await request(`/api/factor-library/factors/detail?factor_ref=${encodeURIComponent(frozen.ref || frozen.factor_ref)}${registeredOwner ? `&owner_username=${encodeURIComponent(registeredOwner)}` : ""}`);
        finish(detail.factor);
      }
    } catch (reason) { notify({code:"library.save.failed",type:"error",message:reason instanceof Error ? reason.message : String(reason)}); }
    finally { pending.current=false;setBusy(false); }
  };
  const content = <div className="tr-library-create">{strategy ? <div className="tr-inline-editor-heading"><h2>{t("strategyDetail.edit")}</h2></div> : null}
    <Form layout="vertical" requiredMark={false}>
      {kind === "factor" ? <Form.Item label={t("catalog.families")}><Select aria-label={t("catalog.families")} showSearch optionFilterProp="label" value={family||undefined} disabled={!!factor} options={families.map(row=>{const alias=String(row.factor_family_alias||row.name||"");return {value:familyConfigurationKey(row),label:String(row.factor_family_name||alias)};})} onChange={value=>{setFamily(value);const selected=families.find(row=>familyConfigurationKey(row)===value);setParams(JSON.stringify(parameterDefaults((selected?.parameter_definitions||selected?.params||[]) as JSONObject[]),null,2));}}/></Form.Item> : null}
      {kind === "strategy" ? <><Form.Item label={t("editor.name")}><Input aria-label={t("editor.name")} value={name} onChange={(event) => setName(event.target.value)} /></Form.Item>
        {kind === "strategy" ? <Form.Item label={t("editor.entrypoint")}><Input aria-label={t("editor.entrypoint")} value={entry} onChange={(event) => setEntry(event.target.value)} /></Form.Item> : null}
        <Form.Item label={t("editor.source")}><Input.TextArea aria-label={t("editor.source")} className="tr-source-input" autoSize={{ minRows: 10 }} value={source} onChange={(event) => setSource(event.target.value)} /></Form.Item></> : null}
      {kind === "strategy" ? <><Form.Item label={t("library.description")}><Input.TextArea aria-label={t("library.description")} value={description} onChange={(event) => setDescription(event.target.value)} /></Form.Item><Form.Item label={t("library.visibility")}><Select aria-label={t("library.visibility")} value={visibility} onChange={setVisibility} options={["private", "shared", "public"].map((value) => ({ value, label: t(`strategyDetail.visibility.${value}`) }))} /></Form.Item></> : null}
      {kind==="factor"&&definitions.length?<div className="tr-inline-actions"><Switch checked={jsonMode||!validParameters} onChange={setJsonMode} aria-label={t("editor.jsonParameters")}/><span>{t("editor.jsonParameters")}</span></div>:null}
      {kind==="factor"&&definitions.length&&!jsonMode&&validParameters?<FactorParameters definitions={definitions} values={parameterValues} disabled={busy} onPendingChange={setParametersPending} onChange={values=>setParams(JSON.stringify(values,null,2))}/>:<Form.Item label={t(kind === "strategy" ? "editor.requirements" : "editor.parameters")}><Input.TextArea aria-label={t("editor.parameters")} className="tr-source-input" autoSize={{ minRows: 5 }} value={params} onChange={(event) => setParams(event.target.value)} /></Form.Item>}
      <div className="tr-inline-actions"><Button type="primary" aria-label={t("configuration.save")} aria-busy={busy} loading={busy} disabled={busy||parametersPending||(kind === "strategy" ? !name || !source : !family)} onClick={() => void save()}>{t("configuration.save")}</Button><DetailsCancelButton disabled={busy} closePanel={mobile && !strategy && !factor} onCancel={onCancel}/></div>
    </Form>
  </div>;
  return mobile && !strategy && !factor && !embedded ? <DetailsPanel title={t(kind === "factor" ? "editor.newFactor" : "editor.newStrategy")} onClose={onCancel}>{content}</DetailsPanel> : content;
}
