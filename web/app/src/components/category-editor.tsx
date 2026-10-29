import React, { useState } from "react";
import { Alert, Button, Form, Input } from "antd";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { DetailsPanel } from "./details-panel.tsx";
import { useCompactLayout } from "../configuration/layout.ts";

type Category = Record<string, any>;

export function CategoryEditor({ category, onSaved, onDeleted, onCancel }: {
  category?: Category | null;
  onSaved: (value: Category) => void;
  onDeleted: () => void;
  onCancel: () => void;
}): React.ReactElement {
  const { t } = useTranslation();
  const mobile = useCompactLayout();
  const editing = Boolean(category?.id);
  const items = Array.isArray(category?.items) ? category.items as Category[] : [];
  const pathsEditable = !editing || (items.length <= 1 && !items.some((item) => item.label_generated));
  const [name, setName] = useState(String(category?.alias || category?.title_zh || category?.name || ""));
  const [paths, setPaths] = useState(items.flatMap((item) => item.paths || []).map((value) => String(value)).join("\n"));
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState("");
  const save = async (): Promise<void> => {
    setBusy(true); setError("");
    try {
      if (!name.trim()) throw new Error(t("category.requiredName"));
      const body: Record<string, unknown> = { name: name.trim() };
      if (pathsEditable) {
        const values = paths.split("\n").map((value) => value.trim()).filter(Boolean);
        if (!values.length) throw new Error(t("category.required"));
        const label = editing ? String(items[0]?.label || name.trim()) : name.trim();
        body.items = [{ label, paths: values }];
      }
      const result = await request(
        editing ? `/api/product-library/categories/${encodeURIComponent(String(category!.id))}` : "/api/product-library/categories",
        { method: editing ? "PUT" : "POST", body: JSON.stringify(body) },
      );
      onSaved(result.category || result);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally { setBusy(false); }
  };
  const remove = async (): Promise<void> => {
    setBusy(true); setError("");
    try {
      await request(`/api/product-library/categories/${encodeURIComponent(String(category?.id))}`, { method: "DELETE" });
      onDeleted();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally { setBusy(false); setConfirming(false); }
  };
  const content = <div className="tr-library-create">
    {editing ? <div className="tr-inline-editor-heading"><h2>{t("category.edit")}</h2></div> : null}
    {error ? <Alert type="error" message={error} showIcon /> : null}
    <Form layout="vertical" requiredMark={false}>
      <Form.Item label={t("category.name")}><Input aria-label={t("category.name")} value={name} onChange={(event) => setName(event.target.value)} /></Form.Item>
      {pathsEditable ? <Form.Item label={t("category.paths")} help={t("category.pathsHint")}><Input.TextArea aria-label={t("category.paths")} className="tr-source-input" autoSize={{ minRows: 6 }} value={paths} onChange={(event) => setPaths(event.target.value)} /></Form.Item> : <Alert type="info" showIcon message={t("category.pathsComplex")} />}
      {confirming ? <Alert type="warning" showIcon message={t("category.deleteTitle")} description={t("category.deleteHint")} action={<div className="tr-inline-actions"><Button danger loading={busy} onClick={() => void remove()}>{t("category.deleteConfirm")}</Button><Button onClick={() => setConfirming(false)}>{t("configuration.cancel")}</Button></div>} /> : null}
      <div className="tr-inline-actions"><Button type="primary" loading={busy} onClick={() => void save()}>{t("configuration.save")}</Button><Button disabled={busy} onClick={onCancel}>{t("configuration.cancel")}</Button>{editing && !confirming ? <Button danger loading={busy} onClick={() => setConfirming(true)}>{t("category.delete")}</Button> : null}</div>
    </Form>
  </div>;
  return mobile && !editing ? <DetailsPanel title={t("category.create")} onClose={onCancel}>{content}</DetailsPanel> : content;
}
