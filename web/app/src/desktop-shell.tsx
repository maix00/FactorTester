import React, { useState } from "react";
import {
  DockviewReact,
  type DockviewReadyEvent,
  type IDockviewPanelHeaderProps,
  type IDockviewPanelProps,
} from "dockview-react";
import { BUILTIN_PAGES, getPage, pagesForScope, registerPage } from "./registry.ts";
import { PageIcon } from "./icon.tsx";
import { PageSurface } from "./surface.tsx";

for (const page of BUILTIN_PAGES) registerPage(page);

type OpenPanel = { id: string; pageId: string; title: string };

function Panel(props: IDockviewPanelProps<{ pageId: string }>): React.ReactElement {
  return <PageSurface pageId={props.params.pageId} />;
}

function Tab(props: IDockviewPanelHeaderProps<{ pageId: string }>): React.ReactElement {
  const page = getPage(props.params.pageId);
  return (
    <span className="tr-dock-tab">
      <PageIcon name={page?.icon} />
      <span>{page?.title ?? props.api.title ?? props.params.pageId}</span>
      <button type="button" className="tr-dock-close" aria-label="关闭" onClick={() => props.api.close()}>×</button>
    </span>
  );
}

const components = { page: Panel };
const tabComponents = { page: Tab };
const LAYOUT_KEY = "tr.workspace.layout.v2";
type DockviewApi = DockviewReadyEvent["api"];

export function DesktopShell(): React.ReactElement {
  const pages = pagesForScope("desktop");
  const [api, setApi] = useState<DockviewApi | null>(null);
  const [active, setActive] = useState(pages[0]?.id ?? "research");
  const [collapsed, setCollapsed] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    const value = Number(localStorage.getItem("tr.sidebar.width"));
    return Number.isFinite(value) && value >= 180 && value <= 360 ? value : 230;
  });
  const [openPanels, setOpenPanels] = useState<OpenPanel[]>([]);

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

  const syncPanels = (container: DockviewApi): void => {
    setOpenPanels(container.panels.map((panel) => ({
      id: panel.id,
      pageId: String(panel.params?.pageId ?? panel.id),
      title: panel.title ?? "",
    })));
  };

  const open = (pageId: string): void => {
    setActive(pageId);
    if (!api) return;
    const page = pages.find((item) => item.id === pageId);
    if (!page) return;
    const panel = api.getPanel(page.id);
    if (panel) panel.api.setActive();
    else api.addPanel({ id: page.id, component: "page", tabComponent: "page", title: page.title, params: { pageId: page.id } });
  };

  const close = (panelId: string): void => {
    api?.getPanel(panelId)?.api.close();
  };

  const resetLayout = (): void => {
    if (!api) return;
    localStorage.removeItem(LAYOUT_KEY);
    api.clear();
    for (const page of pages.filter((item) => ["research", "jobs", "trading"].includes(item.id))) {
      api.addPanel({ id: page.id, component: "page", tabComponent: "page", title: page.title, params: { pageId: page.id } });
    }
  };

  const onReady = (event: DockviewReadyEvent): void => {
    setApi(event.api);
    let restored = false;
    try {
      const raw = localStorage.getItem(LAYOUT_KEY);
      if (raw) {
        event.api.fromJSON(JSON.parse(raw));
        restored = true;
      }
    } catch {
      restored = false;
    }
    if (!restored) {
      for (const page of pages.filter((item) => ["research", "jobs", "trading"].includes(item.id))) {
        event.api.addPanel({ id: page.id, component: "page", tabComponent: "page", title: page.title, params: { pageId: page.id } });
      }
    }
    syncPanels(event.api);
    event.api.onDidAddPanel(() => syncPanels(event.api));
    event.api.onDidRemovePanel(() => syncPanels(event.api));
    event.api.onDidActivePanelChange(({ panel }) => {
      const pageId = String(panel?.params?.pageId ?? "");
      if (pageId) setActive(pageId);
    });
    event.api.onDidLayoutChange(() => {
      try { localStorage.setItem(LAYOUT_KEY, JSON.stringify(event.api.toJSON())); } catch { /* storage disabled */ }
    });
  };

  return (
    <div className={`tr-app-shell${collapsed ? " is-collapsed" : ""}`} style={{ "--tr-sidebar-width": `${sidebarWidth}px` } as React.CSSProperties}>
      <aside className="tr-sidebar" aria-label="主导航">
        <div className="tr-sidebar-header">
          <button type="button" className="tr-sidebar-brand" onClick={() => open(pages[0]?.id ?? "research")}>
            <span className="tr-sidebar-title">TradeResearch</span>
          </button>
          <button type="button" className="tr-sidebar-toggle" aria-label={collapsed ? "展开侧栏" : "收起侧栏"} title={collapsed ? "展开侧栏" : "收起侧栏"} onClick={() => setCollapsed((value) => !value)}>
            <PageIcon name="sidebar" />
          </button>
        </div>
        <div className="tr-sidebar-resize" role="separator" aria-orientation="vertical" aria-label="调整侧栏宽度" onPointerDown={startResize} />
        <div className="tr-sidebar-caption">功能入口</div>
        <nav className="tr-module-nav">
          {pages.map((page) => (
            <button
              key={page.id}
              type="button"
              className={`tr-nav-item${active === page.id ? " is-active" : ""}`}
              data-tooltip={page.title}
              aria-label={page.title}
              title={page.title}
              onClick={() => open(page.id)}
            >
              <PageIcon name={page.icon} />
              <span className="tr-nav-label">{page.title}</span>
            </button>
          ))}
        </nav>
        <div className="tr-sidebar-caption tr-opened-caption" hidden={openPanels.length === 0}>已打开</div>
        <nav className="tr-opened-tabs" aria-label="已打开">
          {openPanels.map((panel) => (
            <div key={panel.id} className={`tr-opened-tab${active === panel.pageId ? " is-active" : ""}`}>
              <button type="button" className="tr-opened-main" onClick={() => { setActive(panel.pageId); api?.getPanel(panel.id)?.api.setActive(); }}>
                <PageIcon name={getPage(panel.pageId)?.icon} />
                <span>{panel.title}</span>
              </button>
              <button type="button" className="tr-opened-close" aria-label="关闭" onClick={() => close(panel.id)}>×</button>
            </div>
          ))}
        </nav>
        <div className="tr-sidebar-spacer" />
        <button type="button" className="tr-sidebar-reset" onClick={resetLayout}>重置布局</button>
        <button type="button" className="tr-account-button" onClick={() => open("account")}>
          <PageIcon name="account" />
          <span className="tr-nav-label">设置</span>
        </button>
      </aside>
      <main className="tr-main">
        <section className="tr-workspace dockview-theme-light">
          <DockviewReact className="dockview-theme-light" components={components} tabComponents={tabComponents} onReady={onReady} />
        </section>
      </main>
    </div>
  );
}
