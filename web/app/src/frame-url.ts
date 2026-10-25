export function pageFrameSrc(route: string, canvas = false): string {
  const query = canvas ? "presentation=canvas" : "presentation=embedded";
  return `${route}${route.includes("?") ? "&" : "?"}${query}`;
}
