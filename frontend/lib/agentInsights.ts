import { acceptanceStatusText, getToken } from "./factory";

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8010";

type RecordId = string | number;
export type ExecutionMode = "workflow" | "agent_team";
export type ExecutionStatus = "pending" | "running" | "interrupted" | "completed" | "failed" | "cancelled";
export type TaskStatus = "queued" | "running" | "completed" | "failed" | "interrupted";

export interface AgentTask {
  id: RecordId;
  role: string;
  title: string;
  status: TaskStatus;
  round: number;
  started_at: string | null;
  finished_at: string | null;
  input_summary: string;
  output_summary: string;
}

export interface AgentStep {
  id: RecordId;
  task_id: RecordId;
  role: string;
  round: number;
  sequence: number;
  tool: string;
  status: TaskStatus;
  summary: string;
  created_at: string;
  duration_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
}

export interface RunExecution {
  run_id: string;
  execution_mode: ExecutionMode;
  status: ExecutionStatus;
  active_role: string | null;
  limits: { max_turns_per_agent: number; max_repair_rounds: number };
  repair_rounds: number;
  resumable: boolean;
  stop_reason: string | null;
  tasks: AgentTask[];
  steps: AgentStep[];
  handoffs: { id: RecordId; from_role: string; to_role: string; round: number; reason: string; created_at: string }[];
  checks: { id: RecordId; round: number; passed: boolean; summary: string; created_at: string }[];
}

export type ReviewSource = "real" | "mock" | "unknown" | "all";
export type ReviewDays = "7" | "30" | "90" | "all";
export interface ReviewFilters { source: ReviewSource; days: ReviewDays; project_id?: string | null }
export type ReviewMetricKey = "delivery_rate" | "automatic_check_rate" | "delivery_seconds" | "execution_seconds" | "estimated_cost" | "iteration_fix_rate";

export interface ReviewMetric {
  value: number | null;
  numerator: number | null;
  denominator: number | null;
  samples: number;
  excluded: number;
  definition: string;
}

export interface ReviewRow {
  run_id: string;
  project_id: string | null;
  idea: string;
  stage: string;
  source: Exclude<ReviewSource, "all">;
  execution_mode: string;
  created_at: string;
  accepted_at: string | null;
  delivery_seconds: number | null;
  execution_seconds: number | null;
  estimated_cost: number | null;
  accounting_version: string | number | null;
  parent_run_id: string | null;
  acceptance_outcome?: "pending" | "rejected" | "accepted" | null;
  revision_created?: boolean;
}

export interface ProjectReviewData {
  generated_at: string;
  filters: ReviewFilters;
  counts: { total: number; delivered: number; failed: number; cancelled: number; pending: number; real: number; mock: number; unknown: number };
  metrics: Record<ReviewMetricKey, ReviewMetric>;
  iteration: { baseline_failed: number; comparable: number; fixed: number; pending: number; excluded: number; new_failures: number };
  currency: string;
  pricing_basis: string;
  rows: ReviewRow[];
  notes: string[];
}

export const REVIEW_METRICS: { key: ReviewMetricKey; label: string; unit: "ratio" | "seconds" | "currency" }[] = [
  { key: "delivery_rate", label: "人工交付率", unit: "ratio" },
  { key: "automatic_check_rate", label: "自动检查通过率", unit: "ratio" },
  { key: "delivery_seconds", label: "交付用时 · 中位数", unit: "seconds" },
  { key: "execution_seconds", label: "执行用时 · 中位数", unit: "seconds" },
  { key: "estimated_cost", label: "模型费用估算 · 合计", unit: "currency" },
  { key: "iteration_fix_rate", label: "迭代修复率", unit: "ratio" },
];

async function insightRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {};
  const key = process.env.NEXT_PUBLIC_FACTORY_API_KEY;
  if (key) headers["X-API-Key"] = key;
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, { ...init, headers: { ...headers, ...(init?.headers as Record<string, string> | undefined) } });
  } catch (error) {
    if (init?.signal?.aborted) throw error;
    throw new Error("连不上工厂后端，请确认服务已启动后重试。", { cause: error });
  }
  const raw = await response.text();
  let body: unknown = null;
  try { body = raw ? JSON.parse(raw) : null; } catch { body = raw; }
  if (!response.ok) {
    const error = body as { error?: { message?: string }; detail?: string } | null;
    const message = typeof error?.error?.message === "string" ? error.error.message
      : typeof error?.detail === "string" ? error.detail : `请求失败（${response.status}），请重试。`;
    throw new Error(message);
  }
  return body as T;
}

export const getRunExecution = (runId: string, signal?: AbortSignal) =>
  insightRequest<RunExecution>(`/api/v1/runs/${encodeURIComponent(runId)}/execution`, { signal, cache: "no-store" });

export async function resumeExecution(runId: string): Promise<void> {
  await insightRequest<unknown>(`/api/v1/runs/${encodeURIComponent(runId)}/execution/resume`, { method: "POST" });
}

