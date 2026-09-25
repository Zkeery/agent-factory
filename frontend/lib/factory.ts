"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type Stage =
  | "idea_submitted"
  | "clarifying"
  | "awaiting_answers"
  | "prd_drafting"
  | "awaiting_prd_confirm"
  | "building"
  | "testing"
  | "deploying"
  | "evidence_ready"
  | "gate_passed"
  | "awaiting_acceptance"
  | "delivered"
  | "gate_failed"
  | "failed"
  | "cancelled";

export interface Decision {
  code: string;
  question: string;
  options: string;
  recommendation: string;
  consequence: string;
  answer: string | null;
  status: string;
  is_critical: boolean;
}

export interface Evidence {
  stage: string;
  title: string;
  content_path: string;
  content?: string;
}

export interface RunMetric {
  duration_seconds: number;
  cost_estimate: number;
  prompt_tokens: number;
  completion_tokens: number;
}

export interface Run {
  id: string;
  idea: string;
  status: string;
  current_stage: Stage;
  failure_reason: string | null;
  failure_code?: string;
  project_id?: string | null;
  workspace_write_authorized?: boolean;
  workspace_exec_authorized?: boolean;
  workspace_always_allow?: boolean;
  llm_provider?: string;
  llm_model?: string;
  auto_schedule_id?: string | null;
  decisions: Decision[];
  evidence: Evidence[];
  metric: RunMetric | null;
}

export interface Metrics {
  total_runs: number;
  ship_rate: number;
  avg_duration: number;
  avg_cost: number;
  quality_rate: number | null;
  scored_runs: number;
}

export interface RunSummary {
  id: string;
  idea: string;
  current_stage: Stage;
  status: string;
  created_at: string;
  project_id?: string | null;
  auto_schedule_id?: string | null;
}

export interface RunList {
  runs: RunSummary[];
}

// 前端直连后端（后端已开 CORS），SSE 流式不走 Next.js 代理（代理会缓冲）
const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8010";

const TOKEN_KEY = "factory_token";
export const getToken = () => (typeof window !== "undefined" ? localStorage.getItem(TOKEN_KEY) : null);
export const setToken = (t: string) => localStorage.setItem(TOKEN_KEY, t);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  const key = process.env.NEXT_PUBLIC_FACTORY_API_KEY;
  if (key) headers["X-API-Key"] = key;
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return headers;
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = { ...authHeaders(), ...(init?.headers as Record<string, string> | undefined) };
  let res: Response;
  try {
    res = await fetch(BASE + path, { ...init, headers });
  } catch (err) {
    const tip =
      "连不上工厂后端（默认 http://127.0.0.1:8010）。请确认后端已启动后重试。";
    throw new Error(tip, { cause: err });
  }
  const raw = await res.text();
  let data: unknown = null;
  if (raw) {
    try {
      data = JSON.parse(raw);
    } catch {
      data = raw;
    }
  }
  if (!res.ok) {
    const obj = data as { error?: { message?: string }; detail?: string | { msg?: string }[] } | null;
    const msg =
      (obj && typeof obj === "object" && obj.error?.message) ||
      (obj && typeof obj === "object" && typeof obj.detail === "string" && obj.detail) ||
      (typeof data === "string" && data) ||
      `请求失败（${res.status}）`;
    throw new Error(msg);
  }
  return data as T;
}


export interface LlmProfile {
  id: string;
  label: string;
  available: boolean;
  model: string;
}

export interface LlmProfiles {
  default_provider: string;
  profiles: LlmProfile[];
}

export interface ComparePrdVariant {
  provider: string;
  model: string;
  prd: Record<string, unknown> | null;
  prompt_tokens: number;
  completion_tokens: number;
  error: string | null;
}

export interface ComparePrdResult {
  variants: ComparePrdVariant[];
}

