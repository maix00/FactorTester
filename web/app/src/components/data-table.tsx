import React from "react";
import { Alert, Empty, Table } from "antd";
import { useTranslation } from "react-i18next";
import type { TableProps } from "antd";

export type TRPagination = {
  page: number;
  pageSize: number;
  total: number;
  onChange: (page: number, pageSize: number) => void;
};

export function TRDataTable<T extends object>({
  columns, rows, rowKey, loading = false, pagination, error = "", empty,
}: {
  columns: TableProps<T>["columns"];
  rows: T[];
  rowKey: TableProps<T>["rowKey"];
  loading?: boolean;
  pagination: TRPagination;
  error?: string;
  empty?: string;
}): React.ReactElement {
  const { t } = useTranslation();
  if (error) return <Alert type="error" showIcon message={t("loadFailed")} description={error} />;
  return (
    <Table<T>
      rowKey={rowKey}
      columns={columns}
      dataSource={rows}
      loading={loading}
      size="middle"
      locale={{ emptyText: <Empty description={empty || t("empty")} /> }}
      pagination={{
        current: pagination.page,
        pageSize: pagination.pageSize,
        total: pagination.total,
        showSizeChanger: true,
        onChange: pagination.onChange,
      }}
    />
  );
}


/** @deprecated use TRDataTable */
export const FTDataTable = TRDataTable;
