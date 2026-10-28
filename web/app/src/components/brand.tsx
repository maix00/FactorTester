import React from "react";
import { useTranslation } from "react-i18next";

export function Brand(): React.ReactElement {
  const { t } = useTranslation();
  return <span className="tr-brand" aria-label={t("brand.name")}><span>{t("brand.first")}</span><span>{t("brand.second")}</span></span>;
}
