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
export const ADMIN_SETTINGS_SECTIONS = ["federation", "controlDatabase", "manager", "mihomo"] as const satisfies readonly SettingsSectionID[];

export function visibleSettingsSections(access: {
  manager: boolean;
  superAdmin: boolean;
}) {
  void access;
  return SETTINGS_SECTIONS.filter(item => !ADMIN_SETTINGS_SECTIONS.includes(item.id as typeof ADMIN_SETTINGS_SECTIONS[number]));
}
