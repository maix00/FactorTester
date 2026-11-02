import React, { createContext, useContext } from "react";
import { Button, Tooltip } from "antd";
import { InfoCircleOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { objectReferenceLabel, type ObjectReferenceValue } from "../object-reference.ts";
import { useAuth } from "../auth.tsx";

export const ObjectReferenceContext = createContext<((value: ObjectReferenceValue) => void) | null>(null);

/** A reference is a button, not an unverified URL or a nested selection action. */
export function ObjectReference({ value, icon = false }: { value: ObjectReferenceValue; icon?: boolean }): React.ReactElement {
  const open = useContext(ObjectReferenceContext);
  const { t } = useTranslation();
  const { session } = useAuth();
  const label = objectReferenceLabel(value,session);
  if (!value.ref || !open) return <span>{label || "—"}</span>;
  const action = t("objectReference.open", { name: label });
  if (icon) return <Tooltip title={action}><Button type="link" size="small" icon={<InfoCircleOutlined />} aria-label={action}
    onClick={(event) => { event.stopPropagation(); open(value); }} /></Tooltip>;
  return <button type="button" className="tr-table-link tr-object-reference" aria-label={action}
    onClick={(event) => { event.stopPropagation(); open(value); }}>{label}</button>;
}
