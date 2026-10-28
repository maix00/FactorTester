import React, { useState } from "react";
import { Modal, Select } from "antd";
import { useTranslation } from "react-i18next";
import { useCompactLayout } from "../configuration/layout.ts";
import { PageIcon } from "../icon.tsx";
import { useAuth } from "../auth.tsx";
import { SettingsSection } from "./settings-section.tsx";
import { visibleSettingsSections, type SettingsSectionID } from "../settings-model.ts";
export function SettingsOverlay({open,onClose,onResetLayout}:{open:boolean;onClose:()=>void;onResetLayout:()=>void}):React.ReactElement{
 const compact=useCompactLayout();
 const {t}=useTranslation(),{session}=useAuth();const [section,setSection]=useState<SettingsSectionID>("account");
 const sections=visibleSettingsSections({manager:Boolean(session?.capabilities?.manager),superAdmin:session?.role==="super_admin"});
 const current=sections.find(item=>item.id===section)||sections[0];
 return <Modal open={open} onCancel={onClose} footer={null} centered width={820} className="tr-settings-overlay" destroyOnHidden title={t("settingsPanel.title")}>
 <div className="tr-settings-hub">{compact?<Select className="tr-settings-section-picker" aria-label={t("settingsPanel.title")} value={current.id} onChange={setSection} options={sections.map(item=>({value:item.id,label:t(`settingsPanel.sections.${item.id}`)}))}/>:<nav className="tr-settings-nav" aria-label={t("settingsPanel.title")}>
 {sections.map(item=><button key={item.id} type="button" className={current.id===item.id?"is-active":""} onClick={()=>setSection(item.id)}><PageIcon name={item.icon}/><span>{t(`settingsPanel.sections.${item.id}`)}</span></button>)}
 </nav>}<section className="tr-settings-content"><header className="tr-settings-page-header"><span className="tr-settings-page-icon"><PageIcon name={current.icon}/></span><h2>{t(`settingsPanel.sections.${current.id}`)}</h2></header>
 {open?<SettingsSection key={current.id} section={current.id} onResetLayout={onResetLayout}/>:null}</section></div></Modal>;
}
