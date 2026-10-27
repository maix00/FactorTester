import React, { useState } from "react";
import { Collapse, Descriptions, Empty, Table } from "antd";
import { useTranslation } from "react-i18next";
export function ResultView({ value, depth = 0 }: { value: unknown; depth?: number }): React.ReactElement {
  const { t } = useTranslation();
  if (value === null || value === undefined) return <Empty description={t("empty")} />;
  if (Array.isArray(value)) {
    if (!value.length) return <Empty description={t("empty")} />;
    return <ResultArray value={value} />;
  }
  if (typeof value !== "object") return <span>{String(value)}</span>;
  const entries = Object.entries(value);
  const scalars = entries.filter(([, item]) => item === null || typeof item !== "object");
  const nested = entries.filter(([, item]) => item !== null && typeof item === "object");
  return <div className="tr-result-view"><Descriptions column={{ xs: 1, sm: 2, lg: 3 }} items={scalars.map(([key, item]) => ({ key, label: key, children: String(item ?? "—") }))} />
    {nested.length ? <Collapse defaultActiveKey={depth < 1 ? nested.slice(0, 2).map(([key]) => key) : []} items={nested.map(([key, item]) => ({ key, label: key,
      children: depth < 3 ? <ResultView value={item} depth={depth + 1} /> : <pre className="tr-job-detail">{JSON.stringify(item, null, 2)}</pre> }))} /> : null}</div>;
}

function ResultArray({ value }: { value: unknown[] }): React.ReactElement {
  const { t } = useTranslation(); const [page, setPage] = useState(1), [size, setSize] = useState(20);
  const current = Math.min(page, Math.max(1, Math.ceil(value.length / size)));
  const rows = value.slice((current - 1) * size, current * size).map((item, index) => ({ __row: index, ...(item !== null && typeof item === "object" ? item : { value: item }) }));
  const keys = [...new Set(rows.flatMap((row) => Object.keys(row)))].filter((key) => key !== "__row");
  return <Table rowKey="__row" size="middle" scroll={{ x: "max-content" }} dataSource={rows}
    pagination={{ current, pageSize: size, total: value.length, onChange: (next, count) => { setPage(next); setSize(count); } }}
    columns={keys.map((key) => ({ key, title: key, dataIndex: key, render: (item: unknown) => item && typeof item === "object"
      ? <details><summary>{t("details")}</summary><pre>{JSON.stringify(item, null, 2)}</pre></details> : String(item ?? "—") }))} />;
}
