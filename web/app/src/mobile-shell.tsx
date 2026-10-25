import React, { useState } from "react";
import { IonApp, IonTabBar, IonTabButton } from "@ionic/react";
import { BUILTIN_PAGES, pagesForScope, registerPage } from "./registry.ts";
import { PageIcon } from "./icon.tsx";
import { useTranslation } from "react-i18next";
import { PageFrame } from "./frame.tsx";
import { MobileNotificationHost } from "./notifications/mobile-host.tsx";
import { WorkspacePage } from "./pages/workspace.tsx";
import { MobileSettingsPage } from "./pages/mobile-settings.tsx";

for (const page of BUILTIN_PAGES) registerPage(page);

const tabs = pagesForScope("mobile").filter((page) => page.mobileTab);

export function MobileShell(): React.ReactElement {
  const { t } = useTranslation();
  const [active, setActive] = useState(tabs[0]?.id ?? "research");
  const page = tabs.find((item) => item.id === active) ?? tabs[0];
  React.useEffect(() => {
    if (!page || page.id === "workspace") return;
    try {
      const key = "tr.mobile.recent";
      const current = JSON.parse(localStorage.getItem(key) ?? "[]");
      const next = [page.id, ...(Array.isArray(current) ? current.filter((id) => id !== page.id) : [])].slice(0, 8);
      localStorage.setItem(key, JSON.stringify(next));
    } catch { /* storage disabled */ }
  }, [page]);
  return (
    <IonApp>
      <MobileNotificationHost />
      <div className="tr-mobile-shell">
        {page?.id === "workspace" ? <WorkspacePage /> : page?.id === "settings" ? <MobileSettingsPage /> : <PageFrame pageId={page?.id ?? "research"} />}
        <IonTabBar className="tr-mobile-tabs" slot="bottom">
          {tabs.map((item) => (
            <IonTabButton
              key={item.id}
              tab={item.id}
              selected={active === item.id}
              aria-label={item.title}
              onClick={() => setActive(item.id)}
            >
              <PageIcon name={item.icon} />
              <span>{t(`nav.${item.id}`, { defaultValue: item.title })}</span>
            </IonTabButton>
          ))}
        </IonTabBar>
      </div>
    </IonApp>
  );
}
