import React from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "../auth.tsx";

export function AccountPage(): React.ReactElement {
  const { t } = useTranslation();
  const { session, logout } = useAuth();
  return (
    <div className="tr-account-page">
      <h1>{t("nav.account")}</h1>
      <p>TradeResearch</p>
      <div className="tr-account-card">
        <div><span>{t("settingsPanel.accountSession")}</span><b>{session?.username || t("settingsPanel.notSignedIn")}</b></div>
        <div><span>{t("settingsPanel.role")}</span><b>{session?.role || "—"}</b></div>
        {session?.capabilities?.manager ? <div><span>Manager</span><b>{t("available")}</b></div> : null}
        <div><span>{t("settingsPanel.accountAction")}</span><button type="button" className="tr-settings-action" onClick={() => { void logout(); }}>{t("settingsPanel.signOut")}</button></div>
      </div>
    </div>
  );
}
