import React, { useEffect, useRef, useState } from "react";
import { Alert, Button, Drawer, Select } from "antd";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { ProductGroupEditor } from "./product-group-editor.tsx";
import { ObjectReference } from "./object-reference.tsx";
import { useCompactLayout } from "../configuration/layout.ts";
type Row = Record<string, any>;

/** Configurations keep their existing group-ref contract, including new groups. */
export function ProductGroupPicker({ value, onChange, disabled, label, id, scopeKey = "" }: {
  value?: string; onChange: (ref: string) => void; disabled?: boolean; label?: string; id?: string; scopeKey?: string;
}): React.ReactElement {
  const { t } = useTranslation(), compact = useCompactLayout();
  const [rows, setRows] = useState<Row[]>([]), [error, setError] = useState(""), [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false), [editorEpoch, setEditorEpoch] = useState(0);
  const generation = useRef(0), openedGeneration = useRef(0), latest = useRef(onChange); latest.current = onChange;
  useEffect(() => { generation.current += 1; setCreating(false); }, [scopeKey]);
  useEffect(() => { if (disabled) { generation.current += 1; setCreating(false); } }, [disabled]);
  useEffect(() => { const controller = new AbortController();
    request("/api/product-library/product-groups?view=summary", { signal: controller.signal })
      .then(result => { if (!controller.signal.aborted) setRows(result.groups || []); })
      .catch(reason => { if (!controller.signal.aborted) setError(reason.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { controller.abort(); generation.current += 1; };
  }, []);
  const ref = (row: Row): string => String(row.group_ref || row.ref || row.id || "");
  const options = rows.map(row => ({ value: ref(row), label: String(row.name || row.title || ref(row)) }));
  if (value && !options.some(option => option.value === value)) options.unshift({ value, label: value });
  return <div className="tr-product-group-picker">
    <div className="tr-reference-select"><Select id={id} aria-label={label || t("productGroup.name")} showSearch optionFilterProp="label"
      loading={loading} disabled={disabled} value={value || undefined} options={options} onChange={onChange} />
      {value ? <ObjectReference icon value={{ kind: "productGroup", ref: value, label: options.find(option => option.value === value)?.label || value }} /> : null}
      <Button disabled={disabled} onClick={() => { openedGeneration.current = generation.current; setEditorEpoch(n => n + 1); setCreating(true); }}>{t("productGroup.create")}</Button>
    </div>
    {error ? <Alert type="error" message={error} /> : null}
    <Drawer open={creating} title={t("productGroup.create")} width={compact ? "100%" : 700} onClose={() => { generation.current += 1; setCreating(false); }} destroyOnHidden>
      <ProductGroupEditor key={editorEpoch} embedded onCancel={() => setCreating(false)} onDeleted={() => setCreating(false)} onSaved={row => {
        if (openedGeneration.current !== generation.current) return;
        const identity = ref(row); if (!identity) { setError(t("productSelection.missingGroupRef")); return; }
        setRows(current => [row, ...current.filter(item => ref(item) !== identity)]); setCreating(false); latest.current(identity);
      }} />
    </Drawer>
  </div>;
}
