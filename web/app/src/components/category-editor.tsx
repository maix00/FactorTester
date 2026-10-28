import React, { useState } from "react";
import { Alert, Button, Form, Input, Modal } from "antd";
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
  const [name, setName] = useState(String(category?.alias || category?.title_zh || category?.name || ""));
  const [paths, setPaths] = useState((Array.isArray(category?.items) ? category.items : []).flatMap((item: Category) => item.paths || []).join("\n"));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const save = async (): Promise<void> => {
    setBusy(true); setError("");
    try {
      if (!name.trim()) throw new Error(t("category.requiredName"));
      const body: Record<string, unknown> = { name: name.trim() };
      if (!editing) {
        const values = paths.split("\n").map((value) => value.trim()).filter(Boolean);
        if (!values.length) throw new Error(t("category.required"));
        body.items = [{ label: name.trim(), paths: values }];
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
  const remove = (): void => {
    Modal.confirm({
      title: t("category.deleteTitle"),
      content: t("category.deleteHint"),
      okText: t("report.remove"),
      okButtonProps: { danger: true },
      cancelText: t("configuration.cancel"),
      onOk: async () => {
        setBusy(true); setError("");
        try {
          await request(`/api/product-library/categories/${encodeURIComponent(String(category?.id))}`, { method: "DELETE" });
          onDeleted();
        } catch (reason) {
          setError(reason instanceof Error ? reason.message : String(reason));
        } finally { setBusy(false); }
      },
    });
  };
  const content = <div className="tr-library-create">
    {!mobile ? <div className="tr-inline-editor-heading"><h2>{t(editing ? "category.edit" : "category.create")}</h2><Button type="text" onClick={onCancel}>{t("configuration.cancel")}</Button></div> : null}
    {error ? <Alert type="error" message={error} showIcon /> : null}
    <Form layout="vertical" requiredMark={false}>
      <Form.Item label={t("category.name")}><Input aria-label={t("category.name")} value={name} onChange={(event) => setName(event.target.value)} /></Form.Item>
      {!editing ? <Form.Item label={t("category.paths")} help={t("category.pathsHint")}><Input.TextArea aria-label={t("category.paths")} className="tr-source-input" autoSize={{ minRows: 6 }} value={paths} onChange={(event) => setPaths(event.target.value)} /></Form.Item> : null}
      <div className="tr-inline-actions"><Button type="primary" loading={busy} onClick={() => void save()}>{t("configuration.save")}</Button>{editing ? <Button danger loading={busy} onClick={remove}>{t("category.delete")}</Button> : null}</div>
    </Form>
  </div>;
  return mobile ? <DetailsPanel title={t(editing ? "category.edit" : "category.create")} onClose={onCancel}>{content}</DetailsPanel> : content;
}
