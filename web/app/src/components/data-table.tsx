import React, { useState } from "react";
import { Alert, Button, Empty, Select, Table } from "antd";
import { ExpandOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type { TableProps } from "antd";
import { usePageInstance } from "../page-instance.ts";
import { DetailsPanel } from "./details-panel.tsx";

export type TRPagination = {
  page: number;
  pageSize: number;
  total: number;
  mode?: "cursor";
  hasMore?: boolean;
  hideOnSinglePage?: boolean;
  onChange: (page: number, pageSize: number) => void;
};

export function TRDataTable<T extends object>({
  columns, rows, rowKey, loading = false, pagination, error = "", empty, rowSelection, onRow, clientFiltering = false,
}: {
  columns: TableProps<T>["columns"];
  rows: T[];
  rowKey: TableProps<T>["rowKey"];
  loading?: boolean;
  pagination: TRPagination;
  error?: string;
  empty?: string;
  rowSelection?: TableProps<T>["rowSelection"];
  onRow?: TableProps<T>["onRow"];
  clientFiltering?: boolean;
}): React.ReactElement {
  const { t } = useTranslation();
  const { mobile } = usePageInstance();
  const [expanded,setExpanded]=useState(false);
  const [filters,setFilters]=useState<Record<string,(React.Key | boolean)[] | null>>({});
  if (error) return <Alert type="error" showIcon message={t("loadFailed")} description={error} />;
  const visibleColumns=columns?.map(column=>{
    if(!column || !("filters" in column) || !column.filters)return column;
    const key=String(column.key ?? ("dataIndex" in column ? column.dataIndex : ""));
    return Object.prototype.hasOwnProperty.call(filters,key) ? {...column,filteredValue:filters[key]} : column;
  });
  const content = (
    <><Table<T>
      rowKey={rowKey}
      rowSelection={rowSelection}
      onRow={onRow}
      scroll={{ x: "max-content" }}
      columns={visibleColumns}
      onChange={(_pagination, nextFilters)=>setFilters(nextFilters)}
      dataSource={rows}
      loading={loading}
      size="middle"
      locale={{ emptyText: <Empty description={empty || t("empty")} /> }}
      pagination={pagination.mode === "cursor" ? false : {
        current: pagination.page,
        pageSize: pagination.pageSize,
        ...(clientFiltering ? {} : {total: pagination.total}),
        showSizeChanger: true,
        hideOnSinglePage: pagination.hideOnSinglePage,
        onChange: pagination.onChange,
      }}
    />{pagination.mode === "cursor" ? <nav className="tr-cursor-pagination" aria-label={t("pagination.label")}>
      <Button disabled={loading || pagination.page <= 1} onClick={() => pagination.onChange(pagination.page - 1, pagination.pageSize)}>{t("pagination.previous")}</Button>
      <span>{t("pagination.page", { page: pagination.page })}</span>
      <Button disabled={loading || !pagination.hasMore} onClick={() => pagination.onChange(pagination.page + 1, pagination.pageSize)}>{t("pagination.next")}</Button>
      <Select aria-label={t("pagination.pageSize")} disabled={loading} value={pagination.pageSize} options={[20, 50, 100].map((value) => ({ value, label: String(value) }))} onChange={(value) => pagination.onChange(1, value)} />
    </nav> : null}</>
  );
  return <>{mobile && !expanded ? <div className="tr-table-expand"><Button type="text" icon={<ExpandOutlined />} onClick={()=>setExpanded(true)}>{t("table.expand")}</Button></div> : null}
    {expanded ? <DetailsPanel title={t("table.title")} forceFullscreen onClose={()=>setExpanded(false)}>{content}</DetailsPanel> : content}</>;
}


/** @deprecated use TRDataTable */
export const FTDataTable = TRDataTable;
