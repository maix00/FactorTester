import React, { useState } from "react";
import { IonApp, IonContent, IonPage, IonTabBar, IonTabButton } from "@ionic/react";
import { BUILTIN_PAGES, pagesForScope, registerPage } from "./registry.ts";
import { PageSurface } from "./surface.tsx";

for (const page of BUILTIN_PAGES) registerPage(page);

const tabs = pagesForScope("mobile").filter((page) => page.mobileTab);

export function MobileShell(): React.ReactElement {
  const [active, setActive] = useState(tabs[0]?.id ?? "research");
  return (
    <IonApp>
      <IonPage>
        <IonContent fullscreen>
          <div className="tr-mobile-shell">
            <PageSurface pageId={active} />
          </div>
        </IonContent>
        <IonTabBar slot="bottom">
          {tabs.map((page) => (
            <IonTabButton
              key={page.id}
              tab={page.id}
              selected={active === page.id}
              onClick={() => setActive(page.id)}
            >
              {page.title}
            </IonTabButton>
          ))}
        </IonTabBar>
      </IonPage>
    </IonApp>
  );
}
