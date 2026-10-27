import React from "react";
import { useTranslation } from "react-i18next";
export type PropertyItem = { key: string; label: string; value: unknown; wide?: boolean; render?: (value: unknown) => React.ReactNode };
export type PropertyGroup = { key: string; title: string; items: PropertyItem[] };
/** Empty collections are reported values; zero and false must remain visible. */
export function isReported(value: unknown): boolean { return value !== null && value !== undefined && value !== ""; }
export function PropertyGroups({ groups }: { groups: PropertyGroup[] }): React.ReactElement {
 const {t}=useTranslation();
 const missing=groups.flatMap(group => group.items.filter(item => !isReported(item.value)));
 const rows=(items:PropertyItem[]):React.ReactElement => <dl className="tr-property-list">{items.map(item => <div key={item.key} className={item.wide ? "is-wide" : undefined}><dt>{item.label}</dt><dd>{isReported(item.value) ? item.render ? item.render(item.value) : String(item.value) : t("sources.unknown")}</dd></div>)}</dl>;
 return <div className="tr-property-groups">{groups.map(group => {const present=group.items.filter(item => isReported(item.value));return present.length ? <section className="tr-property-group" key={group.key}><h3>{group.title}</h3>{rows(present)}</section> : null;})}
 {missing.length ? <details className="tr-property-missing"><summary>{t("sources.unreported",{count:missing.length})}</summary>{rows(missing)}</details> : null}</div>;
}
