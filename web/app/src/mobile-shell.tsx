import React, { useEffect, useState } from "react";
import { IonApp, IonTabBar, IonTabButton } from "@ionic/react";
import { useTranslation } from "react-i18next";
import { BUILTIN_PAGES, pagesForScope, registerPage } from "./registry.ts";
import { PageIcon } from "./icon.tsx";
import { PageFrame } from "./frame.tsx";
import { WorkspacePage } from "./pages/workspace.tsx";
import { MobileSettingDetail, MobileSettingsPage, type MobileSettingSection } from "./pages/mobile-settings.tsx";
import { MobileJobsPage } from "./pages/mobile-jobs.tsx";
import { PageErrorBoundary } from "./error-boundary.tsx";
import { MobileNotificationHost } from "./notifications/mobile-host.tsx";

for (const page of BUILTIN_PAGES) registerPage(page);

const tabs = pagesForScope("mobile").filter((page) => page.mobileTab);

export function MobileShell(): React.ReactElement {
  const { t } = useTranslation();
  const [active, setActive] = useState(tabs[0]?.id ?? "research");
  const [setting, setSetting] = useState<MobileSettingSection | null>(null);
  const page = tabs.find((item) => item.id === active) ?? tabs[0];

  useEffect(() => {
    const onPop = (): void => setSetting(null);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const selectTab = (id: string): void => {
    try {
      const recent = JSON.parse(localStorage.getItem("tr.mobile.recent") ?? "[]");
      const next = [id, ...(Array.isArray(recent) ? recent : []).filter((value) => value !== id)].slice(0, 8);
      localStorage.setItem("tr.mobile.recent", JSON.stringify(next));
    } catch { /* ignore unavailable storage */ }
    setActive(id);
    setSetting(null);
  };

  const openSetting = (section: MobileSettingSection): void => {
    setSetting(section);
    window.history.pushState({ trSettings: section }, "", location.href);
  };

  const backSetting = (): void => {
    if (window.history.state?.trSettings) window.history.back();
    else setSetting(null);
  };

  return (
    <IonApp>
      <MobileNotificationHost />
      {page?.id === "settings" && setting ? (
        <MobileSettingDetail section={setting} onBack={backSetting} />
      ) : (
        <div className="tr-mobile-shell">
          <PageErrorBoundary label={page?.id ?? "mobile"}>
          {page?.id === "workspace" ? (
            <WorkspacePage onOpen={selectTab} />
          ) : page?.id === "jobs" ? (
            <MobileJobsPage />
          ) : page?.id === "settings" ? (
            <MobileSettingsPage onOpen={openSetting} />
          ) : (
            <PageFrame pageId={page?.id ?? "research"} />
          )}
          </PageErrorBoundary>
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
