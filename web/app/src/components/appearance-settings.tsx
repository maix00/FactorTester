import React from "react";
import { Select } from "antd";
import { useTranslation } from "react-i18next";
import { SettingsFields } from "./settings-fields.tsx";
import { useAppearance } from "./app-theme.tsx";
import { DeviceOrientationSettings, orientationHandler } from "./device-orientation-settings.tsx";

export function AppearanceSettings(): React.ReactElement {
  const {t} = useTranslation();
  const {mode, setMode} = useAppearance();
  return <div className="tr-settings-card tr-appearance-settings"><SettingsFields items={[
    { key:"theme",label:t("appearance.theme"),value:true,render:()=>
      <Select size="small" aria-label={t("appearance.theme")} className="tr-appearance-select" popupClassName="tr-appearance-dropdown" popupMatchSelectWidth={false}
        value={mode} onChange={setMode} options={(["light", "dark", "system"] as const).map(value => ({value, label:t(`appearance.${value}`)}))} /> },
    ...(orientationHandler() ? [{key:"orientation",label:t("deviceOrientation.title"),value:true,render:()=><DeviceOrientationSettings/>}] : []),
  ]}/></div>;
}
