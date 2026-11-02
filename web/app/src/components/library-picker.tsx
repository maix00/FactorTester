import React, { useEffect, useRef, useState } from "react";
import { Button, Select } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import type { JSONObject } from "../configuration/draft.ts";
import {DetailsPanel} from "./details-panel.tsx";
import { LibraryCreate } from "./library-create.tsx";
import { ObjectReference } from "./object-reference.tsx";
import { notify } from "../notifications/core.ts";
export function FactorPicker({ value, label, disabled, onSelect, onPendingChange }: { onPendingChange?:(pending:boolean)=>void; value?: string; label?: string; disabled?: boolean; onSelect: (factor: JSONObject) => void }): React.ReactElement {
  const { t } = useTranslation(); const [rows, setRows] = useState<JSONObject[]>([]), [create, setCreate] = useState(false), [busy, setBusy] = useState(false);
  const pendingCallback=useRef(onPendingChange);pendingCallback.current=onPendingChange;
  const selectedCallback = useRef(onSelect); selectedCallback.current = onSelect;
  const selection = useRef<AbortController | null>(null);
  useEffect(() => () => {selection.current?.abort();pendingCallback.current?.(false);}, []);
  useEffect(() => {
    const controller = new AbortController();
    request("/api/factor-library/factors", { signal: controller.signal }).then((data) => setRows(data.factors || []))
      .catch((reason) => { if (!controller.signal.aborted) notify({code:"factor.options.failed",type:"error",message:reason.message}); });
    return () => controller.abort();
  }, []);
  const options = [...new Map(rows.map((row) => [String(row.ref || row.factor_ref), { value: String(row.ref || row.factor_ref), label: String(row.alias || row.factor_alias || row.ref) }])).values()];
  if (value && !options.some((option) => option.value === value)) options.unshift({ value, label: value });
  const current = rows.find(row => (row.ref || row.factor_ref) === value);
  return <div className="tr-library-picker">{create ? <DetailsPanel title={t("editor.newFactor")} onClose={()=>{setCreate(false);pendingCallback.current?.(false);}}><LibraryCreate kind="factor" embedded onCancel={() => {setCreate(false);pendingCallback.current?.(false);}} onCreated={(factor) => { setRows((old) => [...old, factor]); selectedCallback.current(factor); setCreate(false);pendingCallback.current?.(false); }} /></DetailsPanel> : <div className="tr-picker-control">
    <Select showSearch optionFilterProp="label" aria-label={label || t("catalog.factors")} value={value || undefined} options={options} loading={busy} disabled={disabled} onChange={(ref: string) => {
      const selected = rows.find((row) => (row.ref || row.factor_ref) === ref);
      const owner = selected?.owner_username ? `&owner_username=${encodeURIComponent(String(selected.owner_username))}` : "";
      selection.current?.abort(); const controller = new AbortController(); selection.current = controller;
      setBusy(true);pendingCallback.current?.(true); request(`/api/factor-library/factors/detail?factor_ref=${encodeURIComponent(ref)}${owner}`, { signal: controller.signal })
        .then((data) => { if (!controller.signal.aborted) {if ((data.factor?.ref||data.factor?.factor_ref)!==ref) throw new Error(t("editor.missingIdentity"));selectedCallback.current(data.factor);} }).catch((reason) => { if (!controller.signal.aborted) notify({code:"factor.select.failed",type:"error",message:t("objectReference.loadFailed"),description:reason.message}); }).finally(() => { if (!controller.signal.aborted) {setBusy(false);pendingCallback.current?.(false);} });
    }} />{value ? <ObjectReference icon value={{ kind:"factor", ref:value, label:String(current?.alias || current?.factor_alias || value), owner:typeof current?.owner_username === "string" ? current.owner_username : undefined }} /> : null}<Button type="text" icon={<PlusOutlined />} disabled={disabled} aria-label={t("editor.newFactor")} onClick={() => {setCreate(true);pendingCallback.current?.(true);}} /></div>}</div>;
}
