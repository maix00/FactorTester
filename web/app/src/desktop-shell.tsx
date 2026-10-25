import React from "react";
import { DockviewReact, type DockviewReadyEvent, type IDockviewPanelProps } from "dockview-react";
import { BUILTIN_PAGES, pagesForScope, registerPage } from "./registry.ts";
import { PageSurface } from "./surface.tsx";

for (const page of BUILTIN_PAGES) registerPage(page);

function Panel(props: IDockviewPanelProps<{ pageId: string }>): React.ReactElement {
  return <PageSurface pageId={props.params.pageId} />;
}

const components = { page: Panel };

export function DesktopShell(): React.ReactElement {
  const onReady = (event: DockviewReadyEvent): void => {
    const initial = pagesForScope("desktop").filter((page) => page.id !== "account").slice(0, 3);
    for (const page of initial) {
      event.api.addPanel({ id: page.id, component: "page", title: page.title, params: { pageId: page.id } });
    }
  };
  return (
    <div className="tr-desktop-shell">
      <aside className="tr-desktop-rail">
        <strong>TradeResearch</strong>
        {pagesForScope("desktop").map((page) => <span key={page.id}>{page.title}</span>)}
      </aside>
      <div className="tr-desktop-workspace">
        <DockviewReact components={components} onReady={onReady} />
      </div>
    </div>
  );
}
