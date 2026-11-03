import React, { useCallback, useMemo, useState } from "react";
import { Button, Input, Tooltip } from "antd";
import { CloseOutlined, InfoCircleOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { ProductTree } from "./product-tree.tsx";
import { TRDataTable } from "./data-table.tsx";
import { readProductPaths } from "../product-selection.ts";

/** One editor for groups, category entries and configuration group creation. */
export function ProductPathPicker({ value, onChange, disabled = false, categoryIds,
  allowExclusions = true, label, multiple = true, treeOpen = true, onTreeOpenChange }: {
  value: string; onChange: (text: string) => void; disabled?: boolean;
  categoryIds?: readonly string[]; allowExclusions?: boolean; label?: string; multiple?: boolean;
  treeOpen?: boolean; onTreeOpenChange?: (open: boolean) => void;
}): React.ReactElement {
  const { t } = useTranslation();
  const paths = useMemo(() => readProductPaths(value), [value]);
  const change = useCallback((next: string[]) => onChange(next.join("\n")), [onChange]);
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(5);
  const [advanced, setAdvanced] = useState(false);
  const current = Math.min(page, Math.max(1, Math.ceil(paths.length / size)));
  return <div className="tr-product-path-picker">
    {onTreeOpenChange ? <Button size="small" onClick={() => onTreeOpenChange(!treeOpen)}>{t(treeOpen ? "productSelection.closeTree" : "productSelection.choose")}</Button> : null}
    {treeOpen ? <ProductTree categoryIds={categoryIds} selection={{ paths, readOnly: disabled, multiple, leafOnly: false, allowExclusions,
      onChange: disabled ? undefined : change }} /> : null}
    <TRDataTable<{ path: string }> rows={paths.slice((current - 1) * size, current * size).map(path => ({ path }))} rowKey="path"
      columns={[{ key: "path", title: <span className="tr-product-rules-heading">{t("productSelection.rules", { count: paths.length })}<Tooltip title={t("productSelection.pathHint")}><InfoCircleOutlined aria-label={t("productSelection.ruleHelp")} /></Tooltip></span>, render: (_, row) => <code>{row.path}</code> },
        { key: "remove", width: 80, title: t("productSelection.action"), render: (_, row) => <Tooltip title={t("productSelection.remove")}><Button size="small" type="text" icon={<CloseOutlined />} disabled={disabled}
          aria-label={`${t("productSelection.remove")} ${row.path}`} onClick={() => onChange(paths.filter(path => path !== row.path).join("\n"))} /></Tooltip> }]}
      pagination={{ page: current, pageSize: size, total: paths.length, hideOnSinglePage: true, onChange: (p,s) => { setPage(p); setSize(Math.min(s,100)); } }} />
    <details onToggle={event => setAdvanced(event.currentTarget.open)}><summary>{t("productSelection.advanced")}</summary>{advanced ? <><p className="tr-product-tree-hint">{t(allowExclusions ? "productSelection.preserveHint" : "productSelection.positiveHint")}</p>
      <Input.TextArea aria-label={label || t("productGroup.paths")} disabled={disabled} value={value} rows={6}
        onChange={event => onChange(event.target.value)} />
      </> : null}
    </details>
  </div>;
}
