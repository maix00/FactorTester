import React, { useState } from "react";
import { IonApp, IonTabBar, IonTabButton } from "@ionic/react";
import { useTranslation } from "react-i18next";
import { BUILTIN_PAGES, pagesForScope, registerPage } from "./registry.ts";
import { PageIcon } from "./icon.tsx";
import { PageFrame } from "./frame.tsx";
import { WorkspacePage } from "./pages/workspace.tsx";
import { MobileSettingDetail, MobileSettingsPage, type MobileSettingSection } from "./pages/mobile-settings.tsx";
import { MobileNotificationHost } from "./notifications/mobile-host.tsx";

for (const page of BUILTIN_PAGES) registerPage(page);

const tabs = pagesForScope("mobile").filter((page) => page.mobileTab);

export function MobileShell(): React.ReactElement {
  const { t } = useTranslation();
  const [active, setActive] = useState(tabs[0]?.id ?? "research");
  const [setting, setSetting] = useState<MobileSettingSection | null>(null);
  const page = tabs.find((item) => item.id === active) ?? tabs[0];

  const selectTab = (id: string): void => {
    setActive(id);
    setSetting(null);
  };

  return (
    <IonApp>
      <MobileNotificationHost />
      {page?.id === "settings" && setting ? (
        <MobileSettingDetail section={setting} onBack={() => setSetting(null)} />
      ) : (
        <div className="tr-mobile-shell">
          {page?.id === "workspace" ? (
            <WorkspacePage onOpen={selectTab} />
          ) : page?.id === "settings" ? (
            <MobileSettingsPage onOpen={setSetting} />
          ) : (
            <PageFrame pageId={page?.id ?? "research"} canvas />
          )}
          <IonTabBar className="tr-mobile-tabs" slot="bottom">
            {tabs.map((item) => (
              <IonTabButton
                key={item.id}
                tab={item.id}
                selected={active === item.id}
                aria-label={t(`common.nav.${item.id}`, { defaultValue: item.title })}
                onClick={() => selectTab(item.id)}
              >
                <PageIcon name={item.icon} />
                <span>{t(`common.nav.${item.id}`, { defaultValue: item.title })}</span>
              </IonTabButton>
            ))}
          </IonTabBar>
        </div>
      )}
    </IonApp>
  );
}
