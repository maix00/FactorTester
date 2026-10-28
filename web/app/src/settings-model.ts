export const SETTINGS_SECTIONS = [
  { id: "account", icon: "account" },
  { id: "server", icon: "catalog" },
  { id: "federation", icon: "workspace" },
  { id: "controlDatabase", icon: "runs" },
  { id: "devices", icon: "trading" },
  { id: "quota", icon: "research" },
  { id: "workspace", icon: "workspace" },
  { id: "language", icon: "research" },
  { id: "updates", icon: "runs" },
  { id: "manager", icon: "runs" },
  { id: "docs", icon: "research" },
  { id: "profiles", icon: "account" },
  { id: "mihomo", icon: "runs" },
] as const;

export type SettingsSectionID=typeof SETTINGS_SECTIONS[number]["id"];
export function visibleSettingsSections(access: { manager: boolean; superAdmin: boolean }) {
  return SETTINGS_SECTIONS.filter(item =>
    (!["manager", "mihomo"].includes(item.id) || access.manager) &&
    (!["federation", "controlDatabase"].includes(item.id) || access.superAdmin));
}
