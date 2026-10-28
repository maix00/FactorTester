import { useSyncExternalStore } from "react";
const subscribe = (listener: () => void): (() => void) => {
  const media = window.matchMedia("(max-width: 760px)");
  media.addEventListener("change", listener);
  return () => media.removeEventListener("change", listener);
};
const snapshot = (): boolean => window.matchMedia("(max-width: 760px)").matches;
export function useCompactLayout(): boolean { return useSyncExternalStore(subscribe, snapshot, () => false); }
