import React, { useEffect, useMemo, useState } from "react";
import { Alert, Button, Card, Form, Input, Space, Spin, Switch, Tag } from "antd";
import { ReloadOutlined, SaveOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { notify } from "../notifications/core.ts";
import { request } from "../configuration/api.ts";
import { TRDataTable } from "./data-table.tsx";

type OrganizationPolicy = {
  group_path: string;
  organization_id?: string;
  name: string;
  server_id?: string;
  server_online?: boolean;
  sync_allowed?: boolean;
  sync_enabled?: boolean;
  configured: boolean;
};

type FederationSettings = {
  server: { server_id: string; public_server: boolean; role: string };
  connection: {
    bootstrap_url: string;
    enabled: boolean;
    active: boolean;
    registration_token_configured: boolean;
  };
  policy_mode: "destination_allow" | "source_opt_in";
  organizations: OrganizationPolicy[];
  identity_sync_transport: "not_connected" | "connected";
  can_manage_all: boolean;
  can_edit_connection: boolean;
};

export function AdminFederationSettings(): React.ReactElement {
  const { t } = useTranslation();
  const [value, setValue] = useState<FederationSettings | null>(null);
  const [bootstrapURL, setBootstrapURL] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [pending, setPending] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    void request("/api/admin/federation/settings", { signal: controller.signal })
      .then((result: FederationSettings) => {
        if (controller.signal.aborted) return;
        setValue(result);
        setBootstrapURL(result.connection?.bootstrap_url || "");
      })
      .catch((reason: Error) => {
        if (!controller.signal.aborted) setError(reason.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [revision]);

  const isPublic = value?.server.public_server === true;
  const organizationRows = useMemo(() => value?.organizations || [], [value]);

  const updatePolicy = async (row: OrganizationPolicy, enabled: boolean): Promise<void> => {
    if (!value || pending) return;
    setPending(row.group_path);
    const field = value.policy_mode === "destination_allow" ? "allowed" : "enabled";
    try {
      await request("/api/admin/federation/settings", {
        method: "PUT",
        body: JSON.stringify({ group_path: row.group_path, [field]: enabled }),
      });
      setValue(current => current ? {
        ...current,
        organizations: current.organizations.map(item => item.group_path === row.group_path
          ? { ...item, ...(field === "allowed" ? { sync_allowed: enabled } : { sync_enabled: enabled }) }
          : item),
      } : current);
      notify({
        code: `admin.federation.policy:${row.group_path}`,
        type: "success",
        message: t("adminFunctions.federationPolicySaved"),
      });
    } catch (reason) {
      notify({
        code: `admin.federation.policy.failed:${row.group_path}`,
        type: "error",
        message: t("adminFunctions.federationPolicySaveFailed"),
        description: (reason as Error).message,
      });
      setRevision(current => current + 1);
    } finally {
      setPending("");
    }
  };

  const saveConnection = async (): Promise<void> => {
    if (!value || pending) return;
    setPending("connection");
    try {
      const result = await request("/api/admin/federation/settings", {
        method: "PUT",
        body: JSON.stringify({ bootstrap_url: bootstrapURL.trim() }),
      });
      setValue(current => current ? {
        ...current,
        connection: { ...current.connection, ...result.connection },
      } : current);
      notify({
        code: "admin.federation.connection.saved",
        type: "success",
        message: t("adminFunctions.federationAddressSaved"),
      });
    } catch (reason) {
      notify({
        code: "admin.federation.connection.failed",
        type: "error",
        message: t("adminFunctions.federationAddressSaveFailed"),
        description: (reason as Error).message,
      });
    } finally {
      setPending("");
    }
  };

  if (loading && !value) return <div className="tr-admin-federation-loading"><Spin tip={t("loading")} /></div>;
  if (error && !value) return <Alert type="error" showIcon message={t("adminFunctions.federationLoadFailed")}
    description={error} action={<Button icon={<ReloadOutlined />} onClick={() => setRevision(n => n + 1)}>{t("retry")}</Button>} />;
  if (!value) return <Alert type="warning" showIcon message={t("adminFunctions.federationUnavailable")} />;

  const policyLabel = value.policy_mode === "destination_allow"
    ? t("adminFunctions.allowOrganizationSync")
    : t("adminFunctions.enableOrganizationSync");

  return <section className="tr-admin-federation" aria-label={t("adminFunctions.federation")}>
    {error ? <Alert type="error" showIcon message={error} /> : null}
    <Alert
      type={value.identity_sync_transport === "connected" ? "success" : "warning"}
      showIcon
      message={t(value.identity_sync_transport === "connected"
        ? "adminFunctions.identitySyncConnected"
        : "adminFunctions.identitySyncPolicyOnly")}
      description={t(value.identity_sync_transport === "connected"
        ? "adminFunctions.identitySyncConnectedHint"
        : "adminFunctions.identitySyncPolicyOnlyHint")}
    />

    {!isPublic && value.can_edit_connection ? <Card className="tr-admin-federation-card" title={t("adminFunctions.publicManagerConnection")}>
      <p className="tr-admin-federation-help">{t("adminFunctions.publicManagerConnectionHint")}</p>
      <Form layout="vertical" onFinish={() => void saveConnection()}>
        <Form.Item label={t("adminFunctions.publicManagerAddress")}>
          <Input value={bootstrapURL} onChange={event => setBootstrapURL(event.target.value)}
            placeholder="http://10.x.x.x:17998/api/federation/register" autoComplete="url" />
        </Form.Item>
        <Space wrap>
          <Button type="primary" htmlType="submit" icon={<SaveOutlined />}
            loading={pending === "connection"} disabled={!!pending}>{t("save")}</Button>
          <Tag color={value.connection.active ? "green" : value.connection.enabled ? "blue" : "default"}>
            {t(value.connection.active ? "adminFunctions.connectionOnline" : value.connection.enabled
              ? "adminFunctions.connectionConfigured" : "adminFunctions.connectionNotConfigured")}
          </Tag>
        </Space>
      </Form>
    </Card> : null}

    <Card className="tr-admin-federation-card" title={policyLabel}
      extra={<Button icon={<ReloadOutlined />} aria-label={t("configuration.reload")}
        disabled={!!pending} onClick={() => setRevision(n => n + 1)} />}>
      <p className="tr-admin-federation-help">{t(isPublic
        ? "adminFunctions.destinationSyncPolicyHint"
        : "adminFunctions.sourceSyncPolicyHint")}</p>
      <TRDataTable<OrganizationPolicy>
        rows={organizationRows}
        rowKey="group_path"
        loading={loading}
        empty={t("adminFunctions.noFederationOrganizations")}
        pagination={{ page: 1, pageSize: Math.max(20, organizationRows.length), total: organizationRows.length,
          hideOnSinglePage: true, onChange: () => undefined }}
        columns={[
          { key: "organization", title: t("adminFunctions.organization"), render: (_, row) => <div className="tr-admin-federation-org">
            <strong>{row.name}</strong>
            {row.organization_id ? <small>{row.organization_id}</small> : null}
          </div> },
          ...(isPublic ? [{ key: "server", title: t("adminFunctions.organizationServer"), render: (_: unknown, row: OrganizationPolicy) => <div>
            <div>{row.server_id || "—"}</div>
            <Tag color={row.server_online ? "green" : "default"}>{t(row.server_online ? "adminFunctions.serverOnline" : "adminFunctions.serverOffline")}</Tag>
          </div> }] : []),
          { key: "policy", title: policyLabel, render: (_, row) => {
            const checked = value.policy_mode === "destination_allow" ? row.sync_allowed === true : row.sync_enabled === true;
            return <Switch checked={checked} disabled={!row.configured || !!pending}
              loading={pending === row.group_path} aria-label={`${policyLabel}: ${row.name}`}
              onChange={enabled => void updatePolicy(row, enabled)} />;
          } },
        ]}
      />
    </Card>
  </section>;
}
