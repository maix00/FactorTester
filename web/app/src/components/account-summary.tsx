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
    { key: "actions", label: t("settingsPanel.accountAction"), value: true, render: () => <AccountActions /> },
  ];
  if (session?.capabilities?.manager) items.push({ key: "manager", label: "Manager", value: t("available") });
  return <PropertyGroups density="comfortable" groups={[{ key: "account", title: t("settingsPanel.sections.account"), items }]} />;
}
