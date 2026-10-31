import React, { createContext, useCallback, useContext, useMemo, useState } from "react";
import { useLocalResearch } from "./use-local-research.ts";
import { useLocalReportSync } from "./use-local-report-sync.ts";

type SessionProjection = Parameters<typeof useLocalResearch>[0];
type ContextValue = ReturnType<typeof useLocalResearch> & { syncRevision: number; requestSync: () => void };
const LocalResearchContext = createContext<ContextValue | null>(null);

/** One native binding and one bounded synchronization loop per authenticated app. */
export function LocalResearchProvider({ session, mobile, children }: { session: SessionProjection; mobile: boolean; children: React.ReactNode }): React.ReactElement {
  const local = useLocalResearch(session, mobile);
  const [syncRevision, setSyncRevision] = useState(0);
  const changed = useCallback(() => setSyncRevision(value => value + 1), []);
  const requestSync = useLocalReportSync(local.client, local.capabilities, true, changed);
  const value = useMemo(() => ({ ...local, syncRevision, requestSync }), [local.key, local.phase, local.code, local.client, local.capabilities, local.retry, syncRevision, requestSync]);
  return <LocalResearchContext.Provider value={value}>{children}</LocalResearchContext.Provider>;
}

export function useLocalResearchContext(): ContextValue {
  const value = useContext(LocalResearchContext);
  if (!value) throw new Error("LocalResearchProvider is required");
  return value;
}
