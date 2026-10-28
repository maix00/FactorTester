import React, { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Input, Popconfirm, Tag } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { notify } from "../notifications/core.ts";
import { DetailsPanel } from "./details-panel.tsx";
import { PropertyGroups } from "./property-groups.tsx";
import { TRDataTable } from "./data-table.tsx";

type Device = Record<string, any>;
export function DeviceSettings(): React.ReactElement {
  const { t } = useTranslation();
  const [devices, setDevices] = useState<Device[]>([]), [loading, setLoading] = useState(true), [error, setError] = useState("");
  const [query, setQuery] = useState(""), [page, setPage] = useState(1), [size, setSize] = useState(20), [revision, setRevision] = useState(0);
  const [pending, setPending] = useState("");
  const [selectedID, setSelectedID] = useState("");
  const mutation = useRef<AbortController | null>(null);
  useEffect(() => () => mutation.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError("");
    void request("/api/devices", { signal: controller.signal }).then(data => {
      if (!controller.signal.aborted) setDevices(data.devices || []);
    }).catch(reason => { if (!controller.signal.aborted) setError(reason.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [revision]);
  const filtered = useMemo(() => {
    const text = query.trim().toLocaleLowerCase();
    return devices.filter(device => !text || [device.device_name, device.device_id, device.client_name, device.client_type, device.enrollment_ip, device.last_seen_ip].some(value => String(value || "").toLocaleLowerCase().includes(text)));
  }, [devices, query]);
  const revoke = async (device: Device): Promise<void> => {
    if (loading || mutation.current || !device.enabled || !device.device_id) return;
    const controller = new AbortController(); mutation.current = controller; setPending(device.device_id);
    try {
      const data = await request("/api/devices/revoke", { method: "POST", signal: controller.signal, body: JSON.stringify({ device_id: device.device_id }) });
      if (controller.signal.aborted) return;
      if (data.device) setDevices(current => current.map(row => row.device_id === device.device_id ? data.device : row));
      notify({ code: "devices.revoked", type: "success", message: t("devices.revokedNotice") });
      setRevision(value => value + 1);
    } catch (reason) {
      if (!controller.signal.aborted) notify({ code: "devices.revoke.failed", type: "error", message: t("devices.revokeFailed"), description: (reason as Error).message });
    } finally {
      if (mutation.current === controller) mutation.current = null;
      if (!controller.signal.aborted) setPending("");
    }
  };
  const selected=devices.find(device=>device.device_id===selectedID);
  const currentPage = Math.min(page, Math.max(1, Math.ceil(filtered.length / size)));
  return <section aria-label={t("settingsPanel.sections.devices")}>
    <p className="tr-settings-description">{t("devices.hint")}</p>
    <div className="tr-library-filters"><Input.Search allowClear aria-label={t("devices.search")} placeholder={t("devices.search")} value={query} onChange={event => { setQuery(event.target.value); setPage(1); }} />
      <Button icon={<ReloadOutlined />} aria-label={t("configuration.reload")} onClick={() => setRevision(value => value + 1)} disabled={!!pending} /></div>
    {error ? <Alert type="error" showIcon message={error} action={<Button onClick={() => setRevision(value => value + 1)}>{t("retry")}</Button>} /> : null}
    <TRDataTable rows={filtered} rowKey="device_id" loading={loading} empty={t("devices.empty")} pagination={{ page: currentPage, pageSize: size, total: filtered.length, hideOnSinglePage: true, onChange: (value, size) => { setPage(value); setSize(size); } }} columns={[
      { key: "name", title: t("devices.name"), render: (_, device) => <div><button className="tr-table-link" onClick={() => setSelectedID(device.device_id)}>{device.device_name || device.device_id}</button><small className="tr-job-mobile-meta">{device.device_id}</small></div> },
      { key: "client", title: t("devices.client"), render: (_, device) => device.client_name || t(`devices.clients.${device.client_type}`, { defaultValue: device.client_type || "—" }) },
      { dataIndex: "enrollment_ip", title: t("devices.enrollmentIP"), responsive: ["md"] },
      { dataIndex: "last_seen_ip", title: t("devices.lastIP"), responsive: ["md"] },
      { key: "state", title: t("jobs.status"), render: (_, device) => <Tag color={device.enabled ? "green" : "default"}>{t(device.enabled ? "devices.active" : "devices.revoked")}</Tag> },
      { key: "revoke", title: t("devices.action"), render: (_, device) => device.enabled ? <Popconfirm title={t("devices.revokeConfirm")} description={device.device_name || device.device_id} onConfirm={() => revoke(device)} okText={t("devices.revoke")} cancelText={t("configuration.cancel")}><Button danger size="small" loading={pending === device.device_id} disabled={loading || !!pending}>{t("devices.revoke")}</Button></Popconfirm> : null },
    ]} />
    {selected ? <DetailsPanel title={selected.device_name || selected.device_id} onClose={()=>setSelectedID("")} width={640}><PropertyGroups groups={[{key:"device",title:t("devices.name"),items:[
      {key:"id",label:t("devices.identity"),value:selected.device_id},
      {key:"client",label:t("devices.client"),value:selected.client_name || selected.client_type},
      {key:"enrollment",label:t("devices.enrollmentIP"),value:selected.enrollment_ip},
      {key:"last",label:t("devices.lastIP"),value:selected.last_seen_ip},
      {key:"fingerprint",label:t("devices.fingerprint"),value:selected.public_key_fingerprint},
      {key:"source",label:t("devices.source"),value:selected.source_server_id},
      {key:"state",label:t("jobs.status"),value:t(selected.enabled?"devices.active":"devices.revoked")},
    ]}]}/></DetailsPanel> : null}
  </section>;
}
