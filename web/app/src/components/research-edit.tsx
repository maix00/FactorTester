import React, { useState } from "react";
import { Alert, Button, Form, Input } from "antd";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";

type Research = Record<string, any>;

export function ResearchEdit({ research, onSaved, onArchived, onCancel }: {
  research: Research;
  onSaved: (value: Research) => void;
  onArchived: (value: Research) => void;
  onCancel: () => void;
}): React.ReactElement {
  const { t } = useTranslation();
  const id = String(research.research_id || research.id || research.ref || "");
  const [title, setTitle] = useState(String(research.title || ""));
  const [description, setDescription] = useState(String(research.description || ""));
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState("");
  const save = async (): Promise<void> => {
    setBusy(true); setError("");
    try {
      if (!title.trim()) throw new Error(t("research.titleRequired"));
      const result = await request(`/api/research/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify({ title: title.trim(), description: description.trim() }) });
      onSaved(result.research || result);
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(false); }
  };
  const archive = async (): Promise<void> => {
    setBusy(true); setError("");
    try {
      const result = await request(`/api/research/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify({ status: "archived" }) });
      onArchived(result.research || result);
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(false); setConfirming(false); }
  };
  const content = <div className="tr-library-create">
    <div className="tr-inline-editor-heading"><h2>{t("research.edit")}</h2></div>
    {error ? <Alert type="error" message={error} showIcon /> : null}
    <Form layout="vertical" requiredMark={false}>
      <Form.Item label={t("editor.name")}><Input aria-label={t("editor.name")} value={title} onChange={(event) => setTitle(event.target.value)} /></Form.Item>
      <Form.Item label={t("library.description")}><Input.TextArea aria-label={t("library.description")} autoSize={{ minRows: 4 }} value={description} onChange={(event) => setDescription(event.target.value)} /></Form.Item>
      {confirming ? <Alert type="warning" showIcon message={t("research.archiveTitle")} description={t("research.archiveHint")} action={<div className="tr-inline-actions"><Button danger loading={busy} onClick={() => void archive()}>{t("research.archiveConfirm")}</Button><Button onClick={() => setConfirming(false)}>{t("configuration.cancel")}</Button></div>} /> : null}
      <div className="tr-inline-actions"><Button type="primary" loading={busy} onClick={() => void save()}>{t("configuration.save")}</Button><Button disabled={busy} onClick={onCancel}>{t("configuration.cancel")}</Button>{!confirming ? <Button danger loading={busy} onClick={() => setConfirming(true)}>{t("research.archive")}</Button> : null}</div>
    </Form>
  </div>;
  return content;
}
