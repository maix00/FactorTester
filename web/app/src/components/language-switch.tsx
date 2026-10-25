import React from "react";
import { useTranslation } from "react-i18next";
import { Select } from "antd";
import i18n from "../i18n.ts";

export function LanguageSwitch({ compact = false }: { compact?: boolean }): React.ReactElement {
  const { t } = useTranslation();
  return (
    <Select
      size={compact ? "small" : "middle"}
      aria-label={t("language")}
      value={i18n.language.startsWith("en") ? "en" : "zh"}
      options={[{ value: "zh", label: "中文" }, { value: "en", label: "English" }]}
      onChange={(value) => {
        i18n.changeLanguage(value);
        localStorage.setItem("tr.language", value);
        document.documentElement.lang = value === "en" ? "en" : "zh-Hans";
      }}
      style={{ width: compact ? 88 : 110 }}
    />
  );
}
