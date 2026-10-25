import React from "react";
import { Alert, Empty, Table } from "antd";
import type { TableProps } from "antd";

export type FTPagination = {
  page: number;
  pageSize: number;
  total: number;
  onChange: (page: number, pageSize: number) => void;
};

export function FTDataTable<T extends object>({
  columns, rows, rowKey, loading = false, pagination, error = "", empty = "暂无数据",
}: {
  columns: TableProps<T>["columns"];
  rows: T[];
  rowKey: TableProps<T>["rowKey"];
  loading?: boolean;
  pagination: FTPagination;
  error?: string;
  empty?: string;
}): React.ReactElement {
  if (error) return <Alert type="error" showIcon message="读取失败" description={error} />;
  return (
    <Table<T>
      rowKey={rowKey}
      columns={columns}
      dataSource={rows}
      loading={loading}
      size="middle"
      locale={{ emptyText: <Empty description={empty} /> }}
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
