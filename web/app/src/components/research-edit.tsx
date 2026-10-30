import React, { useRef, useState } from "react";
import { Alert, Button, Form, Input, Popconfirm } from "antd";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { notify } from "../notifications/core.ts";

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
  const [error, setError] = useState("");
  const mutation = useRef(false);
  const save = async (): Promise<void> => {
    if (!title.trim()) { setError(t("research.titleRequired")); return; }
    if (mutation.current) return;
    mutation.current = true;
    setBusy(true); setError("");
    try {
      const result = await request(`/api/research/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify({ title: title.trim(), description: description.trim() }) });
      notify({code:"research.edit.success",type:"success",message:t("researchDetail.notices.saved")});
      onSaved(result.research || result);
    } catch (reason) { notify({code:"research.edit.failed",type:"error",message:t("researchDetail.operationFailed"),description:reason instanceof Error ? reason.message : String(reason)}); }
    finally { mutation.current = false; setBusy(false); }
  };
  const archive = async (): Promise<void> => {
    if (mutation.current) return;
    mutation.current = true;
    setBusy(true); setError("");
    try {
      const result = await request(`/api/research/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify({ status: "archived" }) });
      notify({code:"research.archive.success",type:"success",message:t("researchDetail.notices.archived")});
      onArchived(result.research || result);
    } catch (reason) { notify({code:"research.archive.failed",type:"error",message:t("researchDetail.operationFailed"),description:reason instanceof Error ? reason.message : String(reason)}); }
    finally { mutation.current = false; setBusy(false); }
  };
  const content = <div className="tr-library-create">
    <div className="tr-inline-editor-heading"><h2>{t("research.edit")}</h2></div>
    {error ? <Alert type="error" message={error} showIcon /> : null}
    <Form layout="vertical" requiredMark={false}>
      <Form.Item label={t("editor.name")}><Input aria-label={t("editor.name")} value={title} onChange={(event) => setTitle(event.target.value)} /></Form.Item>
      <Form.Item label={t("library.description")}><Input.TextArea aria-label={t("library.description")} autoSize={{ minRows: 4 }} value={description} onChange={(event) => setDescription(event.target.value)} /></Form.Item>
      <div className="tr-inline-actions"><Button type="primary" loading={busy} onClick={() => void save()}>{t("configuration.save")}</Button><Button disabled={busy} onClick={onCancel}>{t("configuration.cancel")}</Button><Popconfirm title={t("research.archiveTitle")} description={t("research.archiveHint")} onConfirm={() => void archive()} okText={t("research.archiveConfirm")} cancelText={t("configuration.cancel")}><Button danger loading={busy}>{t("research.archive")}</Button></Popconfirm></div>
    </Form>
  </div>;
  return content;
}
