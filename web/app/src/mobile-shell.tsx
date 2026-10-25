import React, { useEffect, useState } from "react";
import { IonApp } from "@ionic/react";
import { useTranslation } from "react-i18next";
import { BUILTIN_PAGES, getPage, pagesForScope, registerPage } from "./registry.ts";
import { PageIcon } from "./icon.tsx";
import { PageFrame } from "./frame.tsx";
import { WorkspacePage } from "./pages/workspace.tsx";
import { MobileSettingsPage } from "./pages/mobile-settings.tsx";
import { MobileNotificationHost } from "./notifications/mobile-host.tsx";

for (const page of BUILTIN_PAGES) registerPage(page);

const pages = pagesForScope("mobile").filter((page) => page.id !== "workspace");

export function MobileShell(): React.ReactElement {
  const { t } = useTranslation();
  const [active, setActive] = useState<string | null>(null);
  const page = active ? getPage(active) : null;

  useEffect(() => {
    const onPop = (): void => setActive(null);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const open = (id: string): void => {
    setActive(id);
    window.history.pushState({ trMobile: id }, "", location.href);
  };

  const back = (): void => {
    if (window.history.state?.trMobile) window.history.back();
    else setActive(null);
  };

  return (
    <IonApp>
      <MobileNotificationHost />
      {page ? (
        <div className="tr-mobile-page">
          <header className="tr-mobile-page-header">
            <button type="button" className="tr-mobile-back" aria-label={t("back")} onClick={back}>
              <PageIcon name="back" />
            </button>
            <strong>{t(`common.nav.${page.id}`, { defaultValue: page.title })}</strong>
          </header>
          <div className="tr-mobile-page-body">
            {page.id === "settings" ? <MobileSettingsPage /> : <PageFrame pageId={page.id} canvas />}
          </div>
        </div>
      ) : (
        <div className="tr-mobile-shell">
          <WorkspacePage onOpen={open} />
        </div>
      )}
    </IonApp>
  );
}
