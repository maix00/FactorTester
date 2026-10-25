import React from "react";
import { pagesForScope } from "../registry.ts";
import { PageIcon } from "../icon.tsx";

const RECENT_KEY = "tr.mobile.recent";

function recentIds(): string[] {
  try {
    const value = JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]");
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
  } catch {
    return [];
  }
}

export function WorkspacePage(): React.ReactElement {
  const recent = recentIds();
  const pages = pagesForScope("mobile")
    .filter((page) => page.id !== "workspace")
    .sort((a, b) => {
      const ai = recent.indexOf(a.id);
      const bi = recent.indexOf(b.id);
      return (ai < 0 ? 999 : ai) - (bi < 0 ? 999 : bi);
    });
  return (
    <section className="tr-mobile-workspace">
      <header>
        <h1>工作区</h1>
        <p>已打开和最近访问的页面</p>
      </header>
      <div className="tr-mobile-open-list">
        {pages.map((page) => (
          <a key={page.id} href={`/m/${page.id}`} className="tr-mobile-open-row">
            <span className="tr-mobile-open-icon"><PageIcon name={page.icon} /></span>
            <span>{page.title}</span>
            <span className="tr-mobile-open-route">{page.route.split("?")[0]}</span>
          </a>
        ))}
      </div>
    </section>
  );
}
