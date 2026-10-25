import React from "react";
import { IonApp, IonRouterOutlet, IonTabBar, IonTabButton, IonTabs } from "@ionic/react";
import { IonReactRouter } from "@ionic/react-router";
import { Navigate, Route, Routes, useParams } from "react-router-dom";
import { BUILTIN_PAGES, pagesForScope, registerPage } from "./registry.ts";
import { PageSurface } from "./surface.tsx";
import { PageIcon } from "./icon.tsx";

for (const page of BUILTIN_PAGES) registerPage(page);

const tabs = pagesForScope("mobile").filter((page) => page.mobileTab);

function MobilePage(): React.ReactElement {
  const { tab = tabs[0]?.id ?? "research" } = useParams<{ tab: string }>();
  const page = tabs.find((item) => item.id === tab) ?? tabs[0];
  return <PageSurface pageId={page?.id ?? "research"} />;
}

export function MobileShell(): React.ReactElement {
  return (
    <IonApp>
      <IonReactRouter>
        <IonTabs>
          <IonRouterOutlet>
            <Routes>
              <Route path="/m/:tab" element={<MobilePage />} />
              <Route path="*" element={<Navigate to={`/m/${tabs[0]?.id ?? "research"}`} replace />} />
            </Routes>
          </IonRouterOutlet>
          <IonTabBar slot="bottom" className="tr-mobile-tabs">
            {tabs.map((page) => (
              <IonTabButton key={page.id} tab={page.id} href={`/m/${page.id}`} aria-label={page.title}>
                <PageIcon name={page.icon} />
                <span>{page.title}</span>
              </IonTabButton>
            ))}
          </IonTabBar>
        </IonTabs>
      </IonReactRouter>
    </IonApp>
  );
}