export const createRun = (
  idea: string,
  opts?: {
    project_id?: string;
    project_name?: string;
    workspace_path?: string;
    llm_provider?: string;
  },
) =>
  api<Run>("/api/v1/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ idea, ...(opts || {}) }),
  });

export const getLlmProfiles = () => api<LlmProfiles>("/api/v1/llm/profiles");

export const comparePrd = (idea: string, decisions: { code?: string; question?: string; answer?: string }[] = []) =>
  api<ComparePrdResult>("/api/v1/llm/compare-prd", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ idea, decisions }),
  });

export const getRun = (id: string) => api<Run>(`/api/v1/runs/${id}`);

export const answerDecision = (id: string, code: string, answer: string) =>
  api<Run>(`/api/v1/runs/${id}/decisions/${code}/answer`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answer }),
  });

export const confirmPrd = (id: string) =>
  api<Run>(`/api/v1/runs/${id}/confirm-prd`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirmed: true }),
  });

export const rejectPrd = (id: string) =>
  api<Run>(`/api/v1/runs/${id}/confirm-prd`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirmed: false }),
  });

export const cancelRun = (id: string) =>
  api<Run>(`/api/v1/runs/${id}/cancel`, { method: "POST" });

export const retryRun = (id: string) =>
  api<Run>(`/api/v1/runs/${id}/retry`, { method: "POST" });

/** 闸门失败就地重测：同 Run id，从 testing 续跑。 */
export const retestRun = (id: string) =>
  api<Run>(`/api/v1/runs/${id}/retest`, { method: "POST" });

/** 闸门失败 / 失败：可尝试「仅重测」（后端仍会校验磁盘代码）。 */
export function canRetestInPlace(stage: Stage | null | undefined): boolean {
  return stage === "gate_failed" || stage === "failed";
}

/** 失败 / 闸门失败 / 已取消：可「整段重跑」。 */
export function canFullRetry(stage: Stage | null | undefined): boolean {
  return stage === "gate_failed" || stage === "failed" || stage === "cancelled";
}


export const scoreRun = (id: string, decision: number, prd: number, code: number) =>
  api<Run>(`/api/v1/runs/${id}/score`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision, prd, code }),
  });

export const getMetrics = () => api<Metrics>("/api/v1/metrics");

export const getRunList = () => api<RunList>("/api/v1/runs");

/* ---------- 登录/账号 ---------- */
export interface AuthResult {
  token: string;
  phone: string;
}

export const requestCode = (phone: string) =>
  api<{ phone: string; mock_code: string | null }>("/api/v1/auth/request-code", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ phone }),
  });

export const login = (phone: string, code: string) =>
  api<AuthResult>("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ phone, code }),
  });

export const fetchMe = () => api<{ phone: string }>("/api/v1/auth/me");

/* ---------- 成品预览 ---------- */
export interface AppRunStatus {
  running: boolean;
  url: string | null;
  port: number | null;
}

export const startApp = (id: string) =>
  api<AppRunStatus>(`/api/v1/runs/${id}/start`, { method: "POST" });

export const stopApp = (id: string) =>
  api<AppRunStatus>(`/api/v1/runs/${id}/stop`, { method: "POST" });

export const getAppStatus = (id: string) =>
  api<AppRunStatus>(`/api/v1/runs/${id}/app-status`);

/** 预览运行态短文案（右栏展示 / 单测）。 */
export function summarizeAppStatus(status: AppRunStatus | null | undefined): string {
  if (!status || !status.running) return "未运行";
  if (status.port != null) return `运行中 · 端口 ${status.port}`;
  return "运行中";
}

export interface WorkspaceSyncResult {
  ok: boolean;
  target: string;
  files_copied: number;
}

