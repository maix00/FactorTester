import React, { useEffect, useRef, useState } from "react";
import { Alert, Button, Select } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import type { JSONObject } from "../configuration/draft.ts";
import { LibraryCreate } from "./library-create.tsx";
export function FactorPicker({ value, label, disabled, onSelect }: { value?: string; label?: string; disabled?: boolean; onSelect: (factor: JSONObject) => void }): React.ReactElement {
  const { t } = useTranslation(); const [rows, setRows] = useState<JSONObject[]>([]), [create, setCreate] = useState(false), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const selectedCallback = useRef(onSelect); selectedCallback.current = onSelect;
  const selection = useRef<AbortController | null>(null);
  useEffect(() => () => selection.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController();
    request("/api/factor-library/factors", { signal: controller.signal }).then((data) => setRows(data.factors || []))
      .catch((reason) => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, []);
  const options = [...new Map(rows.map((row) => [String(row.ref || row.factor_ref), { value: String(row.ref || row.factor_ref), label: String(row.alias || row.factor_alias || row.ref) }])).values()];
  if (value && !options.some((option) => option.value === value)) options.unshift({ value, label: value });
  return <div className="tr-library-picker">{create ? <LibraryCreate kind="factor" onCancel={() => setCreate(false)} onCreated={(factor) => { setRows((old) => [...old, factor]); selectedCallback.current(factor); setCreate(false); }} /> : <div className="tr-picker-control">
    <Select showSearch optionFilterProp="label" aria-label={label || t("catalog.factors")} value={value || undefined} options={options} loading={busy} disabled={disabled} onChange={(ref: string) => {
      const selected = rows.find((row) => (row.ref || row.factor_ref) === ref);
      const owner = selected?.owner_username ? `&owner_username=${encodeURIComponent(String(selected.owner_username))}` : "";
      selection.current?.abort(); const controller = new AbortController(); selection.current = controller;
      setBusy(true); setError(""); request(`/api/factor-library/factors/detail?factor_ref=${encodeURIComponent(ref)}${owner}`, { signal: controller.signal })
        .then((data) => { if (!controller.signal.aborted) selectedCallback.current(data.factor); }).catch((reason) => { if (!controller.signal.aborted) setError(reason.message); }).finally(() => { if (!controller.signal.aborted) setBusy(false); });
    }} /><Button type="text" icon={<PlusOutlined />} disabled={disabled} aria-label={t("editor.newFactor")} onClick={() => setCreate(true)} /></div>}{error ? <Alert type="error" message={error} /> : null}</div>;
}
