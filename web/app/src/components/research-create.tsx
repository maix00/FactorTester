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
  const visibility = Form.useWatch("visibility", form) || "private";
  const profileRef = Form.useWatch("profile_ref", form);
  const authorizedUsers = Form.useWatch("authorized_users", form) || [];
  const [profiles, setProfiles] = useState<Row[]>([]), [principals, setPrincipals] = useState<Row[]>([]);
  const [authority, setAuthority] = useState<"keycloak" | "legacy" | null>(null);
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false);
  const [principalQuery, setPrincipalQuery] = useState(""), [principalLoading, setPrincipalLoading] = useState(false), [principalError, setPrincipalError] = useState("");
  const [lookupError, setLookupError] = useState(""), [retry, setRetry] = useState(0);
  const saving = useRef(false), mutation = useRef<AbortController | null>(null);
  useEffect(() => () => mutation.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setLookupError("");
    const capability = researchAuthority(controller.signal,t("researchDetail.invalidResponse"));
    void Promise.all([request("/api/client/profiles", { signal: controller.signal }), capability]).then(([profiles,value]) => {
      if (controller.signal.aborted) return;
      if (value.authority === "keycloak" && value.create_research !== true) throw new Error(t("researchSharing.unavailable"));
      setProfiles(profiles.profiles || []); setAuthority(value.authority);
    }).catch(reason => { if (!controller.signal.aborted) setLookupError(reason.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [retry,t]);
  useEffect(() => {
    if (authority !== "legacy" || visibility !== "authorized") return;
    const controller = new AbortController(); setPrincipalLoading(true); setPrincipalError("");
    const timer = setTimeout(() => {
      void request(`/api/research/principals?q=${encodeURIComponent(principalQuery.trim())}`, { signal: controller.signal })
        .then(data => { if (!controller.signal.aborted) setPrincipals(data.principals || []); })
        .catch(reason => { if (!controller.signal.aborted) setPrincipalError(reason.message); })
        .finally(() => { if (!controller.signal.aborted) setPrincipalLoading(false); });
    }, 250);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [authority, visibility, principalQuery, retry]);
  const save = async (values: Row): Promise<void> => {
    if (saving.current || !authority) return;
    saving.current = true; setBusy(true);
    const controller = new AbortController(); mutation.current = controller;
    try {
      const data = await request(authority === "keycloak" ? "/api/research/keycloak-create" : "/api/research", { method: "POST", signal: controller.signal, body: JSON.stringify({
        title: values.title.trim(), description: values.description?.trim() || "", profile_ref: values.profile_ref || "",
        visibility: authority === "keycloak" ? "private" : values.visibility, authorized_users: authority === "legacy" && values.visibility === "authorized" ? values.authorized_users || [] : [],
      }) });
      if (!controller.signal.aborted) onCreated(data.research);
    } catch (reason) { if (!controller.signal.aborted) notify({code:"research.create.failed",type:"error",message:t("researchDetail.operationFailed"),description:(reason as Error).message}); }
    finally { saving.current = false; if (!controller.signal.aborted) setBusy(false); }
  };
  return <DetailsPanel title={t("research.create")} onClose={onClose} width={600}>
    {lookupError ? <Alert type="error" showIcon message={lookupError} action={<Button onClick={() => setRetry(value => value + 1)}>{t("retry")}</Button>} /> : null}
    {principalError && authority === "legacy" && visibility === "authorized" ? <Alert type="error" showIcon message={principalError} action={<Button onClick={() => setRetry(value => value + 1)}>{t("retry")}</Button>} /> : null}
    <Form form={form} layout="vertical" initialValues={{ visibility: "private", authorized_users: [] }} disabled={busy} onFinish={save}>
      <Form.Item name="title" label={t("editor.name")} rules={[{ required: true, whitespace: true }]}><Input aria-label={t("editor.name")} autoFocus maxLength={500} /></Form.Item>
      <Form.Item name="description" label={t("library.description")}><Input.TextArea aria-label={t("library.description")} autoSize={{ minRows: 3, maxRows: 8 }} /></Form.Item>
      <Form.Item label={t("research.profile")}><div className="tr-reference-select"><Form.Item name="profile_ref" noStyle><Select aria-label={t("research.profile")} allowClear showSearch optionFilterProp="label" loading={loading} placeholder={t("research.noProfile")} options={profiles.map(item => ({ value: item.profile_id, label: item.display_name || item.profile_id }))} /></Form.Item>{profileRef ? <ObjectReference icon value={{kind:"profile",ref:String(profileRef),profileKey:profiles.find(item => item.profile_id === profileRef)?.profile_key,label:profiles.find(item => item.profile_id === profileRef)?.display_name || String(profileRef)}} /> : null}</div></Form.Item>
      {authority === "legacy" ? <><Form.Item name="visibility" label={t("library.visibility")}><Select aria-label={t("library.visibility")} options={["private", "superiors", "authorized", "public"].map(value => ({ value, label: t(`research.visibility.${value}`) }))} /></Form.Item>
      {visibility === "authorized" ? <Form.Item name="authorized_users" label={t("research.authorizedUsers")} rules={[{ required: true, type: "array", min: 1 }]}><Select aria-label={t("research.authorizedUsers")} mode="multiple" showSearch filterOption={false} onSearch={setPrincipalQuery} loading={principalLoading} placeholder={t("research.searchUsers")} options={principals.map(item => ({ value: item.principal_ref, label: item.label || item.principal_ref }))} /></Form.Item> : null}
      {visibility === "authorized" && authorizedUsers.length ? <div className="tr-reference-chip-list">{authorizedUsers.map((ref: string) => <ObjectReference key={ref} value={{kind:"user",ref,label:principals.find(item => item.principal_ref === ref)?.label || ref}} />)}</div> : null}</> : authority === "keycloak" ? <p className="tr-research-sharing-note">{t("researchSharing.privateOnCreate")}</p> : null}
      <Space><Button aria-label={t("research.create")} type="primary" htmlType="submit" loading={busy} disabled={loading || !authority || !!lookupError || authority === "legacy" && visibility === "authorized" && (principalLoading || !!principalError)}>{t("research.create")}</Button><Button onClick={onClose}>{t("configuration.cancel")}</Button></Space>
    </Form>
  </DetailsPanel>;
}
