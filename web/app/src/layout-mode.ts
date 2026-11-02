/** Select the mobile shell independently of device orientation. */
export function mobileLayout(narrow: boolean, userAgent: string, platform: string, maxTouchPoints: number): boolean {
  return narrow || /iPhone|iPad|iPod|Android/i.test(userAgent)
    || (platform === "MacIntel" && maxTouchPoints > 1);
}
