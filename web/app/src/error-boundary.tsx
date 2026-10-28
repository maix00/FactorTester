import React from "react";
import { notify } from "./notifications/core.ts";
import i18n from "./i18n.ts";

type Props = { children: React.ReactNode; label?: string };
type State = { error: Error | null };

export class PageErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error): void {
    notify({
      code: `page.render:${this.props.label ?? "unknown"}`,
      type: "error",
      message: i18n.t("pageRenderFailed"),
      description: error.message,
      duration: 8,
    });
  }

  render(): React.ReactNode {
    if (this.state.error) {
      return (
        <div className="tr-page-error" role="alert">
          <strong>{i18n.t("pageRenderFailed")}</strong>
          <p>{this.state.error.message}</p>
          <button type="button" onClick={() => this.setState({ error: null })}>{i18n.t("retry")}</button>
        </div>
      );
    }
    return this.props.children;
  }
}
