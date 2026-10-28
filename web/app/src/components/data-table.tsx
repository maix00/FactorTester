import React from "react";
import { Alert, Button, Empty, Select, Table } from "antd";
import { useTranslation } from "react-i18next";
import type { TableProps } from "antd";

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
  columns, rows, rowKey, loading = false, pagination, error = "", empty, rowSelection, onRow,
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
}): React.ReactElement {
  const { t } = useTranslation();
  if (error) return <Alert type="error" showIcon message={t("loadFailed")} description={error} />;
  return (
    <><Table<T>
      rowKey={rowKey}
      rowSelection={rowSelection}
      onRow={onRow}
      scroll={{ x: "max-content" }}
      columns={columns}
      dataSource={rows}
      loading={loading}
      size="middle"
      locale={{ emptyText: <Empty description={empty || t("empty")} /> }}
      pagination={pagination.mode === "cursor" ? false : {
        current: pagination.page,
        pageSize: pagination.pageSize,
        total: pagination.total,
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
}


/** @deprecated use TRDataTable */
export const FTDataTable = TRDataTable;
