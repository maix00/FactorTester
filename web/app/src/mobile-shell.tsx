import React, { useEffect, useRef, useState } from "react";
import { IonApp, IonTabBar, IonTabButton } from "@ionic/react";
import { useTranslation } from "react-i18next";
import { BUILTIN_PAGES, getPage, pagesForScope, registerPage } from "./registry.ts";
import { PageIcon } from "./icon.tsx";
import { PageSurface } from "./surface.tsx";
import { MobileSettingDetail, MobileSettingsPage, type MobileSettingSection } from "./pages/mobile-settings.tsx";
import { PageErrorBoundary } from "./error-boundary.tsx";
import { MobileNotificationHost } from "./notifications/mobile-host.tsx";
import { AppTheme } from "./components/app-theme.tsx";
import { PageInstanceProvider, newPageInstanceId, type PageArguments } from "./page-instance.ts";

for (const page of BUILTIN_PAGES) registerPage(page);
const tabs = pagesForScope("mobile").filter((page) => page.mobileTab);
type Entry = { id: string; pageId: string; args: PageArguments; root?: boolean };

export function MobileShell(): React.ReactElement {
  const { t } = useTranslation();
  const [entries, setEntries] = useState<Entry[]>(() => tabs.map((page) => ({ id: newPageInstanceId(page.id), pageId: page.id, args: {}, root: true })));
  const [active, setActive] = useState(entries[0].id);
  const [setting, setSetting] = useState<MobileSettingSection | null>(null);
  const refs = useRef(entries); refs.current = entries;
  const current = entries.find((item) => item.id === active) || entries[0];
  useEffect(() => {
    history.replaceState({ ...history.state, trPage: active }, "", location.href);
    const onPop = (event: PopStateEvent): void => {
      const known = refs.current.find((item) => item.id === event.state?.trPage);
      if (known) setActive(known.id);
      else setActive(refs.current.find((item) => item.pageId === "more")!.id);
      setSetting(event.state?.trSettings || null);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const setRoute = (id: string, replace = false): void => {
    const url = new URL(location.href);
    for (const key of ["tr_config", "tr_item", "tr_path", "workspace_id"]) url.searchParams.delete(key);
    history[replace ? "replaceState" : "pushState"]({ trPage: id }, "", url.href);
    setActive(id); setSetting(null);
  };
  const open = (pageId: string, args: PageArguments = {}): void => {
    const item: Entry = { id: newPageInstanceId(pageId), pageId, args };
    setEntries((items) => [...items, item]); setRoute(item.id);
  };
  const back = (): void => history.back();
  return <AppTheme><IonApp><MobileNotificationHost /><div className="tr-mobile-shell" data-nested={!current.root}>
    {entries.map((entry) => <div className="tr-mobile-instance" hidden={entry.id !== active} key={entry.id}>
      <PageInstanceProvider value={{ ...entry, mobile: true, active: entry.id === active, open, back }}>
        <PageErrorBoundary label={entry.pageId}>
          {!entry.root && !(entry.pageId === "settings" && setting && entry.id === active) ? <div className="tr-mobile-page-back"><button type="button" onClick={back}><PageIcon name="back" />{t("back")}</button></div> : null}
          {entry.pageId === "settings" ? setting && entry.id === active ? <MobileSettingDetail section={setting} onBack={back} /> :
            <MobileSettingsPage onOpen={(section) => { setSetting(section); history.pushState({ ...history.state, trSettings: section }, "", location.href); }} /> : <PageSurface pageId={entry.pageId} />}
        </PageErrorBoundary>
      </PageInstanceProvider>
    </div>)}
    {current.root ? <IonTabBar className="tr-mobile-tabs" slot="bottom">{tabs.map((item) => <IonTabButton key={item.id} tab={item.id} selected={current.pageId === item.id}
      aria-label={t(`nav.${item.id}`, { defaultValue: item.title })} onClick={() => setRoute(entries.find((entry) => entry.root && entry.pageId === item.id)!.id, true)}>
      <PageIcon name={item.icon} /><span>{t(`nav.${item.id}`, { defaultValue: item.title })}</span>
    </IonTabButton>)}</IonTabBar> : null}
  </div></IonApp></AppTheme>;
}