export const authorizeWorkspace = (
  id: string,
  body: { scopes: ("write" | "exec")[]; always_for_run?: boolean; role: ViewRole },
) =>
  api<Run>(`/api/v1/runs/${id}/workspace/authorize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      scopes: body.scopes,
      always_for_run: Boolean(body.always_for_run),
      role: body.role,
    }),
  });

export const syncWorkspace = (id: string) =>
  api<WorkspaceSyncResult>(`/api/v1/runs/${id}/workspace/sync`, { method: "POST" });

/** 是否仍需弹确认：always 或对应 scope 已授权则否。 */
export function needsWorkspaceAuth(run: Run | null | undefined, scope: "write" | "exec"): boolean {
  if (!run) return true;
  if (run.workspace_always_allow) return false;
  if (scope === "write") return !run.workspace_write_authorized;
  return !run.workspace_exec_authorized;
}

/** 仅开发者可勾选「本 Run 始终允许」。 */
export function canShowAlwaysAllow(role: ViewRole | string): boolean {
  return role === "dev";
}

export const eventsUrl = (id: string) => {
  const params = new URLSearchParams();
  const key = process.env.NEXT_PUBLIC_FACTORY_API_KEY;
  if (key) params.set("api_key", key);
  const token = getToken();
  if (token) params.set("token", token);
  const qs = params.toString();
  return `${BASE}/api/v1/runs/${id}/events${qs ? `?${qs}` : ""}`;
};

export const STAGE_CN: Record<Stage, string> = {
  idea_submitted: "提交想法",
  clarifying: "澄清中",
  awaiting_answers: "等待回答",
  prd_drafting: "生成 PRD",
  awaiting_prd_confirm: "待确认 PRD",
  building: "构建中",
  testing: "测试中",
  deploying: "部署中",
  evidence_ready: "整理证据",
  gate_passed: "自动闸门通过",
  awaiting_acceptance: "待验收",
  delivered: "已交付",
  gate_failed: "闸门失败",
  failed: "失败",
  cancelled: "已取消",
};

/** 失败机器码 → PM 人话（与后端 failure_reasons.PM_TEXT 对齐）。 */
const PM_FAILURE_TEXT: Record<string, { message: string; suggestion: string }> = {
  sandbox_blocked: { message: "生成的内容没过安全检查", suggestion: "换个说法再试，或让开发者看看具体原因" },
  code_syntax: { message: "生成的代码有问题，跑不起来", suggestion: "点「整段重跑」重新生成一次" },
  code_guard: { message: "生成的代码有问题，跑不起来", suggestion: "点「整段重跑」重新生成一次" },
  code_deps: { message: "生成的代码有问题，跑不起来", suggestion: "点「整段重跑」重新生成一次" },
  code_runtime: { message: "生成的代码跑不起来", suggestion: "点「整段重跑」重新生成一次" },
  gate_failed: { message: "生成的代码没通过自动检查", suggestion: "点「整段重跑」重新生成一次" },
  llm_key_missing: { message: "模型没连上，多半是 Key 没配好", suggestion: "检查 .env 里的 LLM_API_KEY 后重试" },
  llm_call_failed: { message: "模型没连上，多半是 Key 或网络问题", suggestion: "检查 Key 和网络后重试" },
  unknown_llm_provider: { message: "选的模型不认识", suggestion: "换个模型或跟随全局默认再试" },
  run_stuck: { message: "这一步做太久，已经被中断", suggestion: "点「整段重跑」重新试一次" },
  internal_error: { message: "这次没做成功", suggestion: "点「整段重跑」再试，或让开发者看看原因" },
};

/** PM 视角的失败人话；未知 code 或空走 internal_error 兜底。 */
export function pmFailureText(code?: string | null): { message: string; suggestion: string } {
  return PM_FAILURE_TEXT[code || ""] ?? PM_FAILURE_TEXT.internal_error;
}

export const STAGE_ORDER: Stage[] = [
  "idea_submitted",
  "clarifying",
  "awaiting_answers",
  "prd_drafting",
  "awaiting_prd_confirm",
  "building",
  "testing",
  "deploying",
  "evidence_ready",
  "gate_passed",
  "awaiting_acceptance",
  "delivered",
];

/** 产品经理可见进度：想法→PRD→验收→交付（隐藏构建/测试等工厂内部阶段）。 */
export const PM_STAGE_ORDER: Stage[] = [
  "idea_submitted",
  "clarifying",
  "awaiting_answers",
  "prd_drafting",
  "awaiting_prd_confirm",
  "awaiting_acceptance",
  "delivered",
];

/** 确认 PRD 之后、验收之前的工厂内部阶段（对产品经理隐藏）。 */
export const POST_PRD_STAGES: Stage[] = [
  "building",
  "testing",
  "deploying",
  "evidence_ready",
  "gate_passed",
  "gate_failed",
];

export const PM_HIDDEN_STAGES: Stage[] = [
  "building",
  "testing",
  "deploying",
  "evidence_ready",
  "gate_passed",
  "gate_failed",
];

export function isPmComplete(stage: Stage | null | undefined): boolean {
  if (!stage) return false;
  return stage === "delivered";
}

export function isPmHiddenStage(stage: Stage | null | undefined): boolean {
  if (!stage) return false;
  return (PM_HIDDEN_STAGES as string[]).includes(stage);
}

/** 任务列表等处给产品经理看的阶段文案。 */
export function pmStageLabel(stage: Stage): string {
  if (isPmHiddenStage(stage)) return "实现中…";
  return STAGE_CN[stage];
}

const TERMINAL: Stage[] = ["delivered", "gate_failed", "failed", "cancelled"];

/** 对话消息类型 */
export type MessageKind = "text" | "decisions" | "prd" | "code" | "deploy" | "acceptance" | "done";

export interface ChatMessage {
  role: "user" | "ai";
  kind: MessageKind;
  content: string;
  decisions?: Decision[];
}

/** 视图角色：产品经理看主路径，开发者看工厂细节。 */
export type ViewRole = "pm" | "dev";

/** 从 run 状态确定性重建对话流（刷新恢复不丢失）。role=pm 时不甩原始代码。 */
export function deriveMessages(run: Run | null, role: ViewRole = "pm"): ChatMessage[] {
  if (!run) return [];
  const msgs: ChatMessage[] = [];
  msgs.push({ role: "user", kind: "text", content: run.idea });
  if (run.decisions.length > 0) {
    msgs.push({ role: "ai", kind: "decisions", content: "动手前，先确认几个关键问题：", decisions: run.decisions });
    for (const d of run.decisions) {
      // 非关键决策已由 AI 自动按推荐回答，不再伪装成用户消息
      if (d.is_critical && d.answer) msgs.push({ role: "user", kind: "text", content: d.answer });
    }
  }
  const prd = run.evidence.find((e) => e.stage === "prd");
  if (prd) msgs.push({ role: "ai", kind: "prd", content: prd.content || prd.title });
  const code = run.evidence.find((e) => e.stage === "code");
  if (code) {
    const lines = (code.content || "").split("\n").length;
    const summary =
      role === "dev"
        ? `代码产物已生成（约 ${lines} 行），请在右侧「产物」查看全文。`
        : "实现产物已就绪。可在右侧「产物」查看说明与成品；完整代码请切换到「开发者」视图。";
    msgs.push({ role: "ai", kind: "code", content: summary });
  }
  const deploy = run.evidence.find((e) => e.stage === "deploy");
  if (deploy) {
    msgs.push({
      role: "ai",
      kind: "deploy",
      content: "运行说明与验收清单已生成，请在右侧「产物」查看。",
    });
  }
  if (run.current_stage === "awaiting_acceptance") {
    msgs.push({ role: "ai", kind: "acceptance", content: "自动检查已通过。请按清单验收后确认交付。" });
  }
  if (run.current_stage === "delivered") {
    msgs.push({ role: "ai", kind: "done", content: "已验收交付。可预览运行成品。" });
  }
  if (run.current_stage === "failed" || run.current_stage === "gate_failed") {
    msgs.push({ role: "ai", kind: "text", content: run.failure_reason ? `运行失败：${run.failure_reason}` : "运行失败，请重试" });
  }
  if (run.current_stage === "cancelled") msgs.push({ role: "ai", kind: "text", content: "已取消" });
  return msgs;
}


export interface Schedule {
  id: string;
  idea: string;
  trigger_time: string;
  enabled: boolean;
  project_id?: string | null;
  last_run_at?: string | null;
  created_at?: string;
}

export const listSchedules = () => api<Schedule[]>("/api/v1/schedules");

export const createSchedule = (body: { idea: string; trigger_time: string; project_id?: string | null }) =>
  api<Schedule>("/api/v1/schedules", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const updateSchedule = (id: string, body: { idea?: string; trigger_time?: string; enabled?: boolean }) =>
  api<Schedule>(`/api/v1/schedules/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const deleteSchedule = (id: string) =>
  api<{ ok: boolean }>(`/api/v1/schedules/${id}`, { method: "DELETE" });

export interface Project {
  id: string;
  name: string;
  idea_summary: string;
  workspace_path: string;
  created_at: string;
  updated_at: string;
  run_count: number;
}

export interface Artifact {
  id: number;
  kind: string;
  stage: string;
  title: string;
  previewable: boolean;
  content?: string;
}

/** 产品经理右侧默认可看的产物 kind（对齐 PRD §1.1）。 */
export const PM_ARTIFACT_KINDS = ["prd", "deploy", "readme"] as const;

export function filterArtifactsForRole(artifacts: Artifact[], role: ViewRole): Artifact[] {
  if (role === "dev") return artifacts;
  return artifacts.filter((a) => (PM_ARTIFACT_KINDS as readonly string[]).includes(a.kind));
}

/** 决策台账摘要（右栏展示 / 单测）。数据来自 run.decisions，不另造表。 */
export function summarizeDecisionLedger(decisions: Decision[] | null | undefined): {
  total: number;
  answered: number;
  pending: number;
  lines: { code: string; question: string; answer: string | null; critical: boolean }[];
} {
  const list = decisions ?? [];
  const lines = list.map((d) => ({
    code: d.code,
    question: d.question,
    answer: d.answer,
    critical: Boolean(d.is_critical),
  }));
  const answered = list.filter((d) => d.status === "answered").length;
  return {
    total: list.length,
    answered,
    pending: list.length - answered,
    lines,
  };
}

export const listProjects = () => api<{ projects: Project[] }>("/api/v1/projects");

export const getProject = (id: string) => api<Project>(`/api/v1/projects/${id}`);

export const createProject = (body: { name: string; idea_summary?: string; workspace_path?: string }) =>
  api<Project>("/api/v1/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const updateProject = (id: string, body: { name?: string; workspace_path?: string; idea_summary?: string }) =>
  api<Project>(`/api/v1/projects/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const listProjectRuns = (id: string) => api<{ runs: RunSummary[] }>(`/api/v1/projects/${id}/runs`);

export const listArtifacts = (runId: string) => api<Artifact[]>(`/api/v1/runs/${runId}/artifacts`);

export const getArtifact = (runId: string, artifactId: number) =>
  api<Artifact>(`/api/v1/runs/${runId}/artifacts/${artifactId}`);


/** 与后端 DEFAULT_ACCEPTANCE_CHECKLIST 同 id / 文案（PRD §4.1） */
export const DEFAULT_ACCEPTANCE_CHECKLIST = [
  { id: "local_run", label: "主路径能按说明在本地跑起来" },
  { id: "prd_match", label: "PRD 与实现大体一致" },
  { id: "no_blockers", label: "没有明显阻断性错误" },
] as const;

export type AcceptanceCheckId = (typeof DEFAULT_ACCEPTANCE_CHECKLIST)[number]["id"];

export const acceptRun = (
  id: string,
  checklist: { id: string; label?: string; passed: boolean }[],
  note = "验收通过",
) =>
  api<Run>(`/api/v1/runs/${id}/accept`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ checklist, note }),
  });

/** 管理一次"造物运行"的提交、SSE 订阅与状态回放。 */
export function useFactoryRun() {
  const [run, setRun] = useState<Run | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [failure, setFailure] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttemptRef = useRef(0);
  const runIdRef = useRef<string | null>(null);
  const seenEventIdsRef = useRef<Set<number>>(new Set());
  const openEventsRef = useRef<(id: string) => void>(() => {});

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);

  const closeEvents = useCallback(() => {
    clearReconnectTimer();
    esRef.current?.close();
    esRef.current = null;
  }, [clearReconnectTimer]);

  const applyRun = useCallback((r: Run) => {
    setRun(r);
    if (r.current_stage === "gate_passed" || r.current_stage === "awaiting_acceptance" || r.current_stage === "delivered") {
      setFailure(null);
    }
  }, []);

  const openEvents = useCallback(
    (id: string) => {
      closeEvents();
      runIdRef.current = id;
      const es = new EventSource(eventsUrl(id));
      esRef.current = es;

      es.addEventListener("chunk", (e) => {
        reconnectAttemptRef.current = 0;
        const d = JSON.parse((e as MessageEvent).data) as {
          id?: number;
          stage: Stage;
          payload?: string;
        };
        if (typeof d.id === "number") {
          if (seenEventIdsRef.current.has(d.id)) return;
          seenEventIdsRef.current.add(d.id);
        }
        setLogs((prev) => [...prev, `[${STAGE_CN[d.stage]}]${d.payload ? " " + d.payload : ""}`]);
        setRun((prev) => (prev ? { ...prev, current_stage: d.stage } : prev));
        getRun(id).then(applyRun).catch(() => {});
      });

      es.addEventListener("done", () => {
        reconnectAttemptRef.current = 0;
        closeEvents();
        getRun(id).then(applyRun).catch(() => {});
      });

      es.addEventListener("error", (e) => {
        const data = (e as MessageEvent).data;
        // 业务错误：带 data，结束订阅
        if (typeof data === "string" && data) {
          try {
            const d = JSON.parse(data) as { error?: { message?: string } };
            setFailure(d.error?.message ?? "运行失败");
          } catch {
            setFailure("运行失败");
          }
          closeEvents();
          getRun(id).then(applyRun).catch(() => {});
          return;
        }
        // 连接抖动：回放状态；若已关闭则退避重连
        getRun(id)
          .then((r) => {
            applyRun(r);
            if (TERMINAL.includes(r.current_stage)) {
              closeEvents();
              return;
            }
            if (esRef.current && esRef.current.readyState !== EventSource.CLOSED) {
              // 浏览器原生会重连，无需手动 open
              return;
            }
            const attempt = reconnectAttemptRef.current;
            if (attempt >= 6) {
              setFailure("进度连接多次失败，请刷新或点任务恢复");
              return;
            }
            const delay = Math.min(8000, 500 * 2 ** attempt);
            reconnectAttemptRef.current = attempt + 1;
            clearReconnectTimer();
            reconnectTimerRef.current = setTimeout(() => {
              if (runIdRef.current === id) openEventsRef.current(id);
            }, delay);
          })
          .catch(() => {});
      });
    },
    [applyRun, closeEvents, clearReconnectTimer],
  );

  useEffect(() => {
    openEventsRef.current = openEvents;
  }, [openEvents]);

  const submit = useCallback(
    async (idea: string, opts?: { llm_provider?: string }) => {
      setFailure(null);
      setLogs([]);
      seenEventIdsRef.current = new Set();
      reconnectAttemptRef.current = 0;
      const r = await createRun(idea, opts?.llm_provider ? { llm_provider: opts.llm_provider } : undefined);
      applyRun(r);
      if (typeof window !== "undefined") {
        localStorage.setItem("factory_run_id", r.id);
      }
      openEvents(r.id);
    },
    [applyRun, openEvents],
  );

  const answer = useCallback(
    async (code: string, value: string) => {
      if (!run) return;
      const r = await answerDecision(run.id, code, value);
      applyRun(r);
      if (!TERMINAL.includes(r.current_stage)) {
        openEvents(run.id);
      }
    },
    [run, applyRun, openEvents],
  );

  const restore = useCallback(
    async (id: string) => {
      setFailure(null);
      setLogs([]);
      seenEventIdsRef.current = new Set();
      reconnectAttemptRef.current = 0;
      const r = await getRun(id);
      applyRun(r);
      // 未终态且尚未过 PRD 确认，才重连 SSE（PM 路径到 PRD 即止）
      if (!TERMINAL.includes(r.current_stage) && !isPmComplete(r.current_stage)) {
        openEvents(id);
      }
    },
    [applyRun, openEvents],
  );

  const confirm = useCallback(async () => {
    if (!run) return;
    // 乐观更新：立即标记已确认，让"确认 PRD"按钮马上消失，防止重复点击
    setRun((prev) => (prev ? { ...prev, current_stage: "building" } : prev));
    try {
      // confirm 接口返回时后台线程尚未推进（仍是 awaiting_prd_confirm），
      // 不能应用这个旧 stage，否则会回退；保持乐观 building，让 SSE 跟到终态
      await confirmPrd(run.id);
      openEvents(run.id);
    } catch {
      // 失败则回滚到待确认状态，让用户可重试
      setRun((prev) => (prev ? { ...prev, current_stage: "awaiting_prd_confirm" } : prev));
      throw new Error("确认失败，请重试");
    }
  }, [run, openEvents]);

  const reject = useCallback(async () => {
    if (!run) return;
    const r = await rejectPrd(run.id);
    applyRun(r);
  }, [run, applyRun]);

  const cancel = useCallback(async () => {
    if (!run) return;
    const r = await cancelRun(run.id);
    applyRun(r);
    closeEvents();
  }, [run, applyRun, closeEvents]);

  const retry = useCallback(async () => {
    if (!run) return;
    setFailure(null);
    setLogs([]);
    seenEventIdsRef.current = new Set();
    reconnectAttemptRef.current = 0;
    closeEvents();
    const r = await retryRun(run.id);
    applyRun(r);
    if (typeof window !== "undefined") {
      localStorage.setItem("factory_run_id", r.id);
    }
    openEvents(r.id);
  }, [run, applyRun, closeEvents, openEvents]);

  const retest = useCallback(async () => {
    if (!run) return;
    setFailure(null);
    setLogs([]);
    seenEventIdsRef.current = new Set();
    reconnectAttemptRef.current = 0;
    closeEvents();
    const r = await retestRun(run.id);
    applyRun(r);
    // 同 id 续跑，不换 localStorage
    openEvents(r.id);
  }, [run, applyRun, closeEvents, openEvents]);

  const score = useCallback(
    async (decision: number, prd: number, code: number) => {
      if (!run) return;
      await scoreRun(run.id, decision, prd, code);
    },
    [run],
  );

  const reset = useCallback(() => {
    closeEvents();
    setRun(null);
    setLogs([]);
    setFailure(null);
    seenEventIdsRef.current = new Set();
    reconnectAttemptRef.current = 0;
    runIdRef.current = null;
    if (typeof window !== "undefined") {
      localStorage.removeItem("factory_run_id");
    }
  }, [closeEvents]);

  useEffect(() => closeEvents, [closeEvents]);

  const stage = run?.current_stage ?? null;
  const isTerminal = stage !== null && TERMINAL.includes(stage);

  return { run, stage, logs, failure, isTerminal, submit, restore, answer, confirm, reject, cancel, retry, retest, score, reset };
}
