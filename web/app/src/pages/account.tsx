import React from "react";
import { useTranslation } from "react-i18next";
import { FunctionPage } from "../components/function-page.tsx";
import { AccountSummary } from "../components/account-summary.tsx";

export function AccountPage(): React.ReactElement {
  const { t } = useTranslation();
  return <FunctionPage title={t("nav.account")}><AccountSummary /></FunctionPage>;
}
