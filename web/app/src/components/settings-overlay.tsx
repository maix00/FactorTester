import React from "react";
import { Drawer } from "antd";
import { useTranslation } from "react-i18next";
import { LanguageSwitch } from "./language-switch.tsx";

export function SettingsOverlay({
  open, onClose, onResetLayout,
}: {
  open: boolean;
  onClose: () => void;
  onResetLayout: () => void;
}): React.ReactElement {
  const { t } = useTranslation();
  return (
    <Drawer title={t("settingsPanel.title")} placement="right" width={360} open={open} onClose={onClose}>
      <div className="tr-settings-section">
        <h3>{t("settingsPanel.language")}</h3>
        <p>{t("settingsPanel.languageHint")}</p>
        <LanguageSwitch />
      </div>
      <div className="tr-settings-section">
        <h3>{t("settingsPanel.layout")}</h3>
        <p>{t("settingsPanel.layoutHint")}</p>
        <button type="button" className="tr-toolbar-button" onClick={onResetLayout}>{t("resetLayout")}</button>
      </div>
    </Drawer>
  );
}
