import {appEntrySearch,cleanAppURL} from "./app-route.ts";
import {appCatalogLink} from "./app-link.ts";
import {pageObjectKey,pageObjectTitle} from "./page-object.ts";
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

function restoredEntries(value: unknown): Entry[] | null {
  if (!Array.isArray(value) || !value.length || !value.every(entry => entry && typeof entry.id === "string" && getPage(entry.pageId) && entry.args && typeof entry.args === "object")) return null;
  if (!tabs.every(tab => value.some(entry => entry.root && entry.pageId === tab.id))) return null;
  return value;
}

function MobileWorkspace(): React.ReactElement {
  const { t } = useTranslation();
  const [restored] = useState(() => restoredEntries(history.state?.trMobileEntries));
  const initialLink=restored ? null : appCatalogLink(appEntrySearch());
  const initialAccount = !restored && new URLSearchParams(appEntrySearch()).get("settings") === "account";
  const [entries, setEntries] = useState<Entry[]>(() => restored || [
    ...tabs.map((page) => ({ id: newPageInstanceId(page.id), pageId: page.id, args: {}, root: true })),
    ...(initialLink ? [{id:newPageInstanceId(initialLink.pageId),pageId:initialLink.pageId,args:initialLink.args}] : []),
    ...(initialAccount ? [{id: newPageInstanceId("settings"), pageId: "settings", args: {}}] : []),
  ]);
  const [active, setActive] = useState(() => restored?.some(entry=>entry.id===history.state?.trPage) ? history.state.trPage : initialAccount || initialLink ? entries[entries.length - 1].id : entries[0].id);
  const [setting, setSetting] = useState<MobileSettingSection | null>(restored ? history.state?.trSettings || null : initialAccount ? "account" : null);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const assistantHistoryId = useRef(newPageInstanceId("assistant"));
  const assistantClosing = useRef(false);
  const refs = useRef(entries); refs.current = entries;
  const current = entries.find((item) => item.id === active) || entries[0];
  useEffect(() => {
    cleanAppURL();
    if (initialAccount) {
      const url = new URL(location.href); url.searchParams.delete("settings");
      history.replaceState({trPage: entries[0].id}, "", url.href);
      history.pushState({trPage: active}, "", url.href);
      history.pushState({trPage: active, trSettings: "account"}, "", url.href);
    } else if (initialLink) {
      const url=new URL(location.href);
      for(const key of ["page","section","object_ref","owner_username","mode"])url.searchParams.delete(key);
      history.replaceState({trPage:entries[0].id},"",url.href);
      history.pushState({trPage:active},"",location.href);
    } else history.replaceState({ ...history.state, trPage: active }, "", location.href);
    const onPop = (event: PopStateEvent): void => {
      const saved = restoredEntries(event.state?.trMobileEntries);
      if (saved) setEntries(saved);
      const known = (saved || refs.current).find((item) => item.id === event.state?.trPage);
      if (known) setActive(known.id);
      else setActive(refs.current.find((item) => item.pageId === "more")!.id);
      setSetting(event.state?.trSettings || null);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  useEffect(() => {
    if (!assistantOpen) return;
    const id = assistantHistoryId.current;
    assistantClosing.current = false;
    history.pushState({ ...history.state, trAssistant: id }, "", location.href);
    const onPop = (event: PopStateEvent): void => {
      if (event.state?.trAssistant !== id) setAssistantOpen(false);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [assistantOpen]);
  const setAssistantVisible = (visible: boolean): void => {
    if (visible) { setAssistantOpen(true); return; }
    if (history.state?.trAssistant === assistantHistoryId.current) {
      if (!assistantClosing.current) { assistantClosing.current = true; history.back(); }
    } else setAssistantOpen(false);
  };
  useEffect(() => {
    history.replaceState({...history.state, trMobileEntries: entries}, "", location.href);
  }, [entries]);
  const setRoute = (id: string, replace = false, nextEntries = entries): void => {
    const url = new URL(location.href);
    for (const key of ["tr_config", "tr_item", "tr_path", "workspace_id"]) url.searchParams.delete(key);
    history[replace ? "replaceState" : "pushState"]({ trPage: id, trMobileEntries: nextEntries }, "", url.href);
    setActive(id); setSetting(null);
  };
  const open = (pageId: string, args: PageArguments = {}): void => {
    const key=pageObjectKey(pageId,args);
    const matching=key?entries.find(entry=>pageObjectKey(entry.pageId,entry.args)===key):undefined;
    if(matching){setRoute(matching.id);return;}
    if (Object.keys(args).length === 0) {
      const existing = entries.find((item) => item.pageId === pageId && Object.keys(item.args).length === 0);
      if (existing) { setRoute(existing.id); return; }
    }
    const item: Entry = { id: newPageInstanceId(pageId), pageId, args };
    setEntries((items) => [...items, item]); setRoute(item.id, false, [...entries, item]);
  };
  const back = (): void => history.back();
  const currentPage = getPage(current.pageId);
  const title = current.pageId === "settings" && setting
    ? t(`settingsPanel.sections.${setting}`)
    : pageObjectTitle(current.pageId,current.args)
      ? pageObjectTitle(current.pageId,current.args)!
      : t(`nav.${current.pageId}`, { defaultValue: currentPage?.title || current.pageId });
  const nested = !current.root || Boolean(setting);
  return <>
    <AgentAssistant open={assistantOpen} onOpenChange={setAssistantVisible} />
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
