import i18n from "./i18n.ts";

export function currentLocale(): string {
  return i18n.language.startsWith("en") ? "en-US" : "zh-CN";
}

export function formatNumber(value: number, options: Intl.NumberFormatOptions = {}): string {
  return new Intl.NumberFormat(currentLocale(), options).format(value);
}

export function formatMoney(value: number, currency: string, options: Intl.NumberFormatOptions = {}): string {
  return new Intl.NumberFormat(currentLocale(), { style: "currency", currency, ...options }).format(value);
}

export function formatDate(
  value: string | number | Date,
  options: Intl.DateTimeFormatOptions & { timeZone?: string } = {},
): string {
  const date = value instanceof Date ? value : new Date(value);
  return new Intl.DateTimeFormat(currentLocale(), options).format(date);
}
