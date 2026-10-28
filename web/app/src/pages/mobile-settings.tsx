import React from "react";
import { useTranslation } from "react-i18next";
import { SettingsSection } from "../components/settings-section.tsx";
import { visibleSettingsSections, type SettingsSectionID } from "../settings-model.ts";
import { useAuth } from "../auth.tsx";
import { PageIcon } from "../icon.tsx";

export type MobileSettingSection = SettingsSectionID;

export function MobileSettingsPage({ onOpen }: { onOpen: (section: MobileSettingSection) => void }): React.ReactElement {
  const { t } = useTranslation();
  const {session}=useAuth();const sections=visibleSettingsSections({manager:Boolean(session?.capabilities?.manager),superAdmin:session?.role==="super_admin"}).filter(item=>item.id!=="workspace");
  return (
    <section className="tr-mobile-workspace">
      <header>
        <h1>{t("settingsPanel.title")}</h1>
        <p>{t("settingsPanel.mobileHint")}</p>
      </header>
      <div className="tr-mobile-open-list">
        {sections.map(({id:section,icon}) => (
          <button key={section} type="button" className="tr-mobile-open-row" onClick={() => onOpen(section)}>
            <span className="tr-mobile-open-icon"><PageIcon name={icon} /></span>
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
  return (
    <div className="tr-mobile-settings-detail">
      <header className="tr-mobile-page-header">
        <button type="button" className="tr-mobile-back" aria-label={t("back")} onClick={onBack}>
          <PageIcon name="back" />
        </button>
        <strong>{t(`settingsPanel.sections.${section}`)}</strong>
      </header>
      <div className="tr-mobile-settings-body">
        <SettingsSection key={section} section={section}/>
      </div>
    </div>
  );
}
