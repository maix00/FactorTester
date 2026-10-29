import React, { useEffect, useState } from "react";
import { Alert, Button, Form, Input, Select, Switch } from "antd";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { DetailsPanel } from "./details-panel.tsx";
import { useCompactLayout } from "../configuration/layout.ts";
import type { JSONObject } from "../configuration/draft.ts";

export function LibraryCreate({ kind, onCreated, onCancel, strategy }: { strategy?: JSONObject; kind: "factor" | "strategy"; onCreated: (value: JSONObject) => void; onCancel: () => void }): React.ReactElement {
  const { t } = useTranslation();
  const mobile = useCompactLayout();
  const finish = (value: JSONObject): void => { if (mobile && !strategy && history.state?.trDetail) history.back(); onCreated(value); };
  const [families, setFamilies] = useState<JSONObject[]>([]), [family, setFamily] = useState("");
  const initialRevision = (strategy?.current_revision || {}) as JSONObject;
  const [name, setName] = useState(String(strategy?.name || "")), [source, setSource] = useState(String(initialRevision.source_code || "")), [entry, setEntry] = useState(String(initialRevision.entrypoint || "Strategy")), [params, setParams] = useState(JSON.stringify(initialRevision.requirements || {}, null, 2));
  const [description, setDescription] = useState(String(strategy?.description || "")), [visibility, setVisibility] = useState(String(strategy?.visibility || "private"));
  const [newFamily, setNewFamily] = useState(false), [createdFamily, setCreatedFamily] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  useEffect(() => {
    if (kind !== "factor") return;
    const controller = new AbortController();
    request("/api/factor-library/families", { signal: controller.signal }).then((data) => setFamilies(data.families ?? []))
      .catch((reason) => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, [kind]);
  const save = async (): Promise<void> => {
    setBusy(true); setError("");
    try {
      const values = JSON.parse(params);
      if (!values || typeof values !== "object" || Array.isArray(values)) throw new Error(t("editor.objectRequired"));
      if (kind === "strategy") {
        const result = await request(strategy?.strategy_ref ? `/api/strategy-library/strategies/${encodeURIComponent(String(strategy.strategy_ref))}` : "/api/strategy-library/strategies", { method: strategy?.strategy_ref ? "PATCH" : "POST", body: JSON.stringify({ name, description, entrypoint: entry, source_code: source, visibility, requirements: values }) });
        finish(result.strategy);
      } else {
        let alias = createdFamily || family;
        if (newFamily && !createdFamily) {
          await request("/api/factor-library/families/custom", { method: "POST", body: JSON.stringify({ name, source_code: source }) });
          setCreatedFamily(name); alias = name;
        }
        const result = await request(`/api/factor-library/configurations/${encodeURIComponent(alias)}/factors`, { method: "POST", body: JSON.stringify({ params: values, mode: "create" }) });
        const factor = result.factor || result.factors?.[0];
        if (!factor?.ref && !factor?.factor_ref) throw new Error(t("editor.missingIdentity"));
        // Resolve the exact registered version; no browser identity reconstruction.
        const detail = await request(`/api/factor-library/factors/detail?factor_ref=${encodeURIComponent(factor.ref || factor.factor_ref)}`);
        finish(detail.factor);
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(false); }
  };
  const content = <div className="tr-library-create">{(!mobile || strategy) ? <div className="tr-inline-editor-heading">{strategy ? <h2>{t("strategyDetail.edit")}</h2> : null}<Button onClick={onCancel}>{t("configuration.cancel")}</Button></div> : null}
    {error ? <Alert type="error" message={error} showIcon /> : null}
    <Form layout="vertical" requiredMark={false}>
      {kind === "factor" ? <><Form.Item label={t("editor.newFamily")}><Switch checked={newFamily} disabled={!!createdFamily} onChange={setNewFamily} /></Form.Item>
        {!newFamily ? <Form.Item label={t("catalog.families")}><Select aria-label={t("catalog.families")} showSearch optionFilterProp="label" value={family || undefined} options={families.map((row) => ({ value: String(row.factor_family_alias || row.name || ""), label: String(row.factor_family_name || row.factor_family_alias || row.name) }))} onChange={setFamily} /></Form.Item> : null}</> : null}
      {kind === "strategy" || newFamily ? <><Form.Item label={t("editor.name")}><Input aria-label={t("editor.name")} value={name} disabled={!!createdFamily} onChange={(event) => setName(event.target.value)} /></Form.Item>
        {kind === "strategy" ? <Form.Item label={t("editor.entrypoint")}><Input aria-label={t("editor.entrypoint")} value={entry} onChange={(event) => setEntry(event.target.value)} /></Form.Item> : null}
        <Form.Item label={t("editor.source")}><Input.TextArea aria-label={t("editor.source")} className="tr-source-input" autoSize={{ minRows: 10 }} value={source} disabled={!!createdFamily} onChange={(event) => setSource(event.target.value)} /></Form.Item></> : null}
      {kind === "strategy" ? <><Form.Item label={t("library.description")}><Input.TextArea aria-label={t("library.description")} value={description} onChange={(event) => setDescription(event.target.value)} /></Form.Item><Form.Item label={t("library.visibility")}><Select aria-label={t("library.visibility")} value={visibility} onChange={setVisibility} options={["private", "shared", "public"].map((value) => ({ value, label: t(`strategyDetail.visibility.${value}`) }))} /></Form.Item></> : null}
      <Form.Item label={t(kind === "strategy" ? "editor.requirements" : "editor.parameters")}><Input.TextArea aria-label={t("editor.parameters")} className="tr-source-input" autoSize={{ minRows: 5 }} value={params} onChange={(event) => setParams(event.target.value)} /></Form.Item>
      <Button type="primary" loading={busy} disabled={kind === "strategy" ? !name || !source : newFamily ? !name || !source : !family} onClick={() => void save()}>{t("configuration.save")}</Button>
    </Form>
  </div>;
  return mobile && !strategy ? <DetailsPanel title={t(kind === "factor" ? "editor.newFactor" : "editor.newStrategy")} onClose={onCancel}>{content}</DetailsPanel> : content;
}
