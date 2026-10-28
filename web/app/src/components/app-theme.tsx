import React from "react";
import { ConfigProvider } from "antd";
import enUS from "antd/es/locale/en_US";
import zhCN from "antd/es/locale/zh_CN";
import { useTranslation } from "react-i18next";

/** One visual/locale contract for desktop and mobile React surfaces. */
export function AppTheme({ children }: { children: React.ReactNode }): React.ReactElement {
  const { i18n } = useTranslation();
  return <ConfigProvider getPopupContainer={(trigger) => trigger?.closest<HTMLElement>(".tr-tab-layer, .tr-mobile-instance") || document.body} locale={i18n.language.startsWith("en") ? enUS : zhCN} form={{ requiredMark: false }} theme={{ token: {
    colorPrimary: "#1677ff", colorBorder: "#dce2ea", borderRadius: 6,
    colorBgContainer: "#fff", colorBgLayout: "#fafbfd", colorText: "#202b3c", colorTextSecondary: "#697587",
    controlHeight: 36, fontSize: 14,
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif",
  }, components: { Table: { rowSelectedBg: "#eaf2ff", rowSelectedHoverBg: "#eaf2ff", rowHoverBg: "#f6f8fc", headerBg: "#f3f6fb" }, Button: { primaryShadow: "none", defaultShadow: "none" } } }}>{children}</ConfigProvider>;
}
