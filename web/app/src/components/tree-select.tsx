import React from "react";
import { TreeSelect } from "antd";

export type TRTreeOption = {
  value: string;
  title: string;
  children?: TRTreeOption[];
  selectable?: boolean;
};

export function TRTreeSelectFilter({
  value, treeData, onChange, placeholder = "选择", multiple = true, label = "选择",
}: {
  value: string | string[];
  treeData: TRTreeOption[];
  onChange: (value: string | string[]) => void;
  placeholder?: string;
  multiple?: boolean;
  label?: string;
}): React.ReactElement {
  return (
    <TreeSelect
      treeData={treeData}
      value={value}
      onChange={onChange}
      placeholder={placeholder}
      aria-label={label}
      multiple={multiple}
      treeCheckable={multiple}
      showCheckedStrategy={TreeSelect.SHOW_PARENT}
      allowClear
      showSearch
      treeNodeFilterProp="title"
      style={{ minWidth: 240 }}
    />
  );
}
