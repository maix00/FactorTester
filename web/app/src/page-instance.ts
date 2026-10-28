import React, { createContext, useContext } from "react";
export type PageArguments = { sourceFamilyId?: string; productName?: string; productTitle?: string; contractUid?: string; jobId?: string; workspaceId?: string; section?: string; factorRef?: string; create?: "factor" | "strategy"; servicePort?: number; serverId?: string; executionNodeId?: string };
export interface PageInstance { id: string; pageId: string; mobile: boolean; active?: boolean; args: PageArguments; open: (pageId: string, args?: PageArguments) => void; back?: () => void }
let sequence = 0;
export function newPageInstanceId(pageId: string): string { return `tr-${pageId}-${Date.now().toString(36)}-${++sequence}`; }
const Context = createContext<PageInstance>({ id: "standalone", pageId: "", mobile: false, args: {}, open: () => undefined });
export const PageInstanceProvider = Context.Provider;
export function usePageInstance(): PageInstance { return useContext(Context); }
