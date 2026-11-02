import React, { useRef, useState } from "react";
import { Alert, Button, Form, Input, Popconfirm } from "antd";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { DetailsCancelButton, DetailsPanel } from "./details-panel.tsx";
import { useCompactLayout } from "../configuration/layout.ts";
import { notify } from "../notifications/core.ts";

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
  const [error, setError] = useState("");
  const mutation = useRef(false);
  const save = async (): Promise<void> => {
    if (mutation.current) return;
    if (!name.trim()) { setError(t("category.requiredName")); return; }
    const values = paths.split("\n").map(value => value.trim()).filter(Boolean);
    if (pathsEditable && !values.length) { setError(t("category.required")); return; }
    mutation.current = true;
    setBusy(true); setError("");
    try {
      const body: Record<string, unknown> = { name: name.trim() };
      if (pathsEditable) {
        const label = editing ? String(items[0]?.label || name.trim()) : name.trim();
        body.items = [{ label, paths: values }];
      }
      const result = await request(
        editing ? `/api/product-library/categories/${encodeURIComponent(String(category!.id))}` : "/api/product-library/categories",
        { method: editing ? "PUT" : "POST", body: JSON.stringify(body) },
      );
      notify({code:"category.save.success",type:"success",message:t("operations.saved")}); onSaved(result.category || result);
    } catch (reason) {
      notify({code:"category.save.failed",type:"error",message:t("operations.saveFailed"),description:reason instanceof Error ? reason.message : String(reason)});
    } finally { mutation.current = false; setBusy(false); }
  };
  const remove = async (): Promise<void> => {
    if (mutation.current) return;
    mutation.current = true;
    setBusy(true); setError("");
    try {
      await request(`/api/product-library/categories/${encodeURIComponent(String(category?.id))}`, { method: "DELETE" });
      notify({code:"category.delete.success",type:"success",message:t("operations.deleted")}); onDeleted();
    } catch (reason) {
      notify({code:"category.delete.failed",type:"error",message:t("operations.deleteFailed"),description:reason instanceof Error ? reason.message : String(reason)});
    } finally { mutation.current = false; setBusy(false); }
  };
  const content = <div className="tr-library-create">
    {editing ? <div className="tr-inline-editor-heading"><h2>{t("category.edit")}</h2></div> : null}
    {error ? <Alert type="error" message={error} showIcon /> : null}
    <Form layout="vertical" requiredMark={false}>
      <Form.Item label={t("category.name")}><Input aria-label={t("category.name")} value={name} onChange={(event) => setName(event.target.value)} /></Form.Item>
      {pathsEditable ? <Form.Item label={t("category.paths")} help={t("category.pathsHint")}><Input.TextArea aria-label={t("category.paths")} className="tr-source-input" autoSize={{ minRows: 6 }} value={paths} onChange={(event) => setPaths(event.target.value)} /></Form.Item> : <Alert type="info" showIcon message={t("category.pathsComplex")} />}
      <div className="tr-inline-actions"><Button type="primary" loading={busy} onClick={() => void save()}>{t("configuration.save")}</Button><DetailsCancelButton disabled={busy} closePanel={mobile && !editing} onCancel={onCancel}/>{editing ? <Popconfirm title={t("category.deleteTitle")} description={t("category.deleteHint")} onConfirm={() => void remove()} okText={t("category.deleteConfirm")} cancelText={t("configuration.cancel")}><Button danger loading={busy}>{t("category.delete")}</Button></Popconfirm> : null}</div>
    </Form>
  </div>;
  return mobile && !editing ? <DetailsPanel title={t("category.create")} onClose={onCancel}>{content}</DetailsPanel> : content;
}
