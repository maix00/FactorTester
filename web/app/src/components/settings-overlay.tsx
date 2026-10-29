import React, { useState } from "react";
import { Modal } from "antd";
import { useTranslation } from "react-i18next";
import { PageIcon } from "../icon.tsx";
import { useAuth } from "../auth.tsx";
import { SettingsSection } from "./settings-section.tsx";
import { visibleSettingsSections, type SettingsSectionID } from "../settings-model.ts";
export function SettingsOverlay({open,onClose,onResetLayout}:{open:boolean;onClose:()=>void;onResetLayout:()=>void}):React.ReactElement{
 const {t}=useTranslation(),{session}=useAuth();const [section,setSection]=useState<SettingsSectionID>("account");
 const sections=visibleSettingsSections({manager:Boolean(session?.capabilities?.manager),superAdmin:session?.role==="super_admin",canManagePermissions:session?.admin_capabilities?.includes("admin_console:manage")});
 const current=sections.find(item=>item.id===section)||sections[0];
 return <Modal open={open} onCancel={onClose} footer={null} centered width={820} className="tr-settings-overlay" destroyOnHidden title={t("settingsPanel.title")}>
 <div className="tr-settings-hub"><nav className="tr-settings-nav" aria-label={t("settingsPanel.title")}>
 {sections.map(item=><button key={item.id} type="button" className={current.id===item.id?"is-active":""} aria-current={current.id===item.id?"page":undefined} onClick={()=>setSection(item.id)}><PageIcon name={item.icon}/><span>{t(`settingsPanel.sections.${item.id}`)}</span></button>)}
 </nav><section className="tr-settings-content"><header className="tr-settings-page-header"><span className="tr-settings-page-icon"><PageIcon name={current.icon}/></span><h2>{t(`settingsPanel.sections.${current.id}`)}</h2></header>
 {open?<SettingsSection key={current.id} section={current.id} onResetLayout={onResetLayout}/>:null}</section></div></Modal>;
}
