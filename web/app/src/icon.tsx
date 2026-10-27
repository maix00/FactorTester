import React from "react";
import { SettingOutlined } from "@ant-design/icons";

const paths: Record<string, React.ReactNode> = {
  research: <><path d="M5 3h9l3 3v11H5z"/><path d="M14 3v4h4M8 11h6M8 14h4"/></>,
  runs: <><path d="M5 4h14v16H5z"/><path d="M8 8h8M8 12h8M8 16h5"/></>,
  trading: <><path d="M4 19V5M4 19h16"/><path d="M8 15l3-4 3 2 4-6"/></>,
  catalog: <><path d="M4 7l8-4 8 4-8 4z"/><path d="M4 7v10l8 4 8-4V7M12 11v10"/></>,
  account: <><circle cx="12" cy="8" r="3"/><path d="M5 20c0-4 3-6 7-6s7 2 7 6"/></>,
  workspace: <><path d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z"/></>,
  sidebar: <><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/></>,
  back: <><path d="M15 18l-6-6 6-6"/></>,
};

export function PageIcon({ name, className = "" }: { name?: string; className?: string }): React.ReactElement {
  if (name === "settings") return <SettingOutlined className={`tr-icon ${className}`} aria-hidden="true" />;
  const key = name && paths[name] ? name : "research";
  return (
    <svg className={`tr-icon ${className}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {paths[key]}
    </svg>
  );
}
