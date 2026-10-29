import React, { useEffect, useMemo, useState } from "react";
import { Alert, Button, Card, Descriptions, Spin, Tabs, Tag } from "antd";
import { ExportOutlined, ReloadOutlined, SafetyCertificateOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { useAuth } from "../auth.tsx";
import { DeviceSettings } from "../components/device-settings.tsx";
import { AdminFederationSettings } from "../components/admin-federation-settings.tsx";
import { FunctionPage } from "../components/function-page.tsx";
import { SettingsSection } from "../components/settings-section.tsx";
import { request } from "../configuration/api.ts";

type Directory = {
  identity_provider?: string;
  managed_externally?: boolean;
  message?: string;
  admin_scope?: "realm" | "organization";
  admin_console_url?: string;
};

type IdentityArea = "organizations" | "users";

function safeAdminURL(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) return "";
  try {
    const url = new URL(value, window.location.href);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : "";
  } catch {
    return "";
  }
}

export function AdminFunctionsPage(): React.ReactElement {
  const { t } = useTranslation();
  const { session } = useAuth();
  const [tab, setTab] = useState("organizations");
  const [directory, setDirectory] = useState<Directory | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const isSuperAdmin = session?.admin_capabilities?.includes("admin_console:manage") === true;
  const isFederationAdmin = session?.admin_capabilities?.includes("federation:manage") === true;
  const isAdmin = isSuperAdmin || isFederationAdmin;

  const visibleTabs = useMemo(() => isSuperAdmin ? [
    "organizations", "users", "devices", "mihomo", "federation", "controlDatabase", "manager",
  ] : isFederationAdmin ? ["organizations", "users", "federation"] : [], [isFederationAdmin, isSuperAdmin]);

  useEffect(() => {
    if (!isAdmin || (tab !== "organizations" && tab !== "users")) return;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    void request("/api/admin/account-directory", { signal: controller.signal })
      .then((value) => { if (!controller.signal.aborted) setDirectory(value as Directory); })
      .catch((reason) => { if (!controller.signal.aborted) setError(reason.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [isAdmin, revision, tab]);

  useEffect(() => {
    if (visibleTabs.length && !visibleTabs.includes(tab)) setTab(visibleTabs[0]);
  }, [tab, visibleTabs]);

  const adminURL = useMemo(() => safeAdminURL(directory?.admin_console_url), [directory?.admin_console_url]);

  if (!isAdmin) {
    return <FunctionPage title={t("adminFunctions.title")}>
      <Alert type="error" showIcon message={t("adminFunctions.permissionRequired")} />
    </FunctionPage>;
  }

  const identityContent = (area: IdentityArea): React.ReactNode => {
    if (loading) return <Spin tip={t("loading")} />;
    if (error) return <Alert type="error" showIcon message={t("adminFunctions.loadFailed")} description={error}
      action={<Button icon={<ReloadOutlined />} onClick={() => setRevision(value => value + 1)}>{t("retry")}</Button>} />;
    if (directory?.identity_provider !== "keycloak") return <Alert type="warning" showIcon
      message={t("adminFunctions.keycloakUnavailable")}
      description={directory?.message || t("adminFunctions.keycloakUnavailableHint")} />;
    const isOrganizations = area === "organizations";
    return <div className="tr-admin-identity">
      <Alert type="info" showIcon
        message={t(isOrganizations ? "adminFunctions.organizationNotice" : "adminFunctions.userNotice")}
        description={t(isOrganizations ? "adminFunctions.organizationHint" : "adminFunctions.userHint")} />
      {!isSuperAdmin ? <Alert className="tr-admin-scope-notice" type="warning" showIcon
        message={t("adminFunctions.scopedKeycloakNotice")}
        description={t("adminFunctions.keycloakScopedAdministrationHint")} /> : null}
      <Card className="tr-admin-provider" bordered>
        <div className="tr-admin-provider-mark"><SafetyCertificateOutlined /></div>
        <div className="tr-admin-provider-copy">
          <div className="tr-admin-provider-title">
            <h2>{t(isOrganizations ? "adminFunctions.organizations" : "adminFunctions.users")}</h2>
            <Tag color="blue">Keycloak</Tag>
          </div>
          <p>{t(isOrganizations ? "adminFunctions.organizationDescription" : "adminFunctions.userDescription")}</p>
        </div>
        <Button type="primary" icon={<ExportOutlined />} href={adminURL || undefined}
          target="_blank" rel="noopener noreferrer" disabled={!adminURL}>
          {t(!isSuperAdmin ? "adminFunctions.manageOrganizationMembers"
            : isOrganizations ? "adminFunctions.manageOrganizations" : "adminFunctions.manageUsers")}
        </Button>
      </Card>
      <Descriptions size="small" column={{ xs: 1, sm: 2 }} items={[
        { key: "identity", label: t("adminFunctions.identitySource"), children: "Keycloak" },
        { key: "permissions", label: t("adminFunctions.permissionsSource"), children: "Keycloak" },
        { key: "local", label: t("adminFunctions.localCopy"), children: t("adminFunctions.noLocalCopy") },
      ]} />
    </div>;
  };

  const allTabs = [
    { key: "organizations", label: t("adminFunctions.organizations"), children: tab === "organizations" ? identityContent("organizations") : null },
    { key: "users", label: t("adminFunctions.users"), children: tab === "users" ? identityContent("users") : null },
    { key: "devices", label: t("adminFunctions.devices"), children: tab === "devices" ? <DeviceSettings scope="admin" /> : null },
    { key: "mihomo", label: "Mihomo", children: tab === "mihomo" ? <SettingsSection section="mihomo" adminSurface /> : null },
    { key: "federation", label: t("adminFunctions.federation"), children: tab === "federation" ? <AdminFederationSettings /> : null },
    { key: "controlDatabase", label: t("adminFunctions.controlDatabase"), children: tab === "controlDatabase" ? <SettingsSection section="controlDatabase" adminSurface /> : null },
    { key: "manager", label: t("adminFunctions.runtime"), children: tab === "manager" ? <SettingsSection section="manager" adminSurface /> : null },
  ];
  const tabItems = allTabs.filter(item => visibleTabs.includes(item.key));

  return <FunctionPage title={t("adminFunctions.title")}>
    <div className="tr-admin-tab">
      <Tabs aria-label={t("adminFunctions.title")} activeKey={tab} onChange={setTab} items={tabItems} />
    </div>
  </FunctionPage>;
}
