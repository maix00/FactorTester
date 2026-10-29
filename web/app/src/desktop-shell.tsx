import React, { useCallback, useEffect, useState } from "react";
import { Dropdown, Tooltip } from "antd";
import { MoreOutlined } from "@ant-design/icons";
import {
  DockviewReact,
  type DockviewReadyEvent,
  type IDockviewPanelHeaderProps,
  type IDockviewPanelProps,
} from "dockview-react";
import { BUILTIN_PAGES, getPage, pagesForScope, registerPage } from "./registry.ts";
import { PageIcon } from "./icon.tsx";
import { PageInstanceProvider, newPageInstanceId, type PageArguments } from "./page-instance.ts";
import { PageSurface } from "./surface.tsx";
import { useCompactLayout } from "./configuration/layout.ts";
import { AppTheme } from "./components/app-theme.tsx";
import { Brand } from "./components/brand.tsx";
import { useTranslation } from "react-i18next";
import { workspaceLayoutKey } from "./layout.ts";
import { useAuth } from "./auth.tsx";
import { AccountMenu } from "./components/account-actions.tsx";
import { SettingsOverlay } from "./components/settings-overlay.tsx";
import { PageErrorBoundary } from "./error-boundary.tsx";
import { DesktopNotificationHost } from "./notifications/antd-host.tsx";
import { AgentAssistant } from "./components/agent-assistant.tsx";

for (const page of BUILTIN_PAGES) registerPage(page);

function Panel(props: IDockviewPanelProps<{ pageId: string; args?: PageArguments; ordinal?: number }>): React.ReactElement {
  const { t } = useTranslation();
  const [visible, setVisible] = useState(props.api.isVisible);
  useEffect(() => { const subscription = props.api.onDidVisibilityChange((event) => setVisible(event.isVisible)); return () => subscription.dispose(); }, [props.api]);
  return (
    <div className="tr-tab-layer" data-tab-layer={props.params.pageId} aria-hidden={!visible} inert={!visible}>
      <PageInstanceProvider value={{ id: props.api.id, pageId: props.params.pageId, args: props.params.args || {}, mobile: false, active: visible,
        open: (pageId, args) => {
          const page = getPage(pageId); if (!page) return;
          props.containerApi.addPanel({ id: newPageInstanceId(pageId), component: "page", tabComponent: "page", title: t(`nav.${page.id}`, { defaultValue: page.title }),
            params: { pageId, args, ordinal: props.containerApi.panels.filter((p) => p.params?.pageId === pageId).length + 1 }, renderer: "always" });
        } }}><PageErrorBoundary label={props.params.pageId}><PageSurface pageId={props.params.pageId} /></PageErrorBoundary></PageInstanceProvider>
    </div>
  );
}

function AgentAssistantPanel(props: IDockviewPanelProps<{ pageId: string }>): React.ReactElement {
  const [visible, setVisible] = useState(props.api.isVisible);
  useEffect(() => {
    const subscription = props.api.onDidVisibilityChange((event) => setVisible(event.isVisible));
    return () => subscription.dispose();
  }, [props.api]);
  return <div className="tr-dock-assistant-layer" aria-hidden={!visible} inert={!visible}>
    <AgentAssistant open={visible} presentation="panel" />
  </div>;
}

function Tab(props: IDockviewPanelHeaderProps<{ pageId: string; ordinal?: number }>): React.ReactElement {
  const page = getPage(props.params.pageId);
  const { t } = useTranslation();
  const isAssistant = props.params.pageId === "agent-assistant";
  const title = page ? t(`nav.${page.id}`, { defaultValue: page.title }) : isAssistant ? t("assistant.title") : (props.api.title ?? props.params.pageId);
  const icon = page?.icon ?? (isAssistant ? "assistant" : undefined);
  return (
    <span className="tr-dock-tab" title={title}>
      <PageIcon name={icon} />
      <span className="tr-dock-tab-title" title={title}>{title}{(props.params.ordinal || 1) > 1 ? ` ${props.params.ordinal}` : ""}</span>
      <Dropdown trigger={["click"]} menu={{ items: [
        { key: "right", label: t("panelLayout.right") }, { key: "bottom", label: t("panelLayout.below") },
        { key: "maximize", label: t("panelLayout.maximize") }, { key: "restore", label: t("panelLayout.restore") },
      ], onClick: ({ key }) => {
        if (key === "right" || key === "bottom") props.api.moveTo({ group: props.api.group, position: key });
        else if (key === "maximize") props.api.maximize(); else props.api.exitMaximized();
      } }}><button type="button" className="tr-dock-arrange" aria-label={t("panelLayout.menu")} onPointerDown={(event) => event.stopPropagation()} onClick={(event) => event.stopPropagation()}><MoreOutlined /></button></Dropdown>
      <button type="button" className="tr-dock-close" aria-label={t("close")} onClick={() => props.api.close()}>×</button>
    </span>
  );
}

