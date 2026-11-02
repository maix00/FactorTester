import React, { createContext, useContext, useEffect, useState } from "react";
import { ConfigProvider, theme as antTheme } from "antd";
import enUS from "antd/es/locale/en_US";
import zhCN from "antd/es/locale/zh_CN";
import { useTranslation } from "react-i18next";

type ColorMode = "light" | "dark" | "system";
const MODE_KEY = "traderesearch.color-mode";
const AppearanceContext = createContext<{mode: ColorMode; setMode: (value: ColorMode) => void}>({mode:"system", setMode: () => {}});
export const useAppearance = () => useContext(AppearanceContext);

/** One visual/locale contract for desktop and mobile React surfaces. */
export function AppTheme({ children }: { children: React.ReactNode }): React.ReactElement {
  const { i18n } = useTranslation();
  const [mode, setMode] = useState<ColorMode>(() => {
    try { const value = localStorage.getItem(MODE_KEY); return value === "dark" || value === "system" ? value : "light"; }
    catch { return "light"; }
  });
  const [systemDark, setSystemDark] = useState(() => window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false);
  useEffect(() => {
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!media) return;
    const update = (event: MediaQueryListEvent) => setSystemDark(event.matches);
    media.addEventListener("change", update); return () => media.removeEventListener("change", update);
  }, []);
  const dark = mode === "dark" || (mode === "system" && systemDark);
  useEffect(() => { document.documentElement.dataset.trTheme = dark ? "dark" : "light"; }, [dark]);
  const selectMode = (value: ColorMode) => { setMode(value); try { localStorage.setItem(MODE_KEY, value); } catch { /* ephemeral preference */ } };
  return <AppearanceContext.Provider value={{mode, setMode:selectMode}}><ConfigProvider getPopupContainer={(trigger) => trigger?.closest<HTMLElement>(".tr-tab-layer, .tr-mobile-instance") || document.body} locale={i18n.language.startsWith("en") ? enUS : zhCN} form={{ requiredMark: false }} theme={{ algorithm:dark ? antTheme.darkAlgorithm : antTheme.defaultAlgorithm, token: {
    colorPrimary: "#1677ff", borderRadius: 6,
    ...(dark ? {colorBorder:"#394150",colorBgContainer:"#1d2430",colorBgLayout:"#121720",colorText:"#e7ebf2",colorTextSecondary:"#aab4c3"} : {colorBorder:"#dce2ea",colorBgContainer:"#fff",colorBgLayout:"#fafbfd",colorText:"#202b3c",colorTextSecondary:"#697587"}),
    controlHeight: 36, fontSize: 14,
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif",
  }, components: { Table: dark ? {} : { rowSelectedBg: "#eaf2ff", rowSelectedHoverBg: "#eaf2ff", rowHoverBg: "#f6f8fc", headerBg: "#f3f6fb" }, Button: { primaryShadow: "none", defaultShadow: "none" } } }}>{children}</ConfigProvider></AppearanceContext.Provider>;
}
