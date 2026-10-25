import React from "react";
import { useTranslation } from "react-i18next";
import i18n, { persistLanguage } from "../i18n.ts";

export function MobileSettingsPage(): React.ReactElement {
  const { t } = useTranslation();
  return (
    <section className="tr-mobile-workspace">
      <header>
        <h1>{t("settingsPanel.title")}</h1>
        <p>{t("settingsPanel.sections.language")}</p>
      </header>
      <div className="tr-mobile-settings-card">
        <div>
          <b>{t("settingsPanel.language")}</b>
          <small>{t("settingsPanel.languageHint")}</small>
        </div>
        <select
          className="tr-mobile-language"
          aria-label={t("settingsPanel.language")}
          value={i18n.language.startsWith("en") ? "en" : "zh"}
          onChange={(event) => {
            const language = event.target.value === "en" ? "en" : "zh";
            i18n.changeLanguage(language);
            persistLanguage(language);
          }}
        >
          <option value="zh">中文</option>
          <option value="en">English</option>
        </select>
      </div>
    </section>
  );
}
