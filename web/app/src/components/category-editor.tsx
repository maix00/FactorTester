import React, { useRef, useState } from "react";
import { Button, Form, Input, Popconfirm } from "antd";
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
  const composite = category?.is_composite === true;
  const [entries, setEntries] = useState<Category[]>(items.length ? items.map(item => ({...item, paths: (item.paths || []).join("\n")})) : [{label:"",paths:""}]);
  const [name, setName] = useState(String(category?.alias || category?.title_zh || category?.name || ""));
  const [busy, setBusy] = useState(false);
  const mutation = useRef(false);
  const save = async (): Promise<void> => {
    if (mutation.current) return;
    const values = entries.map(item => ({...item, label:String(item.label || "").trim(), paths:String(item.paths || "").split("\n").map(path => path.trim()).filter(Boolean)}));
    if (!name.trim() || values.some(item => !item.label || !item.paths.length) || new Set(values.map(item => item.label)).size !== values.length) {
      notify({code:"category.validation",type:"error",message:t("category.requiredEntries")}); return;
    }
    mutation.current = true;
    setBusy(true);
    try {
      const body = {name:name.trim(), items:values};
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
    setBusy(true);
    try {
      await request(`/api/product-library/categories/${encodeURIComponent(String(category?.id))}`, { method: "DELETE" });
      notify({code:"category.delete.success",type:"success",message:t("operations.deleted")}); onDeleted();
    } catch (reason) {
      notify({code:"category.delete.failed",type:"error",message:t("operations.deleteFailed"),description:reason instanceof Error ? reason.message : String(reason)});
    } finally { mutation.current = false; setBusy(false); }
  };
  const content = <div className="tr-library-create">
    {editing ? <div className="tr-inline-editor-heading"><h2>{t("category.edit")}</h2></div> : null}
    <Form layout="vertical" requiredMark={false}>
      <Form.Item label={t("category.name")}><Input aria-label={t("category.name")} disabled={composite || busy} value={name} onChange={(event) => setName(event.target.value)} /></Form.Item>
      {entries.map((item,index) => <fieldset key={index} className="tr-category-entry">
        <Form.Item label={t("category.entryLabel")}><Input aria-label={`${t("category.entryLabel")} ${index+1}`} disabled={busy || item.label_generated} value={item.label} onChange={event=>setEntries(current=>current.map((row,i)=>i===index?{...row,label:event.target.value}:row))}/></Form.Item>
        <Form.Item label={t("category.paths")}><Input.TextArea aria-label={`${t("category.paths")} ${index+1}`} disabled={busy || composite || item.label_generated} autoSize={{minRows:3,maxRows:8}} value={item.paths} onChange={event=>setEntries(current=>current.map((row,i)=>i===index?{...row,paths:event.target.value}:row))}/></Form.Item>
        {!composite && !item.label_generated && entries.length>1?<Button danger type="text" disabled={busy} onClick={()=>setEntries(current=>current.filter((_,i)=>i!==index))}>{t("category.removeEntry")}</Button>:null}
      </fieldset>)}
      {!composite?<Button disabled={busy} onClick={()=>setEntries(current=>[...current,{label:"",paths:""}])}>{t("category.addEntry")}</Button>:null}
      <div className="tr-inline-actions"><Button type="primary" loading={busy} onClick={() => void save()}>{t("configuration.save")}</Button><DetailsCancelButton disabled={busy} closePanel={mobile && !editing} onCancel={onCancel}/>{editing ? <Popconfirm title={t("category.deleteTitle")} description={t("category.deleteHint")} onConfirm={() => void remove()} okText={t("category.deleteConfirm")} cancelText={t("configuration.cancel")}><Button danger loading={busy}>{t("category.delete")}</Button></Popconfirm> : null}</div>
    </Form>
  </div>;
  return mobile && !editing ? <DetailsPanel title={t("category.create")} onClose={onCancel}>{content}</DetailsPanel> : content;
}
