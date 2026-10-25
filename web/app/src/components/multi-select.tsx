import React from "react";
import { Select } from "antd";

export type TROption = { value: string; label: string };

export function TRMultiSelectFilter({
  value, options, onChange, placeholder = "筛选", label = "筛选",
}: {
  value: string[];
  options: TROption[];
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


/** @deprecated use TRMultiSelectFilter */
export const FTMultiSelectFilter = TRMultiSelectFilter;
