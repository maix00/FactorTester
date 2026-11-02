import React from "react";
import { Select } from "antd";
import { useTranslation } from "react-i18next";
import { useAppearance } from "./app-theme.tsx";
import { DeviceOrientationSettings, orientationHandler } from "./device-orientation-settings.tsx";

export function AppearanceSettings(): React.ReactElement {
  const {t} = useTranslation();
  const {mode, setMode} = useAppearance();
  return <div className="tr-settings-card tr-appearance-settings">
    <div className="tr-settings-row"><b>{t("appearance.theme")}</b>
      <Select aria-label={t("appearance.theme")} className="tr-appearance-select" popupClassName="tr-appearance-dropdown" popupMatchSelectWidth={false}
        value={mode} onChange={setMode} options={(["light", "dark", "system"] as const).map(value => ({value, label:t(`appearance.${value}`)}))} />
    </div>
    {orientationHandler() && <DeviceOrientationSettings />}
  </div>;
}