export function getProjectReview(filters: ReviewFilters, signal?: AbortSignal): Promise<ProjectReviewData> {
  const query = new URLSearchParams({ source: filters.source, days: filters.days });
  if (filters.project_id) query.set("project_id", filters.project_id);
  return insightRequest<ProjectReviewData>(`/api/v1/metrics/review?${query}`, { signal, cache: "no-store" });
}

export function agentRoleLabel(role: string | null | undefined): string {
  return role === "builder" ? "开发 Agent" : role === "verifier" ? "验证 Agent" : role || "暂无执行者";
}

export function executionModeLabel(mode: string | undefined): string {
  return mode === "agent_team" ? "Agent 协作" : mode === "workflow" ? "固定流程" : "执行方式未记录";
}

export function reviewSourceLabel(source: string): string {
  return ({ real: "真实模型", mock: "Mock", unknown: "来源未知", all: "全部来源" } as Record<string, string>)[source] || "来源未知";
}

export function formatInsightDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total} 秒`;
  if (total < 3600) return `${Math.floor(total / 60)} 分 ${total % 60} 秒`;
  if (total < 86400) return `${Math.floor(total / 3600)} 小时 ${Math.floor(total % 3600 / 60)} 分`;
  return `${Math.floor(total / 86400)} 天 ${Math.floor(total % 86400 / 3600)} 小时`;
}

export function formatInsightCost(value: number | null | undefined, currency: string): string {
  if (value == null || !Number.isFinite(value)) return "—";
  try { return new Intl.NumberFormat("zh-CN", { style: "currency", currency, minimumFractionDigits: 2, maximumFractionDigits: 4 }).format(value); }
  catch { return `${currency} ${value.toFixed(4)}`; }
}

export function formatReviewMetric(key: ReviewMetricKey, metric: ReviewMetric, currency: string): string {
  if (metric.value == null || !Number.isFinite(metric.value) || metric.samples === 0) return "暂无样本";
  if (key.endsWith("_rate")) return `${(metric.value * 100).toFixed(1)}%`;
  if (key === "estimated_cost") return formatInsightCost(metric.value, currency);
  return formatInsightDuration(metric.value);
}

function csvCell(value: unknown): string {
  if (value == null) return '""';
  let text = String(value);
  // Text such as an idea or a definition must never become a spreadsheet formula.
  if (typeof value === "string" && /^[\s]*[=+\-@]/.test(text)) text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
}

/** Export the exact displayed snapshot, including denominators and source filters. */
export function projectReviewCsv(data: ProjectReviewData): string {
  const rows: unknown[][] = [
    ["项目复盘", "导出当前筛选结果"],
    ["生成时间", data.generated_at], ["数据来源", data.filters.source], ["时间范围（天）", data.filters.days],
    ["项目ID", data.filters.project_id], ["币种", data.currency], ["成本说明", data.pricing_basis],
    ["费用性质", "估算成本，不是服务商账单"], [],
    ["指标", "原始值", "单位", "分子", "分母", "样本数", "未计入数", "统计口径"],
    ...REVIEW_METRICS.map(({ key, label, unit }) => {
      const metric = data.metrics[key];
      return [label, metric.value, unit === "currency" ? data.currency : unit, metric.numerator, metric.denominator, metric.samples, metric.excluded, metric.definition];
    }), [],
    ["记录总数", "已交付", "失败", "取消", "待完成", "真实模型", "Mock", "来源未知"],
    [data.counts.total, data.counts.delivered, data.counts.failed, data.counts.cancelled, data.counts.pending, data.counts.real, data.counts.mock, data.counts.unknown], [],
    ["迭代基线未通过", "可比较", "已修复", "待验证", "未计入", "新增未通过"],
    [data.iteration.baseline_failed, data.iteration.comparable, data.iteration.fixed, data.iteration.pending, data.iteration.excluded, data.iteration.new_failures], [],
    ["Run ID", "项目ID", "想法", "阶段", "来源", "执行方式", "创建时间", "验收时间", "交付用时（秒）", "执行用时（秒）", "估算成本", "币种", "计费口径版本", "父Run ID"],
    ...data.rows.map((row) => [row.run_id, row.project_id, row.idea, acceptanceStatusText(row) || row.stage, row.source, row.execution_mode, row.created_at, row.accepted_at, row.delivery_seconds, row.execution_seconds, row.estimated_cost, data.currency, row.accounting_version, row.parent_run_id]),
    [], ["说明"], ...data.notes.map((note) => [note]),
  ];
  return "\uFEFF" + rows.map((row) => row.map(csvCell).join(",")).join("\r\n");
}

export function downloadProjectReview(data: ProjectReviewData): void {
  const url = URL.createObjectURL(new Blob([projectReviewCsv(data)], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `project-review-${data.filters.source}-${data.filters.days}-${data.generated_at.slice(0, 10)}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
