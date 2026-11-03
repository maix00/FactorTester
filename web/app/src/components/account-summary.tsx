import React from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "../auth.tsx";
import { AccountActions } from "./account-actions.tsx";
import { ObjectReference } from "./object-reference.tsx";
import { PropertyGroups, type PropertyItem } from "./property-groups.tsx";

/** The same account fields and controls in settings and restored account pages. */
export function AccountSummary(): React.ReactElement {
  const { t } = useTranslation();
  const { session } = useAuth();
  const items: PropertyItem[] = [
    { key: "principal", label: t("settingsPanel.accountSession"), value: session?.username || t("settingsPanel.notSignedIn"),
      render: () => session?.username ? <ObjectReference value={{ kind: "user", ref: session.username }} /> : t("settingsPanel.notSignedIn") },
    { key: "role", label: t("settingsPanel.role"), value: session?.role ? t(`auth.roles.${session.role}`, { defaultValue: session.role }) : "—" },
    { key: "actions", label: t("settingsPanel.accountAction"), value: true, render: () => <AccountActions size="small" /> },
  ];
  const reported = Array.isArray(session?.admin_capabilities) || Array.isArray(session?.keycloak_roles);
  const grants = [...new Set([
    ...(Array.isArray(session?.keycloak_roles) ? session.keycloak_roles.filter(value => typeof value === "string" && value) : []),
    ...(Array.isArray(session?.admin_capabilities) ? session.admin_capabilities.filter(value => typeof value === "string" && value) : []),
    ...(session?.public_server_login === true ? ["public_server:login"] : []),
  ])].sort();
  const permissionItems: PropertyItem[] = grants.length ? grants.map(permission => ({
    key: permission,
    label: t(`accountPermissions.labels.${permission}`, { nsSeparator: false, defaultValue: permission }),
    value: t("accountPermissions.granted"),
  })) : [{ key: "administrative", label: t("accountPermissions.administrative"),
    value: t(reported ? "accountPermissions.none" : "accountPermissions.unreported") }];
  return <PropertyGroups controls groups={[
    { key: "account", title: t("settingsPanel.sections.account"), items },
    { key: "permissions", title: t("accountPermissions.title"), items: permissionItems },
  ]} />;
}
