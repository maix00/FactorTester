import { useSyncExternalStore } from "react";

export type AssistantResearchContext = Readonly<{
  pageId: string;
  researchId: string;
  title: string;
  section: string;
}>;

/** Visible page instances own their registration; interacting with one makes it current. */
export class AssistantResearchContexts {
  private entries = new Map<string, { value: AssistantResearchContext; order: number }>();
  private listeners = new Set<() => void>();
  private order = 0;
  private current: AssistantResearchContext | null = null;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  snapshot = (): AssistantResearchContext | null => this.current;

  set(pageId: string, context: Omit<AssistantResearchContext, "pageId"> | null): void {
    const previous = this.entries.get(pageId);
    if (!context) {
      if (!previous) return;
      this.entries.delete(pageId);
    } else {
      if (previous && previous.value.researchId === context.researchId &&
          previous.value.title === context.title && previous.value.section === context.section) return;
      this.entries.set(pageId, {value:{pageId, ...context}, order:previous?.order ?? ++this.order});
    }
    this.updateCurrent();
  }

  activate(pageId: string): void {
    const entry = this.entries.get(pageId);
    if (!entry || entry.value === this.current) return;
    entry.order = ++this.order;
    this.updateCurrent();
  }

  private updateCurrent(): void {
    let latest: { value: AssistantResearchContext; order: number } | null = null;
    for (const entry of this.entries.values()) if (!latest || entry.order > latest.order) latest = entry;
    const next = latest?.value || null;
    if (next === this.current) return;
    this.current = next;
    this.listeners.forEach(listener => listener());
  }
}

export const assistantResearchContexts = new AssistantResearchContexts();

export function useAssistantResearchContext(): AssistantResearchContext | null {
  return useSyncExternalStore(assistantResearchContexts.subscribe, assistantResearchContexts.snapshot, () => null);
}

/** Preserve the existing page-assistance wire contract without sending page content. */
export function researchAssistanceSnapshot(context: AssistantResearchContext): Record<string, unknown> {
  return {
    schema_version:1,
    page_kind:"research",
    view:{research_id:context.researchId, section:context.section},
    navigation:{schema_version:1, root_id:"page", nodes:{page:{id:"page",kind:"research",children:[]}}},
    document_schema:{type:"object",readOnly:true},
    document:{schema_version:1,document_kind:"research_context",research_id:context.researchId},
    revision:0,
  };
}
