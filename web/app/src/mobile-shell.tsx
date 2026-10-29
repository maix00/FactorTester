import React, { useEffect, useRef, useState } from "react";
import { IonApp, IonBadge, IonButton, IonButtons, IonContent, IonHeader, IonPage, IonTabBar, IonTabButton, IonTitle, IonToolbar } from "@ionic/react";
import { useTranslation } from "react-i18next";
import { BUILTIN_PAGES, getPage, pagesForScope, registerPage } from "./registry.ts";
import { PageIcon } from "./icon.tsx";
import { PageSurface } from "./surface.tsx";
import { MobileSettingDetail, MobileSettingsPage, type MobileSettingSection } from "./pages/mobile-settings.tsx";
import { PageErrorBoundary } from "./error-boundary.tsx";
import { MobileNotificationHost, useMobileNotificationCenter } from "./notifications/mobile-host.tsx";
import { AgentAssistant } from "./components/agent-assistant.tsx";
import { AppTheme } from "./components/app-theme.tsx";
import { PageInstanceProvider, newPageInstanceId, type PageArguments } from "./page-instance.ts";
import { WorkspacePage } from "./pages/workspace.tsx";

for (const page of BUILTIN_PAGES) registerPage(page);
const tabs = pagesForScope("mobile").filter((page) => page.mobileTab);
type Entry = { id: string; pageId: string; args: PageArguments; root?: boolean };

export function MobileShell(): React.ReactElement {
  return <AppTheme><IonApp><MobileNotificationHost><MobileWorkspace /></MobileNotificationHost></IonApp></AppTheme>;
}

function MobileWorkspace(): React.ReactElement {
  const { t } = useTranslation();
  const [entries, setEntries] = useState<Entry[]>(() => tabs.map((page) => ({ id: newPageInstanceId(page.id), pageId: page.id, args: {}, root: true })));
  const [active, setActive] = useState(entries[0].id);
  const [setting, setSetting] = useState<MobileSettingSection | null>(null);
  const [assistantOpen, setAssistantOpen] = useState(false);
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
  const currentPage = getPage(current.pageId);
  const title = current.pageId === "settings" && setting
    ? t(`settingsPanel.sections.${setting}`)
    : current.pageId === "product-detail" && current.args.productTitle
      ? current.args.productTitle
      : t(`nav.${current.pageId}`, { defaultValue: currentPage?.title || current.pageId });
  const nested = !current.root || Boolean(setting);
  return <>
    <AgentAssistant open={assistantOpen} onOpenChange={setAssistantOpen} />
    <IonPage className="tr-mobile-shell" data-nested={nested} data-root={current.root}>
      <MobileHeader title={title} nested={nested} onBack={back} onOpenAssistant={() => setAssistantOpen(true)} />
      <IonContent className="tr-mobile-content" data-root={current.root}>
        {entries.map((entry) => <div className="tr-mobile-instance" hidden={entry.id !== active} key={entry.id}>
          <PageInstanceProvider value={{ ...entry, mobile: true, active: entry.id === active, open, back }}>
            <PageErrorBoundary label={entry.pageId}>
              {entry.pageId === "settings" ? setting && entry.id === active ? <MobileSettingDetail section={setting} /> :
                <MobileSettingsPage onOpen={(section) => { setSetting(section); history.pushState({ ...history.state, trSettings: section }, "", location.href); }} /> :
                entry.pageId === "more" ? <WorkspacePage /> : <PageSurface pageId={entry.pageId} />}
            </PageErrorBoundary>
          </PageInstanceProvider>
        </div>)}
      </IonContent>
    {current.root ? <IonTabBar className="tr-mobile-tabs" slot="bottom">{tabs.map((item) => <IonTabButton key={item.id} tab={item.id} selected={current.pageId === item.id}
      aria-label={t(`nav.${item.id}`, { defaultValue: item.title })} onClick={() => setRoute(entries.find((entry) => entry.root && entry.pageId === item.id)!.id, true)}>
      <PageIcon name={item.icon} /><span>{t(`nav.${item.id}`, { defaultValue: item.title })}</span>
    </IonTabButton>)}</IonTabBar> : null}
    </IonPage>
  </>;
}

function MobileHeader({ title, nested, onBack, onOpenAssistant }: { title: string; nested: boolean; onBack: () => void; onOpenAssistant: () => void }): React.ReactElement {
  const { t } = useTranslation();
  const { openCenter, unread } = useMobileNotificationCenter();
  return <IonHeader className="tr-mobile-header">
    <IonToolbar>
      {nested ? <IonButtons slot="start"><IonButton className="tr-mobile-header-action" fill="clear" aria-label={t("back")} onClick={onBack}><PageIcon name="back" /></IonButton></IonButtons> : null}
      <IonTitle>{title}</IonTitle>
      <IonButtons slot="end">
        <IonButton className="tr-mobile-header-action" fill="clear" aria-label={t("notifications.bell")} onClick={openCenter}>
          <span className="tr-mobile-header-icon"><PageIcon name="notifications" />{unread > 0 ? <IonBadge color="danger">{unread > 99 ? "99+" : unread}</IonBadge> : null}</span>
        </IonButton>
        <IonButton className="tr-mobile-header-action" fill="clear" aria-label={t("assistant.open")} onClick={onOpenAssistant}>
          <PageIcon name="assistant" />
        </IonButton>
      </IonButtons>
    </IonToolbar>
  </IonHeader>;
}
