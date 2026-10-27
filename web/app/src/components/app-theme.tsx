import React from "react";
import { ConfigProvider } from "antd";
import enUS from "antd/locale/en_US";
import zhCN from "antd/locale/zh_CN";
import { useTranslation } from "react-i18next";

/** One visual/locale contract for desktop and mobile React surfaces. */
export function AppTheme({ children }: { children: React.ReactNode }): React.ReactElement {
  const { i18n } = useTranslation();
  return <ConfigProvider locale={i18n.language.startsWith("en") ? enUS : zhCN} form={{ requiredMark: false }} theme={{ token: {
    colorPrimary: "#1677ff", colorBorder: "#dce2ea", borderRadius: 6,
    colorBgContainer: "#fff", colorBgLayout: "#fafbfd", colorText: "#202b3c", colorTextSecondary: "#697587",
    controlHeight: 36, fontSize: 14,
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif",
  }, components: { Button: { primaryShadow: "none", defaultShadow: "none" } } }}>{children}</ConfigProvider>;
}
