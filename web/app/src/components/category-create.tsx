import React, { useState } from "react";
import { Alert, Button, Form, Input } from "antd";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { DetailsPanel } from "./details-panel.tsx";
import { useCompactLayout } from "../configuration/layout.ts";

export function CategoryCreate({ onCreated, onCancel }: {
  onCreated: (value: Record<string, unknown>) => void;
  onCancel: () => void;
}): React.ReactElement {
  const { t } = useTranslation();
  const mobile = useCompactLayout();
  const [name, setName] = useState("");
  const [paths, setPaths] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const save = async (): Promise<void> => {
    setBusy(true); setError("");
    try {
      const values = paths.split("\n").map((value) => value.trim()).filter(Boolean);
      if (!name.trim() || !values.length) throw new Error(t("category.required"));
      const result = await request("/api/product-library/categories", {
        method: "POST",
        body: JSON.stringify({ name: name.trim(), items: [{ label: name.trim(), paths: values }] }),
      });
      onCreated(result.category || result);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally { setBusy(false); }
  };
  const content = <div className="tr-library-create">
    {!mobile ? <div className="tr-inline-editor-heading"><h2>{t("category.create")}</h2><Button type="text" onClick={onCancel}>{t("configuration.cancel")}</Button></div> : null}
    {error ? <Alert type="error" message={error} showIcon /> : null}
    <Form layout="vertical" requiredMark={false}>
      <Form.Item label={t("category.name")}><Input aria-label={t("category.name")} value={name} onChange={(event) => setName(event.target.value)} /></Form.Item>
      <Form.Item label={t("category.paths")} help={t("category.pathsHint")}>
        <Input.TextArea aria-label={t("category.paths")} className="tr-source-input" autoSize={{ minRows: 6 }} value={paths} onChange={(event) => setPaths(event.target.value)} />
      </Form.Item>
      <Button type="primary" loading={busy} onClick={() => void save()}>{t("configuration.save")}</Button>
    </Form>
  </div>;
  return mobile ? <DetailsPanel title={t("category.create")} onClose={onCancel}>{content}</DetailsPanel> : content;
}
