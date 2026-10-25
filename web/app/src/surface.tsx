import React from "react";
import { getPage } from "./registry.ts";

export function PageSurface({ pageId }: { pageId: string }): React.ReactElement {
  const page = getPage(pageId);
  return (
    <section className="tr-page-surface" data-page-id={pageId}>
      <header className="tr-page-header">
        <h1>{page?.title ?? pageId}</h1>
        <span className="tr-page-route">{page?.route ?? ""}</span>
      </header>
      <p className="tr-page-placeholder">
        页面外壳已注册，业务页面将在该路由通过懒加载挂载。
      </p>
    </section>
  );
}
