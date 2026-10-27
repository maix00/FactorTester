import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import i18n, { persistLanguage } from "../i18n.ts";
import { PageIcon } from "../icon.tsx";

const SECTIONS = ["account", "workspace", "language", "server", "devices", "updates"] as const;
export type MobileSettingSection = typeof SECTIONS[number];

export function MobileSettingsPage({ onOpen }: { onOpen: (section: MobileSettingSection) => void }): React.ReactElement {
  const { t } = useTranslation();
  return (
    <section className="tr-mobile-workspace">
      <header>
        <h1>{t("settingsPanel.title")}</h1>
        <p>{t("settingsPanel.mobileHint")}</p>
      </header>
      <div className="tr-mobile-open-list">
        {SECTIONS.map((section) => (
          <button key={section} type="button" className="tr-mobile-open-row" onClick={() => onOpen(section)}>
            <span className="tr-mobile-open-icon"><PageIcon name={section === "language" ? "research" : section === "account" ? "account" : "catalog"} /></span>
            <span>{t(`settingsPanel.sections.${section}`)}</span>
            <span className="tr-mobile-open-route">›</span>
          </button>
        ))}
      </div>
    </section>
  );
}

export function MobileSettingDetail({ section, onBack }: { section: MobileSettingSection; onBack: () => void }): React.ReactElement {
  const { t } = useTranslation();
  const [session, setSession] = useState<{ username?: string; role?: string } | null>(null);
  useEffect(() => {
    if (section !== "account") return;
    fetch("/api/session", { credentials: "same-origin" })
      .then((response) => response.ok ? response.json() : null)
      .then((value) => setSession(value?.session ?? value ?? null))
      .catch(() => undefined);
  }, [section]);
  return (
    <div className="tr-mobile-settings-detail">
      <header className="tr-mobile-page-header">
        <button type="button" className="tr-mobile-back" aria-label={t("back")} onClick={onBack}>
          <PageIcon name="back" />
        </button>
        <strong>{t(`settingsPanel.sections.${section}`)}</strong>
      </header>
      <div className="tr-mobile-settings-body">
        {section === "language" ? (
          <div className="tr-mobile-settings-card">
            <div>
              <b>{t("settingsPanel.language")}</b>
              
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
        ) : section === "account" ? (
          <div className="tr-mobile-settings-card tr-mobile-settings-stack">
            <div><b>{t("settingsPanel.accountSession")}</b><small>{session?.username || t("settingsPanel.notSignedIn")}</small></div>
            <div><b>{t("settingsPanel.role")}</b><small>{session?.role || "—"}</small></div>
          </div>
        ) : (
          <div className="tr-mobile-settings-card"><p>{t("settingsPanel.migrating")}</p></div>
        )}
      </div>
    </div>
  );
}
