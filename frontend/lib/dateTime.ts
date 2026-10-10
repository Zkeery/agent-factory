const NAIVE_DATE_TIME = /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/;

/** 数据库存 UTC。没有时区的时间按 UTC 解析，再交给本地时区显示。 */
export function parseApiInstant(value: string): Date {
  const trimmed = value.trim();
  if (NAIVE_DATE_TIME.test(trimmed)) return new Date(`${trimmed.replace(" ", "T")}Z`);
  return new Date(trimmed);
}

export function formatApiDateTime(
  value: string | null | undefined,
  options: Intl.DateTimeFormatOptions = { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" },
  fallback = "—",
): string {
  if (!value) return fallback;
  const date = parseApiInstant(value);
  if (Number.isNaN(date.getTime())) return fallback;
  return date.toLocaleString("zh-CN", options);
}

export function formatApiDate(value: string | null | undefined, options?: Intl.DateTimeFormatOptions): string {
  return formatApiDateTime(value, { year: "numeric", month: "2-digit", day: "2-digit", ...options });
}

export function formatApiTime(value: string | null | undefined): string {
  return formatApiDateTime(value, { hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" });
}
