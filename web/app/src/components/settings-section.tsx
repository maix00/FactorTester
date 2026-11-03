import React, { useEffect, useState } from "react";
import { Alert, Button, ConfigProvider, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { ProfileSettings } from "./profile-settings.tsx";
import { DeviceSettings } from "./device-settings.tsx";
import { SettingsFields } from "./settings-fields.tsx";
import { ClientDownloads } from "./client-downloads.tsx";
import { AccountSummary } from "./account-summary.tsx";
import { ResultView } from "./result-view.tsx";
import { LanguageSwitch } from "./language-switch.tsx";
import { AppearanceSettings } from "./appearance-settings.tsx";
import { QuotaSummary } from "./quota-summary.tsx";
import { ServerSummary } from "./server-summary.tsx";
import { ManagerConnectionSettings, nativeManagerSettingsAvailable } from "./manager-connection-settings.tsx";
import "./manager-connection-settings.css";
import { request } from "../configuration/api.ts";
import { useAuth } from "../auth.tsx";

import { ADMIN_SETTINGS_SECTIONS, visibleSettingsSections, type SettingsSectionID } from "../settings-model.ts";

type SettingsSectionProps={section:SettingsSectionID;onResetLayout?:()=>void;adminSurface?:boolean};
export function SettingsSection(props:SettingsSectionProps):React.ReactElement {
 const {session}=useAuth(),{t}=useTranslation();
 const isAdminSection=ADMIN_SETTINGS_SECTIONS.includes(props.section as typeof ADMIN_SETTINGS_SECTIONS[number]);
 const hasAdminCapability=session?.admin_capabilities?.includes("admin_console:manage")===true;
 const allowed=props.adminSurface ? isAdminSection&&hasAdminCapability : visibleSettingsSections({manager:Boolean(session?.capabilities?.manager),superAdmin:hasAdminCapability}).some(item=>item.id===props.section);
 if(!allowed)return <Alert type="info" message={t("settingsPanel.permissionRequired")} />;
 return <ConfigProvider componentSize="small"><div className="tr-settings-body"><SettingsSectionContent {...props}/></div></ConfigProvider>;
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
      quota: "/api/jobs/storage",
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
 if(error && section!=="server")return <Alert type="error" message={error} action={<Button onClick={()=>{setError("");setReload(value=>value+1);}}>{t("retry")}</Button>}/>;
 return <>          {section === "appearance" ? <AppearanceSettings /> : section === "language" ? (
            <SettingsFields items={[{key:"language",label:t("settingsPanel.language"),value:true,render:()=><LanguageSwitch compact/>}]}/>
          ) : section === "workspace" ? (
            <SettingsFields items={[{key:"layout",label:t("settingsPanel.layout"),value:true,render:()=><Button size="small" onClick={onResetLayout} disabled={!onResetLayout}>{t("resetLayout")}</Button>}]}/>
          ) : section === "server" ? (
            <>{typeof window !== "undefined" && nativeManagerSettingsAvailable(window) ? <div className="tr-settings-card tr-manager-connection"><ManagerConnectionSettings /></div> : null}<div className="tr-settings-card tr-manager-server-summary">
              {error ? <Alert type="error" message={error} action={<Button onClick={()=>{setError("");setReload(value=>value+1);}}>{t("retry")}</Button>}/> : serverInfo ? <ServerSummary data={serverInfo} /> : <Spin tip={t("loading")}/>}
            </div></>
          ) : section === "profiles" ? <ProfileSettings/> : section === "devices" ? <DeviceSettings /> : section === "updates" ? <ClientDownloads/> : ["controlDatabase", "quota", "manager", "mihomo"].includes(section) ? (
            <div className="tr-settings-card">
              {sectionData ? section === "quota" ? <QuotaSummary data={sectionData} onRefresh={() => setReload(value => value + 1)} /> : <ResultView value={sectionData} /> : <Spin tip={t("loading")}/>}
            </div>
          ) : section === "account" ? (
            <div className="tr-settings-card"><AccountSummary /></div>
          ) : (
            <div className="tr-settings-card tr-settings-migrating">
              <p>{t("settingsPanel.migrating")}</p>
            </div>
          )}</>;
}
