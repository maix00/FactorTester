import React, { useEffect, useState } from "react";
import { Alert, Button, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { AccountActions } from "./account-actions.tsx";
import { ResultView } from "./result-view.tsx";
import { LanguageSwitch } from "./language-switch.tsx";
import { useAuth } from "../auth.tsx";

export const SETTINGS_SECTIONS = [
  { id: "account", icon: "account" },
  { id: "server", icon: "catalog" },
  { id: "federation", icon: "workspace" },
  { id: "controlDatabase", icon: "runs" },
  { id: "devices", icon: "trading" },
  { id: "quota", icon: "research" },
  { id: "workspace", icon: "workspace" },
  { id: "language", icon: "research" },
  { id: "updates", icon: "runs" },
  { id: "manager", icon: "runs" },
  { id: "docs", icon: "research" },
  { id: "profiles", icon: "account" },
  { id: "mihomo", icon: "runs" },
] as const;

export type SettingsSectionID=typeof SETTINGS_SECTIONS[number]["id"];
export function visibleSettingsSections(manager:boolean){return SETTINGS_SECTIONS.filter(item=>!["manager","mihomo"].includes(item.id)||manager);}

export function SettingsSection({section,onResetLayout}:{section:SettingsSectionID;onResetLayout?:()=>void}):React.ReactElement{
 const {t}=useTranslation();const {session}=useAuth();
 const [error,setError]=useState("");const [reload,setReload]=useState(0);
  const [serverInfo, setServerInfo] = useState<Record<string, unknown> | null>(null);
  const [sectionData, setSectionData] = useState<Record<string, unknown> | null>(null);
  const [docPage, setDocPage] = useState<string>("");
  const [docContent, setDocContent] = useState<string>("");
  const [profileID, setProfileID] = useState<string>("");
  const [profileData, setProfileData] = useState<Record<string, unknown> | null>(null);
  useEffect(() => {
    const controller=new AbortController();setError("");setSectionData(null);
    const endpoints: Record<string, string> = {
      controlDatabase: "/api/control-database/config",
      manager: "/api/worktrees",
      docs: "/api/docs/index",
      profiles: "/api/client/profiles",
      mihomo: "/api/admin/mihomo",
      federation: "/api/federation/config",
      devices: "/api/devices",
      quota: "/api/jobs/storage",
      updates: "/api/client/releases/beta.json",
    };
    const endpoint = endpoints[section];
    if (!endpoint) { setSectionData(null); return; }
    fetch(endpoint, { credentials: "same-origin", signal:controller.signal })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
      .then((value) => {if(!controller.signal.aborted)setSectionData(value);})
      .catch(reason => {if(!controller.signal.aborted)setError(reason.message);});
    return ()=>controller.abort();
  }, [section,reload]);

  useEffect(() => {
    const controller=new AbortController();
    if (section !== "profiles" || !profileID) { setProfileData(null); return; }
    fetch(`/api/client/profiles/${encodeURIComponent(profileID)}`, { credentials: "same-origin", signal:controller.signal })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
      .then((value) => {if(!controller.signal.aborted)setProfileData(value);})
      .catch(reason => {if(!controller.signal.aborted)setError(reason.message);});
    return ()=>controller.abort();
  }, [section,profileID,reload]);

  useEffect(() => {
    const controller=new AbortController();
    if (section !== "docs" || !docPage) { setDocContent(""); return; }
    fetch(`/api/docs/pages/${encodeURIComponent(docPage)}`, { credentials: "same-origin", signal:controller.signal })
      .then((response) => response.ok ? response.text() : Promise.reject(new Error(`HTTP ${response.status}`)))
      .then((value) => {if(!controller.signal.aborted)setDocContent(value);})
      .catch(reason => {if(!controller.signal.aborted)setError(reason.message);});
    return ()=>controller.abort();
  }, [section,docPage,reload]);

  useEffect(() => {
    const controller=new AbortController();
    if (section !== "server") return;
    fetch("/api/server/network-info", { credentials: "same-origin", signal:controller.signal })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
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
              {serverInfo ? <ResultView value={serverInfo} /> : <Spin tip={t("loading")}/>}
            </div>
          ) : section === "profiles" ? (
            <div className="tr-settings-card">
              {sectionData ? (
                <div className="tr-doc-pages">
                  {((sectionData.profiles ?? sectionData.items ?? []) as Record<string, unknown>[]).map((profile, index) => {
                    const id = String(profile.profile_id ?? profile.id ?? index);
                    return <button key={id} type="button" className={profileID === id ? "is-active" : ""} onClick={() => setProfileID(id)}>{String(profile.name ?? profile.title ?? id)}</button>;
                  })}
                </div>
              ) : <Spin tip={t("loading")}/>}
              {profileID ? <ResultView value={profileData} /> : null}
            </div>
          ) : section === "docs" ? (
            <div className="tr-settings-card">
              {sectionData ? (
                <div className="tr-doc-pages">
                  {((sectionData.pages ?? sectionData.items ?? []) as Record<string, unknown>[]).map((doc, index) => {
                    const slug = String(doc.slug ?? doc.path ?? doc.id ?? index);
                    return <button key={slug} type="button" className={docPage === slug ? "is-active" : ""} onClick={() => setDocPage(slug)}>{String(doc.title ?? doc.name ?? slug)}</button>;
                  })}
                </div>
              ) : <Spin tip={t("loading")}/>}
              {docPage ? <pre className="tr-job-detail">{docContent || t("loading")}</pre> : null}
            </div>
          ) : ["controlDatabase", "federation", "devices", "quota", "updates", "manager", "profiles", "mihomo"].includes(section) ? (
            <div className="tr-settings-card">
              {sectionData ? <ResultView value={sectionData} /> : <Spin tip={t("loading")}/>}
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
