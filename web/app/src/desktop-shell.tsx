import React, { useState } from "react";
import { DockviewReact, type DockviewReadyEvent, type IDockviewPanelHeaderProps, type IDockviewPanelProps } from "dockview-react";
import { BUILTIN_PAGES, getPage, pagesForScope, registerPage } from "./registry.ts";
import { PageSurface } from "./surface.tsx";
import { PageIcon } from "./icon.tsx";

for (const page of BUILTIN_PAGES) registerPage(page);

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
const LAYOUT_KEY = "tr.workspace.layout.v1";
type DockviewApi = DockviewReadyEvent["api"];

export function DesktopShell(): React.ReactElement {
  const pages = pagesForScope("desktop");
  const [api, setApi] = useState<DockviewApi | null>(null);
  const [active, setActive] = useState(pages[0]?.id ?? "research");

  const open = (pageId: string): void => {
    setActive(pageId);
    if (!api) return;
    const page = pages.find((item) => item.id === pageId);
    if (!page) return;
    const panel = api.getPanel(page.id);
    if (panel) panel.api.setActive();
    else api.addPanel({ id: page.id, component: "page", tabComponent: "page", title: page.title, params: { pageId: page.id } });
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
    event.api.onDidLayoutChange(() => {
      try { localStorage.setItem(LAYOUT_KEY, JSON.stringify(event.api.toJSON())); } catch { /* storage disabled */ }
    });
  };

  return (
    <div className="tr-desktop-shell">
      <aside className="tr-desktop-rail" aria-label="主导航">
        <div className="tr-brand"><span className="tr-brand-mark" aria-hidden="true" />TradeResearch</div>
        <nav className="tr-nav">
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
              <span>{page.title}</span>
            </button>
          ))}
        </nav>
        <div className="tr-rail-footer">TradeResearch Workbench</div>
      </aside>
      <div className="tr-desktop-workspace dockview-theme-light">
        <DockviewReact className="dockview-theme-light" components={components} tabComponents={tabComponents} onReady={onReady} />
      </div>
    </div>
  );
}
