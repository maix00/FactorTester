import React, { useEffect, useState } from "react";
import { Alert, Button, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { DocsSettings } from "./docs-settings.tsx";
import { ProfileSettings } from "./profile-settings.tsx";
import { DeviceSettings } from "./device-settings.tsx";
import { AccountActions } from "./account-actions.tsx";
import { ResultView } from "./result-view.tsx";
import { LanguageSwitch } from "./language-switch.tsx";
import { QuotaSummary } from "./quota-summary.tsx";
import { ServerSummary } from "./server-summary.tsx";
import { PermissionsSettings } from "./permissions-settings.tsx";
import { request } from "../configuration/api.ts";
import { useAuth } from "../auth.tsx";

import { visibleSettingsSections, type SettingsSectionID } from "../settings-model.ts";

type SettingsSectionProps={section:SettingsSectionID;onResetLayout?:()=>void};
export function SettingsSection(props:SettingsSectionProps):React.ReactElement {
 const {session}=useAuth(),{t}=useTranslation();
 const allowed=visibleSettingsSections({manager:Boolean(session?.capabilities?.manager),superAdmin:session?.role==="super_admin",canManagePermissions:session?.admin_capabilities?.includes("admin_console:manage")});
 if(!allowed.some(item=>item.id===props.section))return <Alert type="info" message={t("settingsPanel.permissionRequired")} />;
 return <SettingsSectionContent {...props}/>;
}
function SettingsSectionContent({section,onResetLayout}:SettingsSectionProps):React.ReactElement{
 const {t}=useTranslation();const {session}=useAuth();
 const [error,setError]=useState("");const [reload,setReload]=useState(0);
  const [serverInfo, setServerInfo] = useState<Record<string, unknown> | null>(null);
  const [sectionData, setSectionData] = useState<Record<string, unknown> | null>(null);
  useEffect(() => {
    const controller=new AbortController();setError("");setSectionData(null);
    const endpoints: Record<string, string> = {
      controlDatabase: "/api/control-database/config",
      manager: "/api/worktrees",
      mihomo: "/api/admin/mihomo",
      federation: "/api/federation/config",
      quota: "/api/jobs/storage",
      updates: "/api/client/releases/beta.json",
    };
    const endpoint = endpoints[section];
    if (!endpoint) { setSectionData(null); return; }
    request(endpoint, { signal: controller.signal })
      .then((value) => {if(!controller.signal.aborted)setSectionData(value);})
      .catch(reason => {if(!controller.signal.aborted)setError(reason.message);});
    return ()=>controller.abort();
  }, [section,reload]);

  useEffect(() => {
    const controller=new AbortController();
    if (section !== "server") return;
    setServerInfo(null);
    request("/api/server/network-info", { signal: controller.signal })
      .then((value) => {if(!controller.signal.aborted)setServerInfo(value);})
      .catch(reason => {if(!controller.signal.aborted)setError(reason.message);});
    return ()=>controller.abort();
  }, [section,reload]);
 if(error)return <Alert type="error" message={error} action={<Button onClick={()=>{setError("");setReload(value=>value+1);}}>{t("retry")}</Button>}/>;
 return <>          {section === "language" ? (
            <div className="tr-settings-card">
              <div className="tr-settings-row">
                <div><b>{t("settingsPanel.language")}</b></div>
                <LanguageSwitch />
              </div>
            </div>
          ) : section === "workspace" ? (
            <div className="tr-settings-card">
              <div className="tr-settings-row">
                <div><b>{t("settingsPanel.layout")}</b></div>
                <button type="button" className="tr-toolbar-button" onClick={onResetLayout} disabled={!onResetLayout}>{t("resetLayout")}</button>
              </div>
            </div>
          ) : section === "server" ? (
            <div className="tr-settings-card">
              {serverInfo ? <ServerSummary data={serverInfo} /> : <Spin tip={t("loading")}/>}
            </div>
          ) : section === "profiles" ? <ProfileSettings/> : section === "docs" ? <DocsSettings/> : section === "devices" ? <DeviceSettings /> : section === "permissions" ? <PermissionsSettings/> : ["controlDatabase", "federation", "quota", "updates", "manager", "mihomo"].includes(section) ? (
            <div className="tr-settings-card">
              {sectionData ? section === "quota" ? <QuotaSummary data={sectionData} onRefresh={() => setReload(value => value + 1)} /> : <ResultView value={sectionData} /> : <Spin tip={t("loading")}/>}
            </div>
          ) : section === "account" ? (
            <div className="tr-settings-card">
              <div className="tr-settings-row">
                <div><b>{t("settingsPanel.accountSession")}</b></div>
                <span className="tr-settings-value">{session?.username || t("settingsPanel.notSignedIn")}</span>
              </div>
              <div className="tr-settings-row">
                <div><b>{t("settingsPanel.role")}</b></div>
                <span className="tr-settings-value">{session?.role || "—"}</span>
              </div>
              <div className="tr-settings-row">
                <div><b>{t("settingsPanel.accountAction")}</b></div>
                <AccountActions/>
              </div>
            </div>
          ) : (
            <div className="tr-settings-card tr-settings-migrating">
              <p>{t("settingsPanel.migrating")}</p>
            </div>
          )}</>;
}
