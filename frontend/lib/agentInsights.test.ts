import { afterEach, describe, expect, it, vi } from "vitest";
import {
  formatInsightCost, formatInsightDuration, formatReviewMetric, getProjectReview,
  getRunExecution, projectReviewCsv, resumeExecution, type ProjectReviewData, type ReviewMetric,
} from "./agentInsights";

const metric = (patch: Partial<ReviewMetric> = {}): ReviewMetric => ({
  value: null, numerator: null, denominator: null, samples: 0, excluded: 1,
  definition: "按当前筛选计算，待完成样本单列。", ...patch,
});

const snapshot: ProjectReviewData = {
  generated_at: "2026-10-05T12:00:00Z",
  filters: { source: "real", days: "all", project_id: "project-1" },
  counts: { total: 2, delivered: 0, failed: 1, cancelled: 0, pending: 1, real: 2, mock: 0, unknown: 0 },
  metrics: {
    delivery_rate: metric({ value: 0, numerator: 0, denominator: 1, samples: 1 }),
    automatic_check_rate: metric({ value: 0.5, numerator: 1, denominator: 2, samples: 2, excluded: 0 }),
    delivery_seconds: metric(), execution_seconds: metric({ value: 65, samples: 2, excluded: 0 }),
    estimated_cost: metric(), iteration_fix_rate: metric(),
  },
  iteration: { baseline_failed: 1, comparable: 0, fixed: 0, pending: 1, excluded: 0, new_failures: 0 },
  currency: "USD", pricing_basis: "基于已记录用量估算。",
  rows: [{
    run_id: "run-1", project_id: "project-1", idea: '=HYPERLINK("https://example.test","标题")\n第二行',
    stage: "awaiting_acceptance", source: "real", execution_mode: "agent_team", created_at: "2026-10-05T11:00:00Z",
    accepted_at: null, delivery_seconds: null, execution_seconds: 65, estimated_cost: null,
    accounting_version: null, parent_run_id: "parent-1",
  }],
  notes: ["未记录的历史成本不按 0 计算。"],
};

afterEach(() => vi.unstubAllGlobals());

describe("执行与复盘请求", () => {
  it("筛选只发送到本项目API，并以请求头传递鉴权", async () => {
    vi.stubGlobal("window", {});
    vi.stubGlobal("localStorage", { getItem: () => "private-session-token" });
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(snapshot)));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();
    await getProjectReview({ source: "mock", days: "30", project_id: "project / 1" }, controller.signal);
    const url = new URL(fetchMock.mock.calls[0][0]);
    expect(url.pathname).toBe("/api/v1/metrics/review");
    expect(Object.fromEntries(url.searchParams)).toEqual({ source: "mock", days: "30", project_id: "project / 1" });
    expect(url.href).not.toContain("private-session-token");
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ headers: { Authorization: "Bearer private-session-token" }, signal: controller.signal, cache: "no-store" });
  });

  it("执行记录按Run请求，恢复只提交一次POST且不要求响应正文", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ run_id: "run/1" })))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    await getRunExecution("run/1");
    await resumeExecution("run/1");
    expect(fetchMock.mock.calls[0][0]).toContain("/api/v1/runs/run%2F1/execution");
    expect(fetchMock.mock.calls[1][0]).toContain("/api/v1/runs/run%2F1/execution/resume");
    expect(fetchMock.mock.calls[1][1].method).toBe("POST");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("后端失败原因可见，取消读取保留原取消错误", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { message: "该版本不能恢复" } }), { status: 409 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(resumeExecution("run-1")).rejects.toThrow("该版本不能恢复");
    const controller = new AbortController();
    controller.abort();
    const abort = new DOMException("aborted", "AbortError");
    fetchMock.mockRejectedValueOnce(abort);
    await expect(getRunExecution("run-1", controller.signal)).rejects.toBe(abort);
  });
});

describe("复盘口径与导出", () => {
  it("缺少样本不展示零成绩，真实零通过率仍按0展示", () => {
    expect(formatReviewMetric("delivery_rate", metric(), "USD")).toBe("暂无样本");
    expect(formatReviewMetric("delivery_rate", metric({ value: 0, samples: 0 }), "USD")).toBe("暂无样本");
    expect(formatReviewMetric("delivery_rate", snapshot.metrics.delivery_rate, "USD")).toBe("0.0%");
    expect(formatInsightDuration(null)).toBe("—");
    expect(formatInsightCost(null, "USD")).toBe("—");
    expect(formatInsightDuration(0)).toBe("0 秒");
  });

  it("导出当前筛选、分母与样本数，空成本不变成零", () => {
    const csv = projectReviewCsv(snapshot);
    expect(csv.startsWith("\uFEFF")).toBe(true);
    expect(csv).toContain('"数据来源","real"');
    expect(csv).toContain('"时间范围（天）","all"');
    expect(csv).toContain('"项目ID","project-1"');
    expect(csv).toContain('"人工交付率","0","ratio","0","1","1","1"');
    expect(csv).toContain('"模型费用估算 · 合计","","USD","","","0","1"');
    expect(csv).toContain('"样本数","未计入数","统计口径"');
    expect(csv).toContain("估算成本，不是服务商账单");
    expect(csv).toContain('"迭代基线未通过","可比较","已修复","待验证","未计入","新增未通过"');
    expect(csv).toContain('"待验收"');
    const rejected = {
      ...snapshot,
      rows: [{
        ...snapshot.rows[0],
        stage: "awaiting_acceptance",
        acceptance_outcome: "rejected" as const,
        revision_created: true,
      }],
    };
    expect(projectReviewCsv(rejected)).toContain('"验收未通过 · 已生成修改版"');
  });

  it("CSV对想法里的公式前缀和引号换行安全转义，不改原记录", () => {
    const csv = projectReviewCsv(snapshot);
    expect(csv).toContain('"\'=HYPERLINK(""https://example.test"",""标题"")\n第二行"');
    expect(snapshot.rows[0].idea.startsWith("=")).toBe(true);
    const modified = { ...snapshot, notes: ["  @SUM(1+1)"] };
    expect(projectReviewCsv(modified)).toContain('"\'  @SUM(1+1)"');
  });
});
