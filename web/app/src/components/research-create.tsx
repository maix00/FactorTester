import React, { useEffect, useRef, useState } from "react";
import { Alert, Button, Form, Input, Select, Space } from "antd";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { researchAuthority } from "../research-authority.ts";
import { DetailsPanel } from "./details-panel.tsx";
import { ObjectReference } from "./object-reference.tsx";
import { notify } from "../notifications/core.ts";
import "./research-sharing.css";

type Row = Record<string, any>;
export function ResearchCreate({ onClose, onCreated }: { onClose: () => void; onCreated: (value: Row) => void }): React.ReactElement {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const profileRef = Form.useWatch("profile_ref", form);
  const [profiles, setProfiles] = useState<Row[]>([]);
  const [canCreate, setCanCreate] = useState(false);
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false);
  const [lookupError, setLookupError] = useState(""), [retry, setRetry] = useState(0);
  const saving = useRef(false), mutation = useRef<AbortController | null>(null);
  useEffect(() => () => mutation.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setLookupError("");
    const capability = researchAuthority(controller.signal,t("researchDetail.invalidResponse"));
    void Promise.all([request("/api/client/profiles", { signal: controller.signal }), capability]).then(([profiles,value]) => {
      if (controller.signal.aborted) return;
      if (value.create_research !== true) throw new Error(t("researchSharing.unavailable"));
      setProfiles(profiles.profiles || []); setCanCreate(true);
    }).catch(reason => { if (!controller.signal.aborted) setLookupError(reason.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [retry,t]);
  const save = async (values: Row): Promise<void> => {
    if (saving.current || !canCreate) return;
    saving.current = true; setBusy(true);
    const controller = new AbortController(); mutation.current = controller;
    try {
      const data = await request("/api/research/keycloak-create", { method: "POST", signal: controller.signal, body: JSON.stringify({
        title: values.title.trim(), description: values.description?.trim() || "", profile_ref: values.profile_ref || "",
      }) });
      if (!controller.signal.aborted) onCreated(data.research);
    } catch (reason) { if (!controller.signal.aborted) notify({code:"research.create.failed",type:"error",message:t("researchDetail.operationFailed"),description:(reason as Error).message}); }
    finally { saving.current = false; if (!controller.signal.aborted) setBusy(false); }
  };
  return <DetailsPanel title={t("research.create")} onClose={onClose} width={600}>
    {lookupError ? <Alert type="error" showIcon message={lookupError} action={<Button onClick={() => setRetry(value => value + 1)}>{t("retry")}</Button>} /> : null}
    <Form form={form} layout="vertical" disabled={busy} onFinish={save}>
      <Form.Item name="title" label={t("editor.name")} rules={[{ required: true, whitespace: true }]}><Input aria-label={t("editor.name")} autoFocus maxLength={500} /></Form.Item>
      <Form.Item name="description" label={t("library.description")}><Input.TextArea aria-label={t("library.description")} autoSize={{ minRows: 3, maxRows: 8 }} /></Form.Item>
      <Form.Item label={t("research.profile")}><div className="tr-reference-select"><Form.Item name="profile_ref" noStyle><Select aria-label={t("research.profile")} allowClear showSearch optionFilterProp="label" loading={loading} placeholder={t("research.noProfile")} options={profiles.map(item => ({ value: item.profile_id, label: item.display_name || item.profile_id }))} /></Form.Item>{profileRef ? <ObjectReference icon value={{kind:"profile",ref:String(profileRef),profileKey:profiles.find(item => item.profile_id === profileRef)?.profile_key,label:profiles.find(item => item.profile_id === profileRef)?.display_name || String(profileRef)}} /> : null}</div></Form.Item>
      <Space><Button aria-label={t("research.create")} type="primary" htmlType="submit" loading={busy} disabled={loading || !canCreate || !!lookupError}>{t("research.create")}</Button><Button onClick={onClose}>{t("configuration.cancel")}</Button></Space>
    </Form>
  </DetailsPanel>;
}
