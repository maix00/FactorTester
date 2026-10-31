import React, { useEffect, useMemo, useRef, useState } from "react";
import { Button, Input, Popconfirm, Segmented, Select, Tag } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { ObjectReference } from "./object-reference.tsx";
import { request } from "../configuration/api.ts";
import { notify } from "../notifications/core.ts";
import { devicePlatform, DEVICE_PLATFORMS, type DevicePlatform } from "../device-platform.ts";
import { deviceAuthorizationState } from "../device-authorization.ts";
import { DetailsPanel } from "./details-panel.tsx";
import { PropertyGroups } from "./property-groups.tsx";
import { TRDataTable } from "./data-table.tsx";

type Device = Record<string, any>;
type DirectoryUser = { username: string; alias?: string; organization_name?: string; level_id?: string };

export function DeviceSettings({ scope = "self" }: { scope?: "self" | "admin" }): React.ReactElement {
  const { t } = useTranslation();
  const [devices, setDevices] = useState<Device[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [platform, setPlatform] = useState<DevicePlatform>("all");
  const [username, setUsername] = useState("");
  const [directoryUsers, setDirectoryUsers] = useState<DirectoryUser[]>([]);
  const [directoryQuery, setDirectoryQuery] = useState("");
  const [directoryLoading, setDirectoryLoading] = useState(false);
  const [directoryError, setDirectoryError] = useState("");
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(20);
  const [revision, setRevision] = useState(0);
  const [pending, setPending] = useState("");
  const [selectedID, setSelectedID] = useState("");
  const mutation = useRef<AbortController | null>(null);

  useEffect(() => () => mutation.current?.abort(), []);
  useEffect(() => {
    if (scope !== "admin") {
      setDirectoryUsers([]);
      setDirectoryError("");
      setDirectoryLoading(false);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setDirectoryLoading(true);
      setDirectoryError("");
      const params = new URLSearchParams({ limit: "100", query: directoryQuery });
      void request(`/api/admin/users?${params.toString()}`, { signal: controller.signal })
        .then(data => {
          if (!controller.signal.aborted) setDirectoryUsers(data.users || []);
        })
        .catch(reason => {
          if (!controller.signal.aborted) setDirectoryError(reason.message);
        })
        .finally(() => {
          if (!controller.signal.aborted) setDirectoryLoading(false);
        });
    }, directoryQuery ? 250 : 0);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [directoryQuery, scope, revision]);

  useEffect(() => {
    if (scope === "admin" && !username) {
      setDevices([]);
      setLoading(false);
      setError("");
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError("");
    const endpoint = scope === "admin"
      ? `/api/admin/devices?username=${encodeURIComponent(username)}`
      : "/api/devices";
    void request(endpoint, { signal: controller.signal }).then(data => {
      if (controller.signal.aborted) return;
      setDevices(data.devices || []);
    }).catch(reason => {
      if (!controller.signal.aborted) setError(reason.message);
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [revision, scope, username]);
  useEffect(() => {
    if (error) notify({code:`${scope}.devices.load.failed`,type:"error",message:error});
  }, [error, scope]);
  useEffect(() => {
    if (directoryError) notify({code:"admin.devices.directory.failed",type:"error",message:t("adminFunctions.directoryLoadFailed"),description:directoryError});
  }, [directoryError, t]);

  const filtered = useMemo(() => {
    const text = query.trim().toLocaleLowerCase();
    return devices.filter(device => {
      const matchesPlatform = platform === "all" || devicePlatform(device) === platform;
      const matchesUser = scope !== "admin" || !username || device.username === username;
      const matchesText = !text || [
        device.username, device.device_name, device.device_id, device.client_name, device.client_type,
        device.enrollment_ip, device.last_seen_ip,
      ].some(value => String(value || "").toLocaleLowerCase().includes(text));
      return matchesUser && matchesPlatform && matchesText;
    });
  }, [devices, platform, query, scope, username]);

  const revoke = async (device: Device): Promise<void> => {
    if (loading || mutation.current || !device.enabled || !device.device_id) return;
    const controller = new AbortController();
    mutation.current = controller;
    setPending(device.device_id);
    try {
      const data = await request(scope === "admin" ? "/api/admin/devices/revoke" : "/api/devices/revoke", {
        method: "POST", signal: controller.signal,
        body: JSON.stringify({
          device_id: device.device_id,
          ...(scope === "admin" ? { username } : {}),
        }),
      });
      if (controller.signal.aborted) return;
      if (data.device) setDevices(current => current.map(row => row.device_id === device.device_id ? data.device : row));
      notify({ code: `${scope}.devices.revoked`, type: "success", message: t("devices.revokedNotice") });
      setRevision(value => value + 1);
    } catch (reason) {
      if (!controller.signal.aborted) notify({
        code: `${scope}.devices.revoke.failed`, type: "error", message: t("devices.revokeFailed"),
        description: (reason as Error).message,
      });
    } finally {
      if (mutation.current === controller) mutation.current = null;
      if (!controller.signal.aborted) setPending("");
    }
  };

  const selected = devices.find(device => device.device_id === selectedID);
  const currentPage = Math.min(page, Math.max(1, Math.ceil(filtered.length / size)));
  const options = DEVICE_PLATFORMS.map(value => ({
    value,
    label: t(`devices.filters.${value}`),
  }));
  const userOptions = useMemo(() => {
    const rows = [...directoryUsers];
    if (username && !rows.some(user => user.username === username)) {
      rows.unshift({ username, alias: username });
    }
    return rows.map(user => ({
      value: user.username,
      label: <span>{user.alias || user.username}<small className="tr-device-user-meta">
        {user.organization_name || user.level_id || user.username}
      </small></span>,
      searchText: `${user.username} ${user.alias || ""} ${user.organization_name || ""}`.toLocaleLowerCase(),
    }));
  }, [directoryUsers, username]);

  return <section className="tr-device-settings" aria-label={t("settingsPanel.sections.devices")}>
    <div className="tr-device-controls">
      <Input.Search allowClear aria-label={t(scope === "admin" ? "adminFunctions.searchDevices" : "devices.search")}
        placeholder={t(scope === "admin" ? "adminFunctions.searchDevices" : "devices.search")}
        value={query} onChange={event => { setQuery(event.target.value); setPage(1); }} />
      {scope === "admin" ? <Select
        aria-label={t("adminFunctions.filterUser")}
        showSearch allowClear filterOption={(input, option) =>
          String(option?.searchText || "").includes(input.toLocaleLowerCase())
        }
        placeholder={t("adminFunctions.filterUser")}
        value={username || undefined}
        searchValue={directoryQuery}
        onSearch={setDirectoryQuery}
        onChange={value => { setUsername(value || ""); setPage(1); }}
        loading={directoryLoading}
        options={userOptions}
        notFoundContent={directoryLoading ? t("loading") : t("adminFunctions.noUsersInScope")}
        style={{ minWidth: 260, flex: "1 1 280px" }} /> : null}
      <Button icon={<ReloadOutlined />} aria-label={t("configuration.reload")}
        onClick={() => setRevision(value => value + 1)} disabled={!!pending} />
    </div>
    <div className="tr-device-filter-row" role="group" aria-label={t("devices.platform")}>
      <Segmented<DevicePlatform> options={options} value={platform}
        onChange={value => { setPlatform(value); setPage(1); }} />
      <span className="tr-device-count">{t("total", { count: filtered.length })}</span>
    </div>
    <TRDataTable rows={filtered} rowKey="device_id" loading={loading} empty={t("devices.empty")}
      pagination={{ page: currentPage, pageSize: size, total: filtered.length, hideOnSinglePage: true,
        onChange: (value, pageSize) => { setPage(value); setSize(pageSize); } }}
      columns={[
        ...(scope === "admin" ? [{ key: "username", title: t("adminFunctions.user"), render: (_: unknown, device: Device) => device.username ? <ObjectReference value={{kind:"user",ref:device.username}} /> : "—" }] : []),
        { key: "name", title: t("devices.name"), render: (_, device) => <div>
          <button className="tr-table-link" onClick={() => setSelectedID(device.device_id)}>{device.device_name || device.device_id}</button>
          <small className="tr-job-mobile-meta">{device.device_id}</small>
        </div> },
        { key: "client", title: t("devices.client"), render: (_, device) => {
          const platformName = t(`devices.platforms.${devicePlatform(device)}`);
          const clientName = device.client_name || t(`devices.clients.${device.client_type}`, { defaultValue: device.client_type || "" });
          return <div className="tr-device-client"><Tag>{platformName}</Tag>{clientName && clientName !== platformName ? <span>{clientName}</span> : null}</div>;
        } },
        { dataIndex: "enrollment_ip", title: t("devices.enrollmentIP"), responsive: ["md"] },
        { dataIndex: "last_seen_ip", title: t("devices.lastIP"), responsive: ["md"] },
        { key: "state", title: t("jobs.status"), render: (_, device) => { const status=deviceAuthorizationState(device,scope); return <Tag color={status === "active" ? "green" : status === "authorizationDenied" ? "orange" : "default"}>{t(`devices.${status}`)}</Tag>; } },
        { key: "revoke", title: t("devices.action"), render: (_, device) => device.enabled ?
          <Popconfirm title={t("devices.revokeConfirm")} description={device.device_name || device.device_id}
            onConfirm={() => revoke(device)} okText={t("devices.revoke")} cancelText={t("configuration.cancel")}>
            <Button danger size="small" loading={pending === device.device_id} disabled={loading || !!pending}>{t("devices.revoke")}</Button>
          </Popconfirm> : null },
      ]} />
    {selected ? <DetailsPanel title={selected.device_name || selected.device_id} onClose={() => setSelectedID("")} width={640}>
      <PropertyGroups groups={[{ key: "device", title: t("devices.name"), items: [
        { key: "id", label: t("devices.identity"), value: selected.device_id },
        { key: "client", label: t("devices.client"), value: <>{t(`devices.platforms.${devicePlatform(selected)}`)} · {selected.client_name || selected.client_type}</> },
        { key: "enrollment", label: t("devices.enrollmentIP"), value: selected.enrollment_ip },
        { key: "last", label: t("devices.lastIP"), value: selected.last_seen_ip },
        { key: "fingerprint", label: t("devices.fingerprint"), value: selected.public_key_fingerprint },
        { key: "source", label: t("devices.source"), value: selected.source_server_id },
        { key: "state", label: t("jobs.status"), value: t(`devices.${deviceAuthorizationState(selected,scope)}`) },
      ] }]} />
    </DetailsPanel> : null}
  </section>;
}
