import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

type Session = { username?: string; role?: string; capabilities?: Record<string, boolean> } | null;

export function AccountPage(): React.ReactElement {
  const { t } = useTranslation();
  const [session, setSession] = useState<Session>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    fetch("/api/session", { credentials: "same-origin" })
      .then((response) => response.ok ? response.json() : null)
      .then((value) => setSession(value?.session ?? value ?? null))
      .catch(() => setFailed(true));
  }, []);
  if (failed) return <div className="tr-account-page"><h1>{t("nav.account")}</h1><p>{t("loadFailed")}</p></div>;
  return (
    <div className="tr-account-page">
      <h1>{t("nav.account")}</h1>
      <p>TradeResearch</p>
      <div className="tr-account-card">
        <div><span>{t("settingsPanel.accountSession")}</span><b>{session?.username || t("settingsPanel.notSignedIn")}</b></div>
        <div><span>{t("settingsPanel.role")}</span><b>{session?.role || "—"}</b></div>
        {session?.capabilities?.manager ? <div><span>Manager</span><b>{t("available")}</b></div> : null}
      </div>
    </div>
  );
}