const components = { page: Panel };
const tabComponents = { page: Tab };
const dockComponents = { ...components, agentAssistant: AgentAssistantPanel };
type DockviewApi = DockviewReadyEvent["api"];

export function DesktopShell(): React.ReactElement {
  const { t } = useTranslation();
  const {session}=useAuth();
  const compact=useCompactLayout();
  const layoutKey=workspaceLayoutKey(session?.username||"anonymous");
  const pages = pagesForScope("desktop").filter((page) => page.sidebarVisible !== false);
  const label = (page: { id: string; title: string }): string => t(`nav.${page.id}`, { defaultValue: page.title });
  const [api, setApi] = useState<DockviewApi | null>(null);
  const [active, setActive] = useState(pages[0]?.id ?? "research");
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("tr.sidebar.collapsed") === "1");
  const effectiveCollapsed=collapsed || compact;
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [assistantRequested, setAssistantRequested] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    const value = Number(localStorage.getItem("tr.sidebar.width"));
    return Number.isFinite(value) && value >= 180 && value <= 360 ? value : 230;
  });

  useEffect(() => { if (api) for (const panel of api.panels) { const page = getPage(panel.params?.pageId); if (page) panel.api.setTitle(t(`nav.${page.id}`, { defaultValue: page.title })); } }, [api, t]);

  const startResize = (event: React.PointerEvent<HTMLDivElement>): void => {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = sidebarWidth;
    const move = (moveEvent: PointerEvent): void => {
      const next = Math.max(180, Math.min(360, startWidth + moveEvent.clientX - startX));
      setSidebarWidth(next);
      localStorage.setItem("tr.sidebar.width", String(next));
    };
    const stop = (): void => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop, { once: true });
  };

  const open = (pageId: string): void => {
    setActive(pageId);
    if (!api) return;
    const page = pages.find((item) => item.id === pageId);
    if (!page) return;
    api.addPanel({ id: newPageInstanceId(pageId), component: "page", tabComponent: "page", title: label(page),
      params: { pageId, ordinal: api.panels.filter((panel) => panel.params?.pageId === pageId).length + 1 }, renderer: "always" });
  };

  const resetLayout = (): void => {
    if (!api) return;
    localStorage.removeItem(layoutKey);
    api.clear();
    for (const page of pages.filter((item) => ["research", "configuration"].includes(item.id))) {
      api.addPanel({ id: newPageInstanceId(page.id), component: "page", tabComponent: "page", title: label(page), params: { pageId: page.id }, renderer: "always" });
    }
  };

  const openAssistant = useCallback((): void => {
    if (!api) {
      setAssistantRequested(true);
      return;
    }
    const existing = api.getPanel("agent-assistant");
    if (existing) {
      existing.api.setActive();
      return;
    }
    const reference = api.activePanel ?? api.panels[0];
    api.addPanel({
      id: "agent-assistant",
      component: "agentAssistant",
      tabComponent: "page",
      title: t("assistant.title"),
      params: { pageId: "agent-assistant" },
      renderer: "always",
      initialWidth: 440,
      minimumWidth: 320,
      ...(reference ? { position: { direction: "right" as const, referencePanel: reference } } : {}),
    });
  }, [api, t]);

  useEffect(() => {
    if (!api || !assistantRequested) return;
    setAssistantRequested(false);
    openAssistant();
  }, [api, assistantRequested, openAssistant]);

  const onReady = (event: DockviewReadyEvent): void => {
    setApi(event.api);
    let restored = false;
    try {
      const raw = localStorage.getItem(layoutKey);
      if (raw) {
        event.api.fromJSON(JSON.parse(raw));
        for (const panel of [...event.api.panels]) {
          if (panel.params?.pageId === "account") panel.api.close();
          else if (panel.params?.pageId === "catalog") panel.api.updateParameters({ pageId: "products" });
          else if (panel.params?.pageId === "agent-assistant") panel.api.setTitle(t("assistant.title"));
        }
        restored = event.api.panels.length > 0;
      }
    } catch {
      restored = false;
    }
    if (!restored) {
      for (const page of pages.filter((item) => ["research", "configuration"].includes(item.id))) {
        event.api.addPanel({ id: newPageInstanceId(page.id), component: "page", tabComponent: "page", title: label(page), params: { pageId: page.id }, renderer: "always" });
      }
    }
    event.api.onDidActivePanelChange(({ panel }) => {
      const pageId = String(panel?.params?.pageId ?? "");
      if (pageId) setActive(pageId);
    });
    event.api.onDidLayoutChange(() => {
      try { localStorage.setItem(layoutKey, JSON.stringify(event.api.toJSON())); } catch { /* storage disabled */ }
    });
  };

  return (
    <AppTheme>
    <DesktopNotificationHost />
    <SettingsOverlay open={settingsOpen} onClose={() => setSettingsOpen(false)} onResetLayout={resetLayout} />
    <div className={`tr-app-shell${effectiveCollapsed ? " is-collapsed" : ""}${compact ? " is-compact" : ""}`} style={{ "--tr-sidebar-width": `${sidebarWidth}px` } as React.CSSProperties}>
      <aside className="tr-sidebar" aria-label={t("mainNavigation")}>
        <div className="tr-sidebar-header">
          <button type="button" className="tr-sidebar-brand" onClick={() => open(pages[0]?.id ?? "research")}>
            <span className="tr-sidebar-title"><Brand /></span>
          </button>
          {!compact ? <button type="button" className="tr-sidebar-toggle" aria-label={collapsed ? t("expand") : t("collapse")} title={collapsed ? t("expand") : t("collapse")} onClick={() => {
              setCollapsed((value) => {
                const next = !value;
                localStorage.setItem("tr.sidebar.collapsed", next ? "1" : "0");
                return next;
              });
            }}>
            <PageIcon name="sidebar" />
          </button> : null}
        </div>
        <div className="tr-sidebar-resize" role="separator" aria-orientation="vertical" aria-label={t("resizeSidebar")} onPointerDown={startResize} />
        <nav className="tr-module-nav">
          {pages.map((page) => (
            <Tooltip key={page.id} title={effectiveCollapsed ? label(page) : undefined} placement="right">
            <button
              key={page.id}
              type="button"
              className={`tr-nav-item${active === page.id ? " is-active" : ""}`}
              aria-label={label(page)}
              onClick={() => open(page.id)}
            >
              <PageIcon name={page.icon} />
              <span className="tr-nav-label">{label(page)}</span>
            </button></Tooltip>
          ))}
        </nav>
        <div className="tr-sidebar-spacer" />
        <Tooltip title={effectiveCollapsed ? t("assistant.title") : undefined} placement="right"><button type="button" aria-label={t("assistant.open")} className={`tr-nav-item${active === "agent-assistant" ? " is-active" : ""}`} onClick={openAssistant}>
          <PageIcon name="assistant" />
          <span className="tr-nav-label">{t("assistant.title")}</span>
        </button></Tooltip>
        <AccountMenu collapsed={effectiveCollapsed}/>
        <Tooltip title={effectiveCollapsed ? t("settings") : undefined} placement="right"><button type="button" aria-label={t("settings")} className="tr-account-button" onClick={() => setSettingsOpen(true)}>
          <PageIcon name="settings" />
          <span className="tr-nav-label">{t("settings")}</span>
        </button></Tooltip>
      </aside>
      <main className="tr-main">
        <section className="tr-workspace dockview-theme-light">
          <DockviewReact className="dockview-theme-light" components={dockComponents} tabComponents={tabComponents} onReady={onReady} />
        </section>
      </main>
    </div>
    </AppTheme>
  );
}
