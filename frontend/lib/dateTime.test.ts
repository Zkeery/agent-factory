import { describe, expect, it } from "vitest";
import { formatApiDate, formatApiDateTime, parseApiInstant } from "./dateTime";

const shanghai = { timeZone: "Asia/Shanghai", hourCycle: "h23" as const };

describe("接口时间按用户时区显示", () => {
  it("没有时区的 UTC 时间在东八区显示为 20:32", () => {
    const text = formatApiDateTime("2026-10-10T12:32:00", {
      ...shanghai,
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
    expect(text).toContain("20:32");
    expect(text).not.toContain("12:32");
  });

  it("带 Z 或偏移的同一时刻解析结果一致", () => {
    const naive = parseApiInstant("2026-10-10T12:32:00").getTime();
    expect(parseApiInstant("2026-10-10T12:32:00Z").getTime()).toBe(naive);
    expect(parseApiInstant("2026-10-10T12:32:00+00:00").getTime()).toBe(naive);
    expect(parseApiInstant("2026-10-10 12:32:00").getTime()).toBe(naive);
  });

  it("跨日的 UTC 时间显示当地日期", () => {
    const day = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Shanghai", day: "2-digit" }).format(
      parseApiInstant("2026-10-10T16:30:00"),
    );
    expect(day).toBe("11");
    expect(formatApiDate("2026-10-10T16:30:00", shanghai)).toContain("11");
  });
});
