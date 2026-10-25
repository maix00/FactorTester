import React from "react";
import { Select } from "antd";

export type FTOption = { value: string; label: string };

export function FTMultiSelectFilter({
  value, options, onChange, placeholder = "筛选", label = "筛选",
}: {
  value: string[];
  options: FTOption[];
  onChange: (value: string[]) => void;
  placeholder?: string;
  label?: string;
}): React.ReactElement {
  return (
    <Select
      mode="multiple"
      allowClear
      options={options}
      value={value}
      onChange={onChange}
      placeholder={placeholder}
      aria-label={label}
      maxTagCount="responsive"
      style={{ minWidth: 220 }}
    />
  );
}
