import React, { useEffect, useState } from "react";
import { Alert, Button, Form, Input, Select } from "antd";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { DetailsCancelButton, DetailsPanel } from "./details-panel.tsx";
import { useCompactLayout } from "../configuration/layout.ts";

type Group = Record<string, any>;

export function ProductGroupEditor({ group, onSaved, onDeleted, onCancel }: {
  group?: Group | null;
  onSaved: (value: Group) => void;
  onDeleted: () => void;
  onCancel: () => void;
}): React.ReactElement {
  const { t } = useTranslation();
  const mobile = useCompactLayout();
  const [name, setName] = useState(String(group?.name || ""));
  const [paths, setPaths] = useState((Array.isArray(group?.paths) ? group.paths : []).map((value: unknown) => String(value)).join("\n"));
  const [categories, setCategories] = useState<string[]>((Array.isArray(group?.category_ids) ? group.category_ids : []).map((value: unknown) => String(value)));
  const [categoryOptions, setCategoryOptions] = useState<{ value: string; label: string }[]>([]);
  const [categoryLoading, setCategoryLoading] = useState(true);
  const [categoryError, setCategoryError] = useState("");
  const [categoryRevision, setCategoryRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState("");
  const groupRef = String(group?.group_ref || group?.ref || "");
  useEffect(() => {
    const controller = new AbortController();
    setCategoryLoading(true); setCategoryError("");
    request("/api/product-library/categories", { signal: controller.signal })
      .then((value) => {
        if (controller.signal.aborted) return;
        if (!Array.isArray(value.categories)) throw new Error(t("productGroup.categoriesLoadFailed"));
        setCategoryOptions(value.categories.map((row: Record<string, unknown>) => ({ value: String(row.id), label: String(row.alias || row.title_zh || row.id) })));
      })
      .catch((reason) => { if (!controller.signal.aborted) setCategoryError(reason instanceof Error ? reason.message : String(reason)); })
      .finally(() => { if (!controller.signal.aborted) setCategoryLoading(false); });
    return () => controller.abort();
  }, [categoryRevision, t]);
  const remove = async (): Promise<void> => {
    setBusy(true); setError("");
    try {
      await request(`/api/product-library/product-groups/${encodeURIComponent(groupRef)}`, { method: "DELETE" });
      onDeleted();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally { setBusy(false); setConfirming(false); }
  };
  const save = async (): Promise<void> => {
    setBusy(true); setError("");
    try {
      const pathValues = paths.split("\n").map((value) => value.trim()).filter(Boolean);
      const categoryValues = categories.map((value) => value.trim()).filter(Boolean);
      if (!name.trim() || !pathValues.length) throw new Error(t("productGroup.required"));
      if (groupRef && !categoryValues.length) throw new Error(t("productGroup.categoryRequired"));
      const result = await request(
        groupRef ? `/api/product-library/product-groups/${encodeURIComponent(groupRef)}` : "/api/product-library/product-groups",
        { method: groupRef ? "PUT" : "POST", body: JSON.stringify({ name: name.trim(), paths: pathValues, category_ids: categoryValues }) },
      );
      onSaved(result.group || result);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally { setBusy(false); }
  };
  const content = <div className="tr-library-create">
    {groupRef ? <div className="tr-inline-editor-heading"><h2>{t("productGroup.edit")}</h2></div> : null}
    {error ? <Alert type="error" message={error} showIcon /> : null}
    <Form layout="vertical" requiredMark={false}>
      <Form.Item label={t("productGroup.name")}><Input aria-label={t("productGroup.name")} value={name} onChange={(event) => setName(event.target.value)} /></Form.Item>
      <Form.Item label={t("productGroup.paths")} help={t("productGroup.pathsHint")}>
        <Input.TextArea aria-label={t("productGroup.paths")} className="tr-source-input" autoSize={{ minRows: 6 }} value={paths} onChange={(event) => setPaths(event.target.value)} />
      </Form.Item>
      <Form.Item label={t("productGroup.categories")} help={t("productGroup.categoriesHint")}>
        <Select mode="multiple" showSearch optionFilterProp="label" loading={categoryLoading} disabled={categoryLoading || !!categoryError} aria-label={t("productGroup.categories")} value={categories} options={categoryOptions} onChange={setCategories} />
      </Form.Item>
      {categoryError ? <Alert type="error" showIcon message={t("productGroup.categoriesLoadFailed")} description={categoryError} action={<Button onClick={() => setCategoryRevision((value) => value + 1)}>{t("retry")}</Button>} /> : null}
      {confirming ? <Alert type="warning" showIcon message={t("productGroup.deleteTitle")} description={t("productGroup.deleteHint")} action={<div className="tr-inline-actions"><Button danger loading={busy} onClick={() => void remove()}>{t("productGroup.deleteConfirm")}</Button><Button onClick={() => setConfirming(false)}>{t("configuration.cancel")}</Button></div>} /> : null}
      <div className="tr-inline-actions"><Button type="primary" loading={busy} disabled={categoryLoading || !!categoryError} onClick={() => void save()}>{t("configuration.save")}</Button><DetailsCancelButton disabled={busy} closePanel={mobile && !groupRef} onCancel={onCancel}/>{groupRef && !confirming ? <Button danger loading={busy} onClick={() => setConfirming(true)}>{t("productGroup.delete")}</Button> : null}</div>
    </Form>
  </div>;
  return mobile && !groupRef ? <DetailsPanel title={t("productGroup.create")} onClose={onCancel}>{content}</DetailsPanel> : content;
}
