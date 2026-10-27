import React from "react";
export function FunctionPage({ title, actions, children }: { title: string; actions?: React.ReactNode; children: React.ReactNode }): React.ReactElement {
  return <section className="tr-function-page"><header className="tr-function-header"><h1>{title}</h1><div className="tr-function-actions">{actions}</div></header><div className="tr-function-body">{children}</div></section>;
}
