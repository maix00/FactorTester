import React from "react";
import { useTranslation } from "react-i18next";
import { AccountActions } from "../components/account-actions.tsx";
import { useAuth } from "../auth.tsx";
import { ObjectReference } from "../components/object-reference.tsx";

export function AccountPage(): React.ReactElement {
  const { t } = useTranslation();
  const { session } = useAuth();
  return (
    <div className="tr-account-page">
      <h1>{t("nav.account")}</h1>
      <div className="tr-account-card">
        <div><span>{t("settingsPanel.accountSession")}</span><b>{session?.username ? <ObjectReference value={{kind:"user",ref:session.username}}/> : t("settingsPanel.notSignedIn")}</b></div>
        <div><span>{t("settingsPanel.role")}</span><b>{session?.role ? t(`auth.roles.${session.role}`, {defaultValue:session.role}) : "—"}</b></div>
        {session?.capabilities?.manager ? <div><span>Manager</span><b>{t("available")}</b></div> : null}
        <div><span>{t("settingsPanel.accountAction")}</span><AccountActions/></div>
      </div>
    </div>
  );
}
