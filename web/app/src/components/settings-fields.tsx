import React from "react";
import { PropertyGroups, type PropertyItem } from "./property-groups.tsx";

/** Ordinary settings share the same compact label/control layout. */
export function SettingsFields({ items }: { items: PropertyItem[] }): React.ReactElement {
  return <PropertyGroups controls groups={[{ key: "settings", title: "", items }]} />;
}
