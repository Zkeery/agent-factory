"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight, ArrowRight, BarChart3, GitBranch, Plus, Layers3, FolderOpen, Clock3, LogOut, ChevronRight, PanelRight, Menu, X } from "lucide-react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { formatApiDate, formatApiDateTime } from "@/lib/dateTime";
import {
  acceptRun,
  rejectRun,
  acceptanceScenarioError,
  canReviseRun,
  authorizeWorkspace,
  canFullRetry,
  canRetestInPlace,
  retestFallbackHint,
  canShowAlwaysAllow,
  mainFlowScenario,
  preservedScenarioResults,
  Artifact,
  Decision,
  filterArtifactsForRole,
  ViewRole,
  getArtifact,
  getMetrics,
  getProject,
  getRunList,
  listArtifacts,
  listProjects,
  deleteProject,
  restoreProject,
  Metrics,
  needsWorkspaceAuth,
  PM_STAGE_ORDER,
  pmStageLabel,
  pmFailureText,
  scheduleInternalIntro,
  scheduleSkipLine,
  Project,
  RunSummary,
  Schedule,
  listSchedules,
  createSchedule,
  updateSchedule,
  deleteSchedule,
  Stage,
  STAGE_CN,
  STAGE_ORDER,
  syncWorkspace,
  updateProject,
  useFactoryRun,
  getLlmProfiles,
  comparePrd,
  type LlmProfile,
  type ComparePrdVariant,
  clearToken,
  fetchMe,
  getToken,
  login,
  requestCode,
  setToken,
  startApp,
  stopApp,
  getAppStatus,
  summarizeAppStatus,
  summarizeDecisionLedger,
  selectArtifactAfterRefresh,
  AppRunStatus,
  type AcceptanceChecklistItem,
  type AcceptanceScenario,
  type AcceptanceScenarioResult,
  type Run,
  type ExecutionMode,
} from "@/lib/factory";
import { cn } from "@/lib/utils";
import { WorkspaceHome, WorkflowProgress } from "@/components/WorkspaceHome";
import { ExecutionPanel } from "@/components/ExecutionPanel";
import { ProjectReview } from "@/components/ProjectReview";
import { ProjectDeleteDialog } from "@/components/ProjectDeleteDialog";
import { ProjectNavigation, ProjectVersionPicker } from "@/components/ProjectNavigation";
import { DecisionPrompt } from "@/components/DecisionPrompt";
import { resumeExecution } from "@/lib/agentInsights";
import { startWorkspaceSync } from "@/lib/workspaceSync";
import {
  AcceptanceRecord,
  AcceptanceScenariosEditor,
  BundleDownload,
  MainFlowAcceptance,
  RequirementsForm,
  RevisionForm,
} from "@/components/RunImprovements";

const productMarkdownComponents: Components = {
  table: ({ children }) => (
    <div className="prose-table-scroll" role="region" aria-label="文档表格，可横向滚动" tabIndex={0}>
      <table>{children}</table>
    </div>
  ),
};

/* ---------- 左栏：任务列表 ---------- */
function TaskList({
  runs,
  currentId,
  currentProjectId,
  onSelect,
  onNew,
  busy,
  onReview,
  reviewActive,
  role,
  onRoleChange,
  projects,
  deletedProjects,
  onDeleteProject,
  onRestoreProject,
  schedules,
  onCreateSchedule,
  onToggleSchedule,
  onDeleteSchedule,
  syncStatus,
  scheduleNotice,
}: {
  runs: RunSummary[];
  currentId: string | null;
  currentProjectId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  busy: boolean;
  onReview: () => void;
  reviewActive: boolean;
  role: ViewRole;
  onRoleChange: (r: ViewRole) => void;
  projects: Project[];
  deletedProjects: Project[];
  onDeleteProject: (id: string) => void;
  onRestoreProject: (id: string) => void;
  schedules: Schedule[];
  onCreateSchedule: (idea: string, triggerTime: string) => Promise<void>;
  onToggleSchedule: (s: Schedule) => void;
  onDeleteSchedule: (id: string) => void;
  syncStatus: string;
  scheduleNotice: { id: string; idea: string } | null;
}) {
  const [showNew, setShowNew] = useState(false);
  const [newIdea, setNewIdea] = useState("");
  const [newTime, setNewTime] = useState("09:00");
  const [savingSchedule, setSavingSchedule] = useState(false);
  const [scheduleError, setScheduleError] = useState<string | null>(null);
  const scheduleNotes = scheduleInternalIntro(role);
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <button disabled={busy} onClick={onNew} className="flex h-[76px] shrink-0 items-center gap-2.5 px-5 text-left" aria-label="返回工作台">
        <span className="factory-logo"><Layers3 size={20} /></span>
        <span><span className="block text-[15px] font-semibold tracking-tight">Agent 造物坊</span><span className="mt-0.5 block font-mono text-[9px] tracking-[0.16em] text-muted">IDEAS INTO REALITY</span></span>
      </button>
      <button disabled={busy} className="button-primary mx-4 mb-5 justify-center" onClick={onNew}><Plus size={16} />创建新项目</button>
      <button disabled={busy} className={cn("mx-4 mb-4 flex items-center gap-2 rounded-lg px-3 py-2 text-xs", reviewActive ? "bg-brand-soft font-medium text-brand" : "text-muted hover:bg-surface-2")} onClick={onReview}><BarChart3 size={15} />项目复盘</button>
      {scheduleNotice && <button disabled={busy} onClick={() => onSelect(scheduleNotice.id)} className="mx-4 mb-3 rounded-lg border border-brand/30 bg-brand-soft px-3 py-2 text-left text-xs text-brand" aria-label={`查看定时新项目：${scheduleNotice.idea}`}>
        <span className="block font-medium">定时任务已生成 · 查看</span>
        <span className="mt-1 block truncate">{scheduleNotice.idea}</span>
      </button>}
      <ProjectNavigation projects={projects} runs={runs} deletedProjects={deletedProjects} currentId={currentId} currentProjectId={currentProjectId} busy={busy} role={role} onSelect={onSelect} onDelete={onDeleteProject} onRestore={onRestoreProject} />
      <p className="mx-5 mt-2 text-[10px] text-muted" role="status">{syncStatus}</p>
      <div className="mx-4 mb-4 mt-4 rounded-lg bg-surface-2 p-1 flex gap-1 text-[11px]">
        <button className={cn("flex-1 rounded-md py-1.5", role === "pm" ? "bg-panel text-ink shadow-sm" : "text-muted")} onClick={() => onRoleChange("pm")}>产品视角</button>
        <button className={cn("flex-1 rounded-md py-1.5", role === "dev" ? "bg-panel text-ink shadow-sm" : "text-muted")} onClick={() => onRoleChange("dev")}>开发视角</button>
      </div>
      <div className="shrink-0 border-t px-3 py-2" style={{ borderColor: "var(--color-line)" }}>
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-2 text-xs font-medium" style={{ color: "var(--color-muted)" }}><Clock3 size={14} />定时任务</span>
          <button className="text-xs" style={{ color: "var(--color-primary)" }} onClick={() => setShowNew((v) => !v)}>{showNew ? "收起" : "新建"}</button>
        </div>
        {showNew && (
          <div className="mt-2 space-y-1.5">
            <div>
              <div className="mb-1 text-[11px]" style={{ color: "var(--color-muted)" }}>想法</div>
              <input
                className="w-full rounded-lg border px-2 py-1.5 text-xs outline-none"
                style={{ borderColor: "var(--color-line)", background: "var(--color-bg)" }}
                placeholder="如：做个每日待办清单"
                value={newIdea}
                onChange={(e) => setNewIdea(e.target.value)}
              />
            </div>
            <div className="flex items-end gap-2">
              <fieldset className="min-w-0">
                <legend className="mb-1 text-[11px] text-muted">每天时间</legend>
                <div className="flex items-center gap-1">
                  <select aria-label="小时" disabled={savingSchedule} className="rounded-lg border border-line bg-panel px-1 py-1.5 text-xs" value={newTime.split(":")[0]} onChange={(e) => setNewTime(`${e.target.value}:${newTime.split(":")[1]}`)}>
                    {Array.from({ length: 24 }, (_, hour) => String(hour).padStart(2, "0")).map((hour) => <option key={hour} value={hour}>{hour} 时</option>)}
                  </select>
                  <span className="text-xs text-muted">:</span>
                  <select aria-label="分钟" disabled={savingSchedule} className="rounded-lg border border-line bg-panel px-1 py-1.5 text-xs" value={newTime.split(":")[1]} onChange={(e) => setNewTime(`${newTime.split(":")[0]}:${e.target.value}`)}>
                    {Array.from({ length: 60 }, (_, minute) => String(minute).padStart(2, "0")).map((minute) => <option key={minute} value={minute}>{minute} 分</option>)}
                  </select>
                </div>
              </fieldset>
              <button
                className="shrink-0 rounded-full px-2 py-1.5 text-xs text-[#0a0b0e] disabled:opacity-50"
                style={{ background: "var(--gradient-brand)" }}
                disabled={savingSchedule || !newIdea.trim()}
                onClick={async () => {
                  if (!newIdea.trim() || savingSchedule) return;
                  setSavingSchedule(true);
                  setScheduleError(null);
                  try {
                    await onCreateSchedule(newIdea.trim(), newTime);
                    setNewIdea("");
                    setNewTime("09:00");
                  } catch (error) {
                    setScheduleError(error instanceof Error ? error.message : "保存失败，请重试。");
                  } finally {
                    setSavingSchedule(false);
                  }
                }}
              >
                {savingSchedule ? "保存中" : "保存"}
              </button>
            </div>
            {scheduleError && <p role="alert" className="text-[11px] text-red-600">{scheduleError}</p>}
          </div>
        )}
        {scheduleNotes.intro && <p className="mt-2 text-[10px] leading-relaxed text-muted">{scheduleNotes.intro}</p>}
        {schedules.length > 0 && (
          <div className="mt-2 space-y-2">
            {schedules.map((s) => {
              const skipLine = scheduleSkipLine(role, s.pending_run_stage, s.last_skipped_at ? formatApiDateTime(s.last_skipped_at) : null);
              return (
              <div key={s.id} className="text-xs">
                <div className="flex items-center gap-1.5">
                  <span className="min-w-0 flex-1 truncate" style={{ color: s.enabled ? "var(--ink)" : "var(--color-muted)" }}>{s.idea}</span>
                  <span title={scheduleNotes.clockTitle} style={{ color: "var(--color-muted)" }}>{s.trigger_time}</span>
                  <label className="flex items-center gap-1" style={{ color: s.enabled ? "var(--ok)" : "var(--color-muted)" }}>
                    <input
                      type="checkbox"
                      className="mt-0.5"
                      checked={s.enabled}
                      onChange={() => onToggleSchedule(s)}
                    />
                    {s.enabled ? "已开启" : "已关闭"}
                  </label>
                  <button className="rounded-full border px-2 py-0.5" style={{ borderColor: "var(--color-line)", color: "var(--color-muted)" }} onClick={() => onDeleteSchedule(s.id)}>删</button>
                </div>
                {skipLine && <div className="mt-1 text-[10px] leading-relaxed text-muted">{skipLine}{s.pending_run_id ? <button type="button" className="ml-1 text-brand" onClick={() => onSelect(s.pending_run_id!)}>查看</button> : null}</div>}
              </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

/* ---------- 中栏：消息气泡 ---------- */

/* ---------- 决策卡快捷按钮 ---------- */
function DecisionsInline({ decisions, onAnswer, stage, busy = false }: { decisions: Decision[]; onAnswer: (code: string, value: string) => void; stage: string | null; busy?: boolean }) {
  const [editing, setEditing] = useState<string | null>(null);
  const open = decisions.filter((d) => d.status !== "answered");
  const answered = decisions.filter((d) => d.status === "answered");
  // 非关键决策仅在 PRD 确认前可改；确认后隐藏「改」，避免点了没反应
  const editable = stage === "awaiting_answers" || stage === "awaiting_prd_confirm";

  const renderOptions = (d: Decision) => (
    <div className="mt-2.5 flex flex-wrap gap-2">
      {d.options.split("/").map((opt) => {
        const o = opt.trim();
        if (!o) return null;
        return (
          <button disabled={busy} key={o} className="rounded-full px-4 py-1.5 text-xs transition hover:opacity-80 disabled:opacity-40" style={{ background: "var(--surface-2)", color: "var(--ink-soft)" }} onClick={() => { onAnswer(d.code, o); setEditing(null); }}>
            {o}
          </button>
        );
      })}
      <button disabled={busy} className="rounded-full px-4 py-1.5 text-xs text-[#0a0b0e] transition hover:opacity-90 disabled:opacity-40" style={{ background: "var(--gradient-brand)" }} onClick={() => { onAnswer(d.code, "按推荐"); setEditing(null); }}>
        按推荐
      </button>
    </div>
  );

  return (
    <div className="mt-3 rounded-[28px] p-5" style={{ background: "var(--color-surface)", boxShadow: "var(--shadow-md)" }}>
      <div className="space-y-5">
        {open.map((d) => (
          <div key={d.code}>
            <div className="text-sm font-medium" style={{ color: "var(--ink)" }}>{d.question}</div>
            {renderOptions(d)}
          </div>
        ))}
        {answered.map((d) => (
          <div key={d.code} className="text-xs" style={{ color: "var(--ok)" }}>
            {d.is_critical ? "已确认 ·" : "默认 ·"} {d.question} → {d.answer}
            {!d.is_critical && editable && (
              <>
                <span style={{ color: "var(--color-muted)" }}>（已按推荐自动）</span>
                <button disabled={busy} className="ml-2 rounded-full px-2 py-0.5 text-xs transition hover:opacity-80 disabled:opacity-40" style={{ background: "var(--surface-2)", color: "var(--ink-soft)" }} onClick={() => setEditing(editing === d.code ? null : d.code)}>
                  改
                </button>
              </>
            )}
            {editing === d.code && renderOptions(d)}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------- 中栏内：紧凑进度条 + 人审闸门 ---------- */
function stageStatus(current: Stage | null | undefined, target: Stage): "done" | "current" | "todo" | "failed" {
  if (!current) return "todo";
  if (current === "failed" || current === "gate_failed" || current === "cancelled") {
    const order = STAGE_ORDER as string[];
    const ci = order.indexOf(current);
    const ti = order.indexOf(target);
    if (ci >= 0 && ti >= 0 && ti < ci) return "done";
    if (target === current) return "failed";
    return "todo";
  }
  const order = STAGE_ORDER as string[];
  const ci = order.indexOf(current);
  const ti = order.indexOf(target);
  if (ci < 0 || ti < 0) return current === target ? "current" : "todo";
  if (ti < ci) return "done";
  if (ti === ci) return "current";
  return "todo";
}

function SessionRail({
  run,
  role,
  onConfirm,
  confirmDisabled,
  confirmHint,
}: {
  run: ReturnType<typeof useFactoryRun>["run"];
  role: ViewRole;
  onConfirm: () => void;
  confirmDisabled: boolean;
  confirmHint?: string;
}) {
  const [view, setView] = useState<"compact" | "board">("compact");
  if (!run) return null;
  const stages = role === "pm" ? PM_STAGE_ORDER : STAGE_ORDER;
  const current = run.current_stage;
  const showGate =
    current === "awaiting_prd_confirm" ||
    current === "awaiting_acceptance";
  const artifactOf = (s: Stage) => run.evidence.find((e) => e.stage === s)?.title ?? "";

  return (
    <div className="shrink-0 border-b px-4 py-2.5" style={{ borderColor: "var(--color-line)", background: "var(--color-surface)" }}>
      {view === "compact" ? (
      <div className="flex flex-wrap items-center gap-1.5">
        {stages.map((s, i) => {
          const st = stageStatus(current, s);
          const label = role === "pm" ? pmStageLabel(s) : STAGE_CN[s];
          const isAccept = s === "awaiting_acceptance" && st === "current";
          const color =
            st === "done" ? "var(--color-ok)" :
            isAccept ? "var(--warn)" :
            st === "current" ? "var(--color-primary)" :
            st === "failed" ? "var(--danger)" :
            "var(--color-muted)";
          return (
            <div key={s} className="flex items-center gap-1.5">
              {i > 0 && <span className="text-[10px]" style={{ color: "var(--color-line)" }}>/</span>}
              <span
                className="rounded-full px-2 py-0.5 text-[11px]"
                style={{
                  color,
                  background: st === "current" ? (isAccept ? "var(--warn-soft)" : "var(--brand-soft)") : "transparent",
                  fontWeight: st === "current" ? 600 : 400,
                }}
              >
                {isAccept && <span className="mr-1 inline-block h-1.5 w-1.5 animate-pulse-dot rounded-full align-middle" style={{ background: "var(--warn)" }} />}
                {label}
              </span>
            </div>
          );
        })}
      </div>
      ) : (
      <div className="flex gap-2 overflow-x-auto pb-1">
        {stages.map((s) => {
          const st = stageStatus(current, s);
          const label = role === "pm" ? pmStageLabel(s) : STAGE_CN[s];
          const isAccept = s === "awaiting_acceptance" && st === "current";
          const color =
            st === "done" ? "var(--color-ok)" :
            isAccept || st === "current" ? (isAccept ? "var(--warn)" : "var(--color-primary)") :
            st === "failed" ? "var(--danger)" :
            "var(--color-muted)";
          const bg =
            st === "current" ? (isAccept ? "var(--warn-soft)" : "var(--brand-soft)") :
            st === "failed" ? "var(--danger-soft)" :
            "var(--color-bg)";
          const icon = st === "done" ? "✓" : st === "failed" ? "✗" : st === "current" ? "◉" : "·";
          const artifact = artifactOf(s);
          return (
            <div key={s} className="min-w-[104px] shrink-0 rounded-lg border p-2" style={{ borderColor: st === "current" ? color : "var(--color-line)", background: bg }}>
              <div className="flex items-center gap-1 text-[11px] font-medium" style={{ color }}>
                <span>{icon}</span>
                <span className="truncate">{label}</span>
                {st === "current" && <span className="h-1.5 w-1.5 animate-pulse-dot rounded-full" style={{ background: color }} />}
              </div>
              {artifact && <div className="mt-1 truncate text-[10px]" style={{ color: "var(--color-muted)" }}>{artifact}</div>}
              {role === "dev" && st === "current" && (
                <div className="mt-1 truncate text-[10px]" style={{ color: "var(--color-muted)" }}>模型：{run.llm_provider || "跟随全局"}</div>
              )}
            </div>
          );
        })}
      </div>
      )}
      <div className="mt-1.5 flex items-center gap-1">
        <button className={cn("rounded-full px-2 py-0.5 text-[11px]", view === "compact" ? "bg-brand-soft text-brand-2" : "text-muted")} onClick={() => setView("compact")}>紧凑</button>
        <button className={cn("rounded-full px-2 py-0.5 text-[11px]", view === "board" ? "bg-brand-soft text-brand-2" : "text-muted")} onClick={() => setView("board")}>看板</button>
      </div>
      {showGate && (
        <div className="mt-2 flex flex-wrap items-center gap-2 rounded-xl border px-3 py-2" style={{ borderColor: "var(--color-line)", background: "var(--color-bg)" }}>
          {current === "awaiting_prd_confirm" && (
            <>
              <span className="text-xs" style={{ color: "var(--color-muted)" }}>PRD 待确认</span>
              <button className="rounded-full px-3 py-1 text-xs text-[#0a0b0e] disabled:opacity-40" style={{ background: "var(--gradient-brand)" }} onClick={onConfirm} disabled={confirmDisabled}>
                确认 PRD
              </button>
              {confirmHint && <span className="text-xs" style={{ color: "var(--color-muted)" }}>{confirmHint}</span>}
            </>
          )}
          {current === "awaiting_acceptance" && (
            <>
              <span className="h-1.5 w-1.5 animate-pulse-dot rounded-full" style={{ background: "var(--warn)" }} />
              <span className="text-xs font-medium" style={{ color: "var(--warn)" }}>
                待验收：打开成品，确认主流程是否走通。
              </span>
            </>
          )}
        </div>
      )}
    </div>
  );
}

type OutputKind = "prd" | "code" | "deploy" | "decisions";
type OutputFocus = { runId: string; sequence: number; kind: OutputKind };

/* ---------- 预览栏：产物 + 本地运行 ---------- */
function InternalExecutionDetails({ run, onResume }: { run: Run; onResume: () => Promise<void> }) {
  const [expanded, setExpanded] = useState(false);
  return <details className="rounded-xl border border-line bg-panel" onToggle={(event) => setExpanded(event.currentTarget.open)}>
    <summary className="cursor-pointer px-4 py-3 text-xs font-medium text-muted">内部执行记录</summary>
    {expanded && <div className="border-t border-line p-3"><ExecutionPanel runId={run.id} currentStage={run.current_stage} executionMode={run.execution_mode} onResume={onResume} /></div>}
  </details>;
}

function PreviewPanel({
  run,
  metrics,
  role,
  onPreview,
  onRunRefresh,
  onResume,
  focusRequest,
}: {
  run: ReturnType<typeof useFactoryRun>["run"];
  metrics: Metrics | null;
  role: ViewRole;
  onPreview: () => void | Promise<void>;
  onRunRefresh: () => Promise<void>;
  onResume: () => Promise<void>;
  focusRequest: OutputFocus | null;
}) {
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [selected, setSelected] = useState<Artifact | null>(null);
  const artifactRevision = useRef<{ runId: string; revision: number } | null>(null);
  const appliedFocus = useRef<number | null>(null);
  const visibleArtifacts = filterArtifactsForRole(artifacts, role);
  const [workspace, setWorkspace] = useState("");
  const [previewBusy, setPreviewBusy] = useState(false);
  const [stopBusy, setStopBusy] = useState(false);
  const [appStatus, setAppStatus] = useState<AppRunStatus | null>(null);
  const [syncBusy, setSyncBusy] = useState(false);
  const [writeConfirmOpen, setWriteConfirmOpen] = useState(false);
  const [writeAlways, setWriteAlways] = useState(false);
  type PreviewTab = "run" | "decisions" | "artifacts" | "quality";
  const [tab, setTab] = useState<PreviewTab>("artifacts");
  const [compareBusy, setCompareBusy] = useState(false);
  const [compareErr, setCompareErr] = useState<string | null>(null);
  const [compareVariants, setCompareVariants] = useState<ComparePrdVariant[]>([]);

  const runId = run?.id ?? null;

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    listArtifacts(runId)
      .then((items) => {
        if (cancelled) return;
        const revision = run?.prd_revision ?? 0;
        const changed = artifactRevision.current?.runId !== runId || artifactRevision.current.revision !== revision;
        const sorted = [...items].sort((a, b) => b.id - a.id);
        setArtifacts(sorted);
        const focus = focusRequest?.runId === runId && focusRequest.sequence !== appliedFocus.current ? focusRequest : null;
        const visible = filterArtifactsForRole(sorted, role);
        const requested = focus ? visible.find((item) => item.kind === focus.kind) : null;
        setSelected((prev) => requested || selectArtifactAfterRefresh(visible, prev?.id ?? null, changed));
        artifactRevision.current = { runId, revision };
        if (focus && (requested || focus.kind === "decisions")) {
          setTab(focus.kind === "decisions" ? "decisions" : "artifacts");
          appliedFocus.current = focus.sequence;
        } else if (changed && sorted.some((item) => item.kind === "prd")) setTab("artifacts");
      })
      .catch(() => {
        if (!cancelled) setArtifacts([]);
      });
    return () => {
      cancelled = true;
    };
  }, [runId, run?.current_stage, run?.evidence?.length, run?.prd_revision, role, focusRequest]);

  useEffect(() => {
    if (!runId) {
      setAppStatus(null);
      return;
    }
    const canPoll = Boolean(
      run && ["awaiting_acceptance", "delivered", "gate_passed"].includes(run.current_stage),
    );
    if (!canPoll) {
      setAppStatus(null);
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | null = null;

    const refresh = () => {
      getAppStatus(runId)
        .then((s) => {
          if (!cancelled) setAppStatus(s);
        })
        .catch(() => {
          if (!cancelled) setAppStatus({ running: false, url: null, port: null });
        });
    };

    refresh();
    timer = setInterval(refresh, 5000);
    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
  }, [runId, run?.current_stage]);


  useEffect(() => {
    const visible = filterArtifactsForRole(artifacts, role);
    setSelected((prev) => {
      if (prev && visible.some((a) => a.id === prev.id)) return prev;
      return visible[0] || null;
    });
  }, [artifacts, role]);

  useEffect(() => {
    if (filterArtifactsForRole(artifacts, role).length > 0) {
      setTab((prev) => (prev === "run" ? "artifacts" : prev));
    }
    if (role !== "dev") {
      setTab((prev) => (prev === "quality" ? "run" : prev));
    }
  }, [artifacts.length, role]);

  const selectedId = selected?.id ?? null;
  const needsContent = Boolean(selected && selected.content === undefined);

  useEffect(() => {
    if (!runId || selectedId === null || !needsContent) return;
    let cancelled = false;
    getArtifact(runId, selectedId)
      .then((detail) => {
        if (!cancelled) setSelected(detail);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [runId, selectedId, needsContent]);

  useEffect(() => {
    const pid = run?.project_id;
    if (!pid) {
      setWorkspace("");
      return;
    }
    let cancelled = false;
    getProject(pid)
      .then((p) => {
        if (!cancelled) setWorkspace(p.workspace_path || "");
      })
      .catch(() => {
        listProjects()
          .then((d) => {
            if (cancelled) return;
            const hit = d.projects.find((p) => p.id === pid);
            if (hit) setWorkspace(hit.workspace_path || "");
          })
          .catch(() => {});
      });
    return () => {
      cancelled = true;
    };
  }, [run?.project_id]);

  async function saveWorkspace() {
    if (!run?.project_id) return;
    try {
      await updateProject(run.project_id, { workspace_path: workspace.trim() });
      alert("工作区路径已保存");
    } catch (e) {
      alert((e as Error).message);
    }
  }

  async function handleLocalRun() {
    setPreviewBusy(true);
    try {
      await onPreview();
    } finally {
      try {
        if (runId) {
          const s = await getAppStatus(runId);
          setAppStatus(s);
        }
      } catch {
        /* status 刷新失败不影响启动结果提示 */
      }
      setPreviewBusy(false);
    }
  }

  async function handleStopPreview() {
    if (!runId) return;
    setStopBusy(true);
    try {
      const s = await stopApp(runId);
      setAppStatus(s);
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setStopBusy(false);
    }
  }

  function openRunningUrl() {
    if (appStatus?.url) window.open(appStatus.url, "_blank", "noopener");
  }

  async function doSync() {
    if (!run) return;
    setSyncBusy(true);
    try {
      const r = await syncWorkspace(run.id);
      alert(`已同步 ${r.files_copied} 个文件到\n${r.target}`);
      await onRunRefresh();
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setSyncBusy(false);
      setWriteConfirmOpen(false);
      setWriteAlways(false);
    }
  }

  async function handleSyncClick() {
    if (!run) return;
    if (needsWorkspaceAuth(run, "write")) {
      setWriteAlways(false);
      setWriteConfirmOpen(true);
      return;
    }
    await doSync();
  }

  async function confirmWriteAuth() {
    if (!run) return;
    setSyncBusy(true);
    try {
      await authorizeWorkspace(run.id, {
        scopes: ["write"],
        always_for_run: canShowAlwaysAllow(role) && writeAlways,
        role,
      });
      await onRunRefresh();
      await doSync();
    } catch (e) {
      alert((e as Error).message);
      setSyncBusy(false);
    }
  }

  const canRun = Boolean(
    run && ["awaiting_acceptance", "delivered", "gate_passed"].includes(run.current_stage),
  );
  const workspaceBound = Boolean(workspace.trim());

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b px-4 pt-3" style={{ borderColor: "var(--color-line)" }}>
        <div className="mb-3 flex items-center justify-between text-xs"><span className="font-semibold">成果区</span><span className="text-[10px] text-muted">需求、代码与运行</span></div>
        <div className="flex flex-wrap gap-1 pb-2">
          {(
            [
              { id: "artifacts" as const, label: "产物" },
              { id: "run" as const, label: "运行" },
              { id: "decisions" as const, label: "决策" },
              ...(role === "dev" ? [{ id: "quality" as const, label: "质量" }] : []),
            ]
          ).map((t) => (
            <button
              key={t.id}
              className={cn(
                "rounded-md px-3 py-1.5 text-xs",
                tab === t.id ? "font-medium" : "",
              )}
              style={
                tab === t.id
                  ? { background: "var(--brand-soft)", color: "var(--brand)" }
                  : { borderColor: "var(--color-line)", color: "var(--color-muted)" }
              }
              onClick={() => { if (focusRequest) appliedFocus.current = focusRequest.sequence; setTab(t.id); }}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className="workspace-scroll flex-1 min-h-0 overflow-auto p-4">
        {tab === "run" && (
          <div className="space-y-4">
            <section>
              <div className="mb-2 text-xs font-medium" style={{ color: "var(--color-muted)" }}>工作区</div>
              <div className="flex gap-1">
                <input
                  className="min-w-0 flex-1 rounded-lg border px-2 py-1 text-xs outline-none"
                  style={{ borderColor: "var(--color-line)", background: "var(--color-bg)" }}
                  placeholder="本地目录路径（可选）"
                  value={workspace}
                  onChange={(e) => setWorkspace(e.target.value)}
                  disabled={!run?.project_id}
                />
                <button
                  className="rounded-lg px-2 py-1 text-xs text-[#0a0b0e] disabled:opacity-40"
                  style={{ background: "var(--gradient-brand)" }}
                  disabled={!run?.project_id}
                  onClick={saveWorkspace}
                >
                  绑定
                </button>
              </div>
            </section>

            <section>
              <div className="mb-2 flex items-center justify-between gap-2">
                <div className="text-xs font-bold uppercase tracking-wide" style={{ color: "var(--color-muted)" }}>本地运行</div>
                <div className="flex flex-wrap justify-end gap-1">
                  {appStatus?.running ? (
                    <>
                      <button
                        className="rounded-full border px-3 py-1 text-xs disabled:opacity-40"
                        style={{ borderColor: "var(--color-line)" }}
                        disabled={!appStatus.url}
                        onClick={openRunningUrl}
                      >
                        在浏览器打开
                      </button>
                      <button
                        className="rounded-full px-3 py-1 text-xs text-[#0a0b0e] disabled:opacity-40"
                        style={{ background: "var(--gradient-brand)" }}
                        disabled={stopBusy}
                        onClick={() => void handleStopPreview()}
                      >
                        {stopBusy ? "停止中…" : "停止预览"}
                      </button>
                    </>
                  ) : (
                    <button
                      className="rounded-full px-3 py-1 text-xs text-[#0a0b0e] disabled:opacity-40"
                      style={{ background: "var(--gradient-brand)" }}
                      disabled={!canRun || previewBusy}
                      onClick={() => void handleLocalRun()}
                    >
                      {previewBusy ? "启动中…" : "打开预览"}
                    </button>
                  )}
                </div>
              </div>
              <div className="text-[11px]" style={{ color: "var(--color-muted)" }}>
                {!canRun
                  ? "待验收或交付后可本地运行。"
                  : appStatus?.running
                    ? summarizeAppStatus(appStatus)
                    : "将启动本轮产物的本地预览服务（首次需确认）。"}
              </div>
              {canRun && appStatus?.running && appStatus.url && (
                <div
                  className="mt-2 truncate rounded-lg border px-2 py-1 font-mono text-[11px]"
                  style={{ borderColor: "var(--color-line)", background: "var(--color-bg)" }}
                  title={appStatus.url}
                >
                  {appStatus.url}
                </div>
              )}
            </section>

            {workspaceBound && canRun && (
              <section>
                <div className="mb-2 flex items-center justify-between">
                  <div className="text-xs font-bold uppercase tracking-wide" style={{ color: "var(--color-muted)" }}>工作区同步</div>
                  <button
                    className="rounded-full border px-3 py-1 text-xs disabled:opacity-40"
                    style={{ borderColor: "var(--color-line)" }}
                    disabled={syncBusy}
                    onClick={() => void handleSyncClick()}
                  >
                    {syncBusy ? "同步中…" : "同步到工作区"}
                  </button>
                </div>
                <div className="text-[11px]" style={{ color: "var(--color-muted)" }}>
                  将本轮生成文件复制到已绑定目录；会覆盖同名生成文件，不会删除其它文件。
                </div>
                {writeConfirmOpen && (
                  <div className="mt-2 rounded-xl border p-3 text-xs" style={{ borderColor: "var(--color-line)", background: "var(--color-bg)" }}>
                    <div className="font-medium">确认写入工作区？</div>
                    <div className="mt-1" style={{ color: "var(--color-muted)" }}>
                      将覆盖工作区内同名生成文件（如 app.py）。
                    </div>
                    {canShowAlwaysAllow(role) && (
                      <label className="mt-2 flex items-center gap-2">
                        <input type="checkbox" checked={writeAlways} onChange={(e) => setWriteAlways(e.target.checked)} />
                        本 Run 始终允许
                      </label>
                    )}
                    <div className="mt-2 flex gap-2">
                      <button
                        className="rounded-full px-3 py-1 text-[#0a0b0e] disabled:opacity-40"
                        style={{ background: "var(--gradient-brand)" }}
                        disabled={syncBusy}
                        onClick={() => void confirmWriteAuth()}
                      >
                        确认同步
                      </button>
                      <button
                        className="rounded-full border px-3 py-1 disabled:opacity-40"
                        style={{ borderColor: "var(--color-line)" }}
                        disabled={syncBusy}
                        onClick={() => { setWriteConfirmOpen(false); setWriteAlways(false); }}
                      >
                        取消
                      </button>
                    </div>
                  </div>
                )}
              </section>
            )}
          </div>
        )}

        {tab === "decisions" && (
          <section className="space-y-4">
            {(run?.change_request || run?.requirement_feedback?.length) && <div><h3 className="mb-2 text-xs font-medium text-muted">需求变更</h3><ul className="space-y-2">{[...new Set([run?.change_request, ...(run?.requirement_feedback || []).map((item) => item.feedback)].filter((text): text is string => Boolean(text)))].map((text) => <li key={text} className="rounded-xl border border-line bg-background px-3 py-2 text-xs leading-6">{text}</li>)}</ul></div>}
            <div className="mb-2 text-xs font-medium" style={{ color: "var(--color-muted)" }}>决策台账</div>
            {(() => {
              const ledger = summarizeDecisionLedger(run?.decisions);
              if (ledger.total === 0) {
                return (
                  <div className="text-sm" style={{ color: "var(--color-muted)" }}>
                    暂无决策
                  </div>
                );
              }
              return (
                <div className="space-y-2">
                  <div className="text-[11px]" style={{ color: "var(--color-muted)" }}>
                    已答 {ledger.answered} / {ledger.total}
                    {ledger.pending > 0 ? ` · 待答 ${ledger.pending}` : ""}
                  </div>
                  <ul className="space-y-2">
                    {ledger.lines.map((line) => (
                      <li
                        key={line.code}
                        className="rounded-xl border px-3 py-2 text-xs"
                        style={{ borderColor: "var(--color-line)", background: "var(--color-bg)" }}
                      >
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="font-mono text-[10px]" style={{ color: "var(--color-muted)" }}>
                            {line.code}
                          </span>
                          {line.critical && (
                            <span
                              className="rounded-full px-1.5 py-0.5 text-[10px] text-[#0a0b0e]"
                              style={{ background: "var(--gradient-brand)" }}
                            >
                              关键
                            </span>
                          )}
                        </div>
                        <div className="mt-1 font-medium leading-snug">{line.question}</div>
                        <div className="mt-1 leading-snug" style={{ color: "var(--color-muted)" }}>
                          {line.answer ? `答：${line.answer}` : "待回答"}
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })()}
          </section>
        )}

        {tab === "artifacts" && (
          <section className="min-h-0 min-w-0">
            <div className="mb-2 text-xs font-medium" style={{ color: "var(--color-muted)" }}>产物</div>
            {!run || visibleArtifacts.length === 0 ? (
              <div className="flex flex-col items-center gap-3 rounded-2xl border border-dashed border-line px-6 py-12 text-center text-muted">
                <FolderOpen size={27} strokeWidth={1.3} />
                <p className="text-sm font-medium">{artifacts.length === 0 ? "你的成果会出现在这里" : "当前视角暂无可查看产物"}</p>
                <p className="max-w-[260px] text-xs leading-6">{artifacts.length === 0 ? "先在对话区确定需求，生成的文档、代码和说明会集中放在这里。" : "切换开发视角可查看代码与检查记录。"}</p>
              </div>
            ) : (
              <div className="space-y-2">
                <div className="flex flex-wrap gap-1">
                  {visibleArtifacts.map((a) => (
                    <button
                      key={a.id}
                      className={cn("rounded-full border px-2 py-0.5 text-xs", selected?.id === a.id ? "bg-brand-soft" : "")}
                      style={{ borderColor: "var(--color-line)" }}
                      onClick={() => { if (focusRequest) appliedFocus.current = focusRequest.sequence; setSelected(a); }}
                    >
                      {a.kind === "prd" ? `${a.id === visibleArtifacts.find((item) => item.kind === "prd")?.id ? "最新 PRD" : "历史 PRD"} · 第 ${visibleArtifacts.filter((item) => item.kind === "prd" && item.id <= a.id).length} 稿` : a.title}
                    </button>
                  ))}
                </div>
                {role === "pm" && artifacts.length > visibleArtifacts.length && (
                  <div className="text-[11px]" style={{ color: "var(--color-muted)" }}>
                    已隐藏 {artifacts.length - visibleArtifacts.length} 项工厂证据；切换到「开发者」可查看代码与闸门明细。
                  </div>
                )}
                {selected && (
                  selected.kind === "prd" || selected.kind === "deploy" || selected.kind === "readme" ? (
                    <div
                      className="prose-product max-h-[60vh] max-w-none overflow-x-hidden overflow-y-auto rounded-xl border p-3 text-xs leading-relaxed"
                      style={{ borderColor: "var(--color-line)", background: "var(--color-bg)" }}
                    >
                      {selected.kind === "prd" && <p className="text-xs font-medium" style={{ color: selected.id === visibleArtifacts.find((item) => item.kind === "prd")?.id ? "var(--ok)" : "var(--warn)" }}>{selected.id === visibleArtifacts.find((item) => item.kind === "prd")?.id ? "当前最新 PRD，用于本次确认。" : "正在查看历史稿。本次确认以最新 PRD 为准。"}</p>}
                      <ReactMarkdown remarkPlugins={[remarkGfm]} components={productMarkdownComponents}>{selected.content || "加载中…"}</ReactMarkdown>
                    </div>
                  ) : (
                    <pre className="max-h-[60vh] overflow-auto rounded-lg border border-line p-3 text-[11px] leading-relaxed" style={{ background: "var(--paper-2)", color: "var(--ink)", whiteSpace: "pre-wrap" }}>
                      {selected.content || "加载中…"}
                    </pre>
                  )
                )}
              </div>
            )}
          </section>
        )}

        {tab === "quality" && role === "dev" && (
          <section className="space-y-3">
            {run?.execution_mode === "agent_team" && <InternalExecutionDetails run={run} onResume={onResume} />}
            <div>
              <div className="mb-2 text-xs font-medium" style={{ color: "var(--color-muted)" }}>本 Run 模型</div>
              <div className="rounded-lg p-2.5 text-sm" style={{ background: "var(--color-bg)" }}>
                提供商 <b style={{ color: "var(--color-primary)" }}>{run?.llm_provider || "跟随全局"}</b>
                <span className="mx-2 opacity-40">·</span>
                模型 <b style={{ color: "var(--color-primary)" }}>{run?.llm_model || "—"}</b>
              </div>
            </div>
            <div>
              <div className="mb-2 text-xs font-medium" style={{ color: "var(--color-muted)" }}>工厂度量</div>
              {metrics ? (
                <div className="space-y-1.5 text-sm">
                  <div className="rounded-lg p-2.5" style={{ background: "var(--color-bg)" }}>稳定出货率 <b style={{ color: "var(--color-primary)" }}>{(metrics.ship_rate * 100).toFixed(1)}%</b></div>
                  <div className="rounded-lg p-2.5" style={{ background: "var(--color-bg)" }}>平均成本 <b style={{ color: "var(--color-primary)" }}>¥{metrics.avg_cost.toFixed(4)}</b></div>
                  <div className="rounded-lg p-2.5" style={{ background: "var(--color-bg)" }}>平均耗时 <b style={{ color: "var(--color-primary)" }}>{metrics.avg_duration}s</b></div>
                </div>
              ) : (
                <div className="text-sm" style={{ color: "var(--color-muted)" }}>加载中…</div>
              )}
            </div>
            <div>
              <div className="mb-2 text-xs font-medium" style={{ color: "var(--color-muted)" }}>对比 PRD 草稿</div>
              <p className="mb-2 text-[11px]" style={{ color: "var(--color-muted)" }}>会调用已配置模型，可能产生费用；不会创建新 Run。</p>
              <button
                className="rounded-full border px-3 py-1.5 text-xs disabled:opacity-40"
                style={{ borderColor: "var(--color-line)" }}
                disabled={compareBusy || !(run?.idea || "").trim()}
                onClick={async () => {
                  if (!run?.idea) return;
                  setCompareBusy(true);
                  setCompareErr(null);
                  try {
                    const r = await comparePrd(run.idea, run.decisions.map((decision) => ({
                      code: decision.code,
                      question: decision.question,
                      options: decision.options,
                      recommendation: decision.recommendation,
                      answer: decision.answer ?? "",
                    })));
                    setCompareVariants(r.variants);
                  } catch (e) {
                    setCompareErr((e as Error).message);
                  } finally {
                    setCompareBusy(false);
                  }
                }}
              >
                {compareBusy ? "对比中…" : "用当前想法对比"}
              </button>
              {compareErr && <div className="mt-2 text-xs" style={{ color: "var(--color-danger)" }}>{compareErr}</div>}
              {compareVariants.length > 0 && (
                <div className="mt-2 grid gap-2">
                  {compareVariants.map((v) => (
                    <div key={v.provider} className="rounded-lg border p-2 text-xs" style={{ borderColor: "var(--color-line)" }}>
                      <div className="mb-1 font-medium">{v.provider} · {v.model}</div>
                      {v.error ? (
                        <div style={{ color: "var(--color-danger)" }}>{v.error}</div>
                      ) : (
                        <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words opacity-90">
                          {typeof v.prd?.title === "string"
                            ? `${v.prd.title}

${String(v.prd.summary || v.prd.overview || "").slice(0, 600)}`
                            : JSON.stringify(v.prd, null, 2).slice(0, 800)}
                        </pre>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>
        )}
      </div>
    </div>
  );

}

/* ---------- 登录页 ---------- */
/* ---------- 登录页 ---------- */

function LoginScreen({ onLoggedIn }: { onLoggedIn: (phone: string) => void }) {
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const phoneRef = useRef<HTMLInputElement>(null);
  const codeRef = useRef<HTMLInputElement>(null);

  async function handleRequestCode() {
    const p = phone.trim() || phoneRef.current?.value.trim() || "";
    if (!p) {
      setErr("请先填写手机号");
      return;
    }
    if (p !== phone) setPhone(p);
    setErr(null);
    setBusy(true);
    try {
      const r = await requestCode(p);
      setSent(true);
      if (r.mock_code) setCode(r.mock_code); // mock 短信：验证码直接显示，本地零成本
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleLogin() {
    const p = phone.trim() || phoneRef.current?.value.trim() || "";
    const c = code.trim() || codeRef.current?.value.trim() || "";
    if (!p) {
      setErr("请先填写手机号");
      return;
    }
    if (!c) {
      setErr("请先填写验证码");
      return;
    }
    if (p !== phone) setPhone(p);
    if (c !== code) setCode(c);
    setErr(null);
    setBusy(true);
    try {
      const r = await login(p, c);
      setToken(r.token);
      onLoggedIn(r.phone);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const inputStyle = { borderColor: "var(--color-line)", background: "var(--color-bg)" };
  return (
    <div className="login-screen flex h-dvh items-center justify-center px-4" style={{ background: "var(--color-bg)" }}>
      <div className="w-full max-w-sm rounded-2xl border p-6" style={{ borderColor: "var(--color-line)", background: "var(--color-surface)" }}>
        <div className="factory-logo"><Layers3 size={22} /></div>
        <div className="mt-5 text-xl font-semibold tracking-tight">欢迎来到 Agent 造物坊</div>
        <div className="mt-2 text-sm leading-6 text-muted">从想法到可用的第一版。登录后继续你的项目。</div>
        <div className="mt-4 flex gap-2">
          <input
            ref={phoneRef}
            className="input-field min-w-0 flex-1"
            style={inputStyle}
            placeholder="手机号"
            name="phone"
            type="tel"
            autoComplete="tel"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            onInput={(e) => setPhone((e.target as HTMLInputElement).value)}
            onKeyDown={(e) => e.key === "Enter" && handleRequestCode()}
          />
          <button className="button-primary shrink-0" onClick={handleRequestCode} disabled={busy}>
            获取验证码
          </button>
        </div>
        {sent && (
          <div className="mt-3 flex gap-2">
            <input
              ref={codeRef}
              className="input-field min-w-0 flex-1"
              style={inputStyle}
              placeholder="验证码"
              name="code"
              autoComplete="one-time-code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              onInput={(e) => setCode((e.target as HTMLInputElement).value)}
              onKeyDown={(e) => e.key === "Enter" && handleLogin()}
            />
            <button className="button-primary" onClick={handleLogin} disabled={busy}>
              登录
            </button>
          </div>
        )}
        {err && <div role="alert" className="mt-3 text-xs" style={{ color: "var(--color-danger)" }}>{err}</div>}
        <p className="mt-4 text-[11px] leading-5 text-muted">使用手机号验证码登录。本地模式下，验证码会自动填入。</p>
      </div>
    </div>
  );
}

export default function Page() {
  const { run, submit, answer, confirm, restore, cancel, retry, retest, isTerminal, failure, reset, requirements, saveScenarios, saveResults, revise } = useFactoryRun();
  const [idea, setIdea] = useState("");
  const [llmProvider, setLlmProvider] = useState<string>("");
  const [executionMode, setExecutionMode] = useState<ExecutionMode>("agent_team");
  const [workspaceView, setWorkspaceView] = useState<"work" | "review">("work");
  const [llmProfiles, setLlmProfiles] = useState<LlmProfile[]>([]);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [runList, setRunList] = useState<RunSummary[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [deletedProjects, setDeletedProjects] = useState<Project[]>([]);
  const [deleteTarget, setDeleteTarget] = useState<Project | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [projectNotice, setProjectNotice] = useState<string | null>(null);
  const listRequest = useRef(0);
  const [syncStatus, setSyncStatus] = useState("正在同步项目…");
  const autoRunIds = useRef<Set<string> | null>(null);
  const [scheduleNotice, setScheduleNotice] = useState<{ id: string; idea: string } | null>(null);
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [role, setRole] = useState<ViewRole>("pm");
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [outputFocus, setOutputFocus] = useState<OutputFocus | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [reviewTab, setReviewTab] = useState<"requirements" | "scenarios">("requirements");
  const [execConfirmOpen, setExecConfirmOpen] = useState(false);
  const [execAlways, setExecAlways] = useState(false);
  const [execBusy, setExecBusy] = useState(false);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const actionPending = useRef(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [scenarioDraft, setScenarioDraft] = useState<{ runId: string; items: AcceptanceScenario[] } | null>(null);
  const [revisionDraft, setRevisionDraft] = useState<{ runId: string; text: string; key: string } | null>(null);
  useEffect(() => {
    if (!revisionDraft || revisionDraft.runId !== run?.id) return;
    const field = document.querySelector<HTMLTextAreaElement>("#revision-form textarea");
    field?.scrollIntoView({ behavior: "smooth", block: "center" });
    field?.focus({ preventScroll: true });
  }, [revisionDraft, run?.id]);
  const scenarios = useMemo(() => {
    if (run && scenarioDraft?.runId === run.id) return scenarioDraft.items;
    if (run?.acceptance_scenarios?.length) return run.acceptance_scenarios;
    return [{ id: "main-flow", title: "主流程是否走通", input: "", expected_output: "" }];
  }, [run, scenarioDraft]);
  const scenarioDirty = JSON.stringify(scenarios) !== JSON.stringify(run?.acceptance_scenarios || []);
  const scenarioIssue = run?.acceptance_mode === "scenario" ? acceptanceScenarioError(scenarios) : null;
  const confirmHint = run?.acceptance_mode === "scenario"
    ? scenarioIssue || (scenarioDirty ? "请先保存验收场景中的修改。" : undefined)
    : undefined;

  async function withMutation(label: string, operation: () => Promise<void>) {
    if (actionPending.current) throw new Error("正在处理上一步，请稍后再试。");
    actionPending.current = true;
    setActionBusy(label);
    setActionError(null);
    try { await operation(); }
    finally { actionPending.current = false; setActionBusy(null); }
  }

  function showActionError(error: unknown) {
    setActionError(error instanceof Error ? error.message : "操作未完成，请重试。");
  }

  useEffect(() => {
    try {
      const saved = localStorage.getItem("factory_view_role");
      if (saved === "pm" || saved === "dev") setRole(saved);
    } catch {
      /* ignore */
    }
  }, []);

  function handleRoleChange(next: ViewRole) {
    setRole(next);
    try {
      localStorage.setItem("factory_view_role", next);
    } catch {
      /* ignore */
    }
  }
  const [leftWidth, setLeftWidth] = useState(224);
  const [rightWidth, setRightWidth] = useState(520);
  const [phone, setPhone] = useState<string | null>(null);
  // 首屏固定 checking，避免 SSR(无 localStorage) 与客户端(有 token) 首帧不一致导致 hydration Issue
  const [authPhase, setAuthPhase] = useState<"guest" | "checking" | "authed">("checking");

  function startDrag(side: "left" | "right") {
    return (e: React.MouseEvent) => {
      e.preventDefault();
      const startX = e.clientX;
      const startW = side === "left" ? leftWidth : rightWidth;
      const setW = side === "left" ? setLeftWidth : setRightWidth;
      const onMove = (ev: MouseEvent) => {
        const delta = side === "right" ? startX - ev.clientX : ev.clientX - startX;
        const min = side === "left" ? 180 : 340;
        const max = side === "left" ? 300 : Math.max(340, Math.min(860, window.innerWidth - leftWidth - 420));
        setW(Math.max(min, Math.min(max, startW + delta)));
      };
      const onUp = () => {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    };
  }

  const pendingQuestions = run?.decisions.filter((decision) => decision.status !== "answered") || [];
  const questionCount = run?.decisions.filter((decision) => decision.is_critical || decision.status !== "answered").length || 0;
  const currentQuestion = pendingQuestions[0];

  function openOutput(kind: OutputKind) {
    if (!run) return;
    setOutputFocus({ runId: run.id, sequence: Date.now(), kind });
    if (!window.matchMedia("(min-width: 1280px)").matches) setInspectorOpen(true);
  }

  const loadNavigation = useCallback(async (signal?: AbortSignal) => {
    const request = ++listRequest.current;
    const current = () => !signal?.aborted && request === listRequest.current;
    const results = await Promise.allSettled([
      getRunList(signal).then((data) => {
        if (!current()) return;
        const scheduled = data.runs.filter((item) => item.auto_schedule_id);
        const latest = autoRunIds.current && scheduled.find((item) => !autoRunIds.current!.has(item.id));
        autoRunIds.current = new Set(scheduled.map((item) => item.id));
        setScheduleNotice((notice) => latest ? { id: latest.id, idea: latest.idea } : notice && data.runs.some((item) => item.id === notice.id) ? notice : null);
        setRunList(data.runs);
      }),
      listProjects(false, signal).then((data) => { if (current()) setProjects(data.projects); }),
      listProjects(true, signal).then((data) => { if (current()) setDeletedProjects(data.projects); }),
      listSchedules(signal).then((data) => { if (current()) setSchedules(data); }),
    ]);
    if (!current()) return;
    if (results.some((result) => result.status === "rejected")) {
      setSyncStatus("项目同步暂时中断，正在重试…");
    } else {
      setSyncStatus(`自动更新 · ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`);
    }
  }, []);

  const loadAll = useCallback(() => {
    // 复盘统计不应阻塞新项目发现。
    void loadNavigation();
    const request = listRequest.current;
    getMetrics().then((data) => { if (request === listRequest.current) setMetrics(data); }).catch(() => {});
  }, [loadNavigation]);

  function requestProjectDelete(id: string) {
    if (actionPending.current) return;
    const project = projects.find((item) => item.id === id);
    if (!project) return;
    setDeleteError(null);
    setDeleteTarget(project);
  }

  async function handleProjectDelete() {
    if (!deleteTarget || actionPending.current) return;
    const project = deleteTarget;
    setDeleteError(null);
    try {
      await withMutation("delete-project", async () => {
        await deleteProject(project.id);
        ++listRequest.current;
        setProjects((items) => items.filter((item) => item.id !== project.id));
        setRunList((items) => items.filter((item) => item.project_id !== project.id));
        setDeletedProjects((items) => [project, ...items.filter((item) => item.id !== project.id)]);
        setSchedules((items) => items.map((item) => item.project_id === project.id ? { ...item, enabled: false } : item));
        if (run?.project_id === project.id) {
          reset();
          setScenarioDraft(null);
          setRevisionDraft(null);
          setInspectorOpen(false);
          setWorkspaceView("work");
          setReviewTab("requirements");
        }
        setDeleteTarget(null);
        setProjectNotice("项目已移入回收站，可在左侧回收站恢复。");
        loadAll();
      });
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : "删除未完成，请重试。");
    }
  }

  async function handleProjectRestore(id: string) {
    if (actionPending.current) return;
    try {
      await withMutation("restore-project", async () => {
        const project = await restoreProject(id);
        ++listRequest.current;
        setDeletedProjects((items) => items.filter((item) => item.id !== id));
        setProjects((items) => [project, ...items.filter((item) => item.id !== id)]);
        setProjectNotice("项目已恢复，关联的定时任务保持暂停。");
        loadAll();
      });
    } catch (error) { showActionError(error); }
  }

  async function handleCreateSchedule(idea: string, triggerTime: string) {
    const schedule = await createSchedule({ idea, trigger_time: triggerTime });
    ++listRequest.current;
    setSchedules((items) => [schedule, ...items.filter((item) => item.id !== schedule.id)]);
  }

  async function handleToggleSchedule(s: Schedule) {
    await updateSchedule(s.id, { enabled: !s.enabled });
    listSchedules().then(setSchedules).catch(() => {});
  }

  async function handleDeleteSchedule(id: string) {
    await deleteSchedule(id);
    listSchedules().then(setSchedules).catch(() => {});
  }

  // 挂载后再读 token，保证 SSR/CSR 首帧同为「加载中…」
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      if (!getToken()) {
        if (!cancelled) setAuthPhase("guest");
        return;
      }
      try {
        const r = await fetchMe();
        if (cancelled) return;
        setPhone(r.phone);
        setAuthPhase("authed");
        loadAll();
        getLlmProfiles()
          .then((d) => {
            setLlmProfiles(d.profiles);
            setLlmProvider((prev) => prev || "");
          })
          .catch(() => {});
        const saved = localStorage.getItem("factory_run_id");
        if (saved) restore(saved).catch(() => {});
      } catch {
        clearToken();
        if (!cancelled) setAuthPhase("guest");
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (run?.current_stage === "delivered" || run?.current_stage === "awaiting_acceptance" || run?.current_stage === "gate_failed" || run?.current_stage === "failed") {
      loadAll();
    }
  }, [run?.current_stage]);

  // 前台每 5 秒同步，切回页面立即同步；慢请求不叠加，也不改变当前选中的项目。
  useEffect(() => {
    if (authPhase !== "authed") return;
    const loop = startWorkspaceSync({
      refresh: loadNavigation,
      isVisible: () => document.visibilityState === "visible",
      onError: () => setSyncStatus("项目同步暂时中断，正在重试…"),
    });
    const metricsLoop = startWorkspaceSync({
      refresh: async (signal) => {
        const data = await getMetrics(signal);
        if (!signal.aborted) setMetrics(data);
      },
      isVisible: () => document.visibilityState === "visible",
      onError: () => {},
      intervalMs: 30000,
    });
    window.addEventListener("focus", loop.sync);
    window.addEventListener("online", loop.sync);
    document.addEventListener("visibilitychange", loop.sync);
    return () => {
      loop.stop();
      metricsLoop.stop();
      window.removeEventListener("focus", loop.sync);
      window.removeEventListener("online", loop.sync);
      document.removeEventListener("visibilitychange", loop.sync);
      ++listRequest.current;
    };
  }, [authPhase, loadNavigation]);

  async function handleSend() {
    const text = idea.trim();
    if (!text || actionPending.current) return;
    try {
      await withMutation("submit", async () => {
        await submit(text, { llm_provider: llmProvider || undefined, execution_mode: executionMode });
        setIdea("");
        setScenarioDraft(null);
        setRevisionDraft(null);
        loadAll();
      });
    } catch (error) { showActionError(error); }
  }

  async function handleAnswer(code: string, value: string): Promise<boolean> {
    try {
      await withMutation("answer", async () => { await answer(code, value); setScenarioDraft(null); });
      return true;
    } catch (error) { showActionError(error); return false; }
  }

  async function handleConfirm() {
    if (confirmHint) { setActionError(confirmHint); return; }
    try { await withMutation("confirm", confirm); }
    catch (error) { showActionError(error); }
  }

  async function handleResume() {
    if (!run) return;
    await withMutation("resume", async () => {
      await resumeExecution(run.id);
      await restore(run.id);
    });
  }

  async function handleAccept(checklist: AcceptanceChecklistItem[], results: AcceptanceScenarioResult[] = []) {
    if (!run) return;
    await withMutation("accept", async () => {
      await acceptRun(run.id, checklist, "验收通过", results);
      await restore(run.id);
      loadAll();
    });
  }

  async function handleRequirements(feedback: string) {
    await withMutation("requirements", async () => { await requirements(feedback); setScenarioDraft(null); });
  }

  async function handleSaveScenarios() {
    await withMutation("scenarios", async () => { await saveScenarios(scenarios); setScenarioDraft(null); });
  }

  async function handleMainFlowFeedback(note: string, mainPassed: boolean) {
    if (!run) return;
    await withMutation("results", async () => {
      const scenarios = run.acceptance_scenarios || [];
      const main = mainFlowScenario(scenarios);
      if (run.acceptance_mode === "scenario" && main) {
        await saveResults([
          { scenario_id: main.id, passed: mainPassed, observation: note },
          ...preservedScenarioResults(scenarios, run.acceptance_results || [], main.id),
        ]);
      }
      await rejectRun(run.id, note);
      await restore(run.id);
      const prefix = "请保留已有功能，按下面的反馈修改：\n\n";
      const limit = 4000 - prefix.length;
      const summary = note.length <= limit ? note : `${note.slice(0, limit - 1).replace(/[\uD800-\uDBFF]$/, "")}…`;
      setRevisionDraft({ runId: run.id, text: prefix + summary, key: crypto.randomUUID() });
    });
  }

  async function handleRevise(changeRequest: string, requestId: string) {
    await withMutation("revise", async () => {
      await revise(changeRequest, requestId);
      setScenarioDraft(null);
      setRevisionDraft(null);
      loadAll();
    });
  }

  async function doStartPreview() {
    if (!run) return;
    const r = await startApp(run.id);
    if (r.url) window.open(r.url, "_blank", "noopener");
  }

  async function handlePreview() {
    if (!run) return;
    if (needsWorkspaceAuth(run, "exec")) {
      setExecAlways(false);
      setExecConfirmOpen(true);
      return;
    }
    setExecBusy(true);
    try {
      await doStartPreview();
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setExecBusy(false);
    }
  }

  async function confirmExecAuth() {
    if (!run) return;
    setExecBusy(true);
    try {
      await authorizeWorkspace(run.id, {
        scopes: ["exec"],
        always_for_run: canShowAlwaysAllow(role) && execAlways,
        role,
      });
      await restore(run.id);
      setExecConfirmOpen(false);
      await doStartPreview();
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setExecBusy(false);
    }
  }

  async function handleSelect(id: string) {
    if (actionPending.current) return;
    try {
      await withMutation("navigate", async () => {
        await restore(id);
        setScheduleNotice((notice) => notice?.id === id ? null : notice);
        setSidebarOpen(false);
        setReviewTab("requirements");
        setWorkspaceView("work");
      });
    } catch (error) { showActionError(error); }
  }

  function handleNew() {
    if (actionPending.current) return;
    reset();
    setScenarioDraft(null);
    setRevisionDraft(null);
    setActionError(null);
    setInspectorOpen(false);
    setSidebarOpen(false);
    setReviewTab("requirements");
    setWorkspaceView("work");
  }

  function handleShowReview() {
    if (actionPending.current) return;
    setWorkspaceView("review");
    setSidebarOpen(false);
    setInspectorOpen(false);
  }

  async function handleLoggedIn(p: string) {
    setPhone(p);
    setAuthPhase("authed");
    loadAll();
    getLlmProfiles()
      .then((d) => {
        setLlmProfiles(d.profiles);
        setLlmProvider((prev) => prev || "");
      })
      .catch(() => {});
    const saved = localStorage.getItem("factory_run_id");
    if (saved) restore(saved).catch(() => {});
  }

  function handleLogout() {
    ++listRequest.current;
    autoRunIds.current = null;
    setScheduleNotice(null);
    setSyncStatus("正在同步项目…");
    clearToken();
    reset();
    setPhone(null);
    setAuthPhase("guest");
    setRunList([]);
    setProjects([]);
    setDeletedProjects([]);
    setDeleteTarget(null);
    setProjectNotice(null);
    setMetrics(null);
  }

  if (authPhase === "checking") {
    return <div className="flex h-dvh items-center justify-center text-sm" style={{ color: "var(--color-muted)" }}>加载中…</div>;
  }
  if (!phone) {
    return <LoginScreen onLoggedIn={handleLoggedIn} />;
  }

  return (
    <div className="workspace-shell flex h-dvh overflow-hidden">
      {/* 左栏 */}
      {sidebarOpen && <button aria-label="关闭项目导航" className="fixed inset-0 z-40 bg-black/20 md:hidden" onClick={() => setSidebarOpen(false)} />}
      <aside className={cn("workspace-sidebar min-h-0 shrink-0 flex-col overflow-hidden border-r md:relative md:flex", sidebarOpen ? "fixed inset-y-0 left-0 z-50 flex shadow-xl" : "hidden")} style={{ width: leftWidth, borderColor: "var(--color-line)" }}>
        <TaskList runs={runList} currentId={workspaceView === "work" ? run?.id ?? null : null} currentProjectId={workspaceView === "work" ? run?.project_id ?? null : null} onSelect={handleSelect} onNew={handleNew} busy={!!actionBusy} onReview={handleShowReview} reviewActive={workspaceView === "review"} role={role} onRoleChange={handleRoleChange} projects={projects} deletedProjects={deletedProjects} onDeleteProject={requestProjectDelete} onRestoreProject={(id) => { void handleProjectRestore(id); }} schedules={schedules} onCreateSchedule={handleCreateSchedule} onToggleSchedule={handleToggleSchedule} onDeleteSchedule={handleDeleteSchedule} syncStatus={syncStatus} scheduleNotice={scheduleNotice} />
        {phone && (
          <div className="shrink-0 border-t px-4 py-4 text-xs" style={{ borderColor: "var(--color-line)" }}>
            <div className="flex items-center justify-between gap-2">
              <span className="flex min-w-0 items-center gap-2" style={{ color: "var(--color-muted)" }}><span className="flex h-7 w-7 items-center justify-center rounded-full border border-line bg-panel text-[10px] font-medium text-ink">我</span>{phone.replace(/^(\d{3})\d{4}/, "$1****")}</span>
              <button aria-label="退出登录" className="shrink-0 text-xs text-muted" onClick={handleLogout}><LogOut size={14} /></button>
            </div>
          </div>
        )}
      </aside>

      {/* 左分隔条（拖动调宽） */}
      <div className="hidden w-px shrink-0 cursor-col-resize hover:bg-brand md:block" onMouseDown={startDrag("left")} />

      {/* 中栏：会话 + 内嵌编排 */}
      <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden" style={{ background: "var(--color-bg)" }}>
        <div className="workspace-topbar flex min-h-[60px] shrink-0 items-center gap-3 border-b border-line px-5 md:px-7">
          <button className="text-muted md:hidden" aria-label="打开项目导航" onClick={() => setSidebarOpen(true)}><Menu size={17} /></button>
          <button disabled={!!actionBusy} onClick={handleNew} className="flex shrink-0 items-center gap-2 text-xs text-muted">工作台</button>
          <ChevronRight size={13} className="shrink-0 text-muted" />
          <span className="min-w-0 flex-1 truncate text-xs font-medium">{workspaceView === "review" ? "项目复盘" : run ? run.idea.split("\n")[0] : "创建项目"}</span>
          {!run && <span className="status-badge hidden sm:inline-flex"><span className="h-1.5 w-1.5 rounded-full bg-ok" />本地工作空间</span>}
          {workspaceView === "work" && run && <button aria-label="打开成果区" className="flex shrink-0 items-center gap-2 rounded-lg border border-line bg-panel px-3 py-2 text-xs xl:hidden" onClick={() => setInspectorOpen(true)}><PanelRight size={14} /><span className="hidden sm:inline">成果区</span></button>}
          {workspaceView === "work" && run && !isTerminal && (
            <button className="text-xs text-muted disabled:opacity-40" disabled={!!actionBusy} onClick={() => { void withMutation("cancel", cancel).catch(showActionError); }}>
              停止
            </button>
          )}
        </div>
        {workspaceView === "work" && run && <ProjectVersionPicker run={run} runs={runList} busy={!!actionBusy} role={role} onSelect={handleSelect} />}
        {workspaceView === "work" && run && <WorkflowProgress run={run} />}
        {projectNotice && <div role="status" className="flex shrink-0 items-center justify-between gap-3 border-b border-line bg-brand-soft px-4 py-2 text-xs text-brand"><span>{projectNotice}</span><button aria-label="关闭项目操作提示" className="flex h-6 w-6 shrink-0 items-center justify-center" onClick={() => setProjectNotice(null)}><X size={13} /></button></div>}
        {actionError && <div role="alert" className="border-b px-4 py-2 text-xs" style={{ color: "var(--danger)", background: "var(--danger-soft)", borderColor: "var(--color-line)" }}>{actionError}</div>}
        {workspaceView === "work" && (failure || (run && (run.current_stage === "failed" || run.current_stage === "gate_failed" || run.current_stage === "cancelled"))) && (
          <div className="flex shrink-0 items-start gap-3 border-b px-4 py-2 text-xs" style={{ background: "var(--danger-soft)", color: "var(--danger)", borderColor: "var(--color-line)" }}>
            <div className="min-w-0 flex-1">
              {role === "dev" ? (
                <>
                  <div>
                    ⚠️{" "}
                    {failure
                      || run?.failure_reason
                      || (run?.current_stage === "cancelled" ? "已取消" : "运行失败")}
                  </div>
                  {run?.current_stage && (
                    <div className="mt-0.5 opacity-80">阶段：{STAGE_CN[run.current_stage] || run.current_stage}</div>
                  )}
                </>
              ) : run?.current_stage === "cancelled" ? (
                <div>⚠️ 已取消</div>
              ) : (
                <>
                  <div>⚠️ {pmFailureText(run?.failure_code, run?.failure_reason).message}</div>
                  <div className="mt-0.5 opacity-80">{pmFailureText(run?.failure_code, run?.failure_reason).suggestion}</div>
                </>
              )}
            </div>
            {run && canFullRetry(run.current_stage) && (
              <div className="flex shrink-0 items-center gap-2">
                {canRetestInPlace(run) ? (
                  <button
                    className="rounded-full px-3 py-1 text-xs font-medium text-white transition"
                    style={{ background: "var(--danger)" }}
                    disabled={!!actionBusy}
                    onClick={() => { void withMutation("retest", retest).catch(showActionError); }}
                  >
                    {run.execution_mode === "agent_team" ? "继续验证" : "仅重测"}
                  </button>
                ) : retestFallbackHint(run) ? (
                  <span className="whitespace-nowrap text-right leading-5">{retestFallbackHint(run)}</span>
                ) : null}
                <button
                  className="rounded-full border px-3 py-1 text-xs transition hover:bg-surface-2"
                  style={{ borderColor: "var(--danger)", color: "var(--danger)" }}
                  disabled={!!actionBusy}
                  onClick={() => { void withMutation("retry", async () => { await retry(); setScenarioDraft(null); loadAll(); }).catch(showActionError); }}
                >
                  整段重跑
                </button>
              </div>
            )}
          </div>
        )}
        <div className="workspace-scroll min-h-0 flex-1 overflow-auto">
          {workspaceView === "review" ? <ProjectReview key={projects.map((project) => project.id).join(",")} projects={projects} onSelectRun={handleSelect} onBack={() => setWorkspaceView("work")} /> : !run ? <WorkspaceHome idea={idea} onIdeaChange={setIdea} onSubmit={handleSend} busy={!!actionBusy} provider={llmProvider} profiles={llmProfiles} onProviderChange={setLlmProvider} executionMode={executionMode} onExecutionModeChange={setExecutionMode} /> : (
            <div className="conversation-content mx-auto max-w-[980px] space-y-5 px-5 py-7 md:px-7">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 grow basis-[260px]">
                  <div className="mb-2 flex items-center gap-2 text-[11px] text-muted"><span className="status-badge">{run.parent_run_id ? "修改版" : "初版"}</span><span>{runList.find((item) => item.id === run.id)?.created_at ? formatApiDate(runList.find((item) => item.id === run.id)!.created_at) : "当前项目"}</span><span>·</span><span>{pmStageLabel(run.current_stage)}</span></div>
                  <h1 className="text-xl font-semibold leading-8 tracking-tight">{run.status === "paused" ? "任务已暂停，可以从检查点继续" : run.current_stage === "awaiting_answers" ? "先把关键需求聊清楚" : run.current_stage === "awaiting_prd_confirm" ? "确认这一版要做什么" : run.current_stage === "awaiting_acceptance" ? "确认主流程是否走通" : run.current_stage === "delivered" ? "这一版已完成交付" : ["failed", "gate_failed", "cancelled"].includes(run.current_stage) ? "构建需要你的关注" : "正在把想法变成应用"}</h1>
                  <p className="mt-1 text-xs leading-6 text-muted">{run.current_stage === "awaiting_answers" ? "一次回答一个问题。选择方向，或直接写下你的想法。" : run.current_stage === "awaiting_prd_confirm" ? "在成果区核对需求，在这里确认主流程怎么走通。" : run.current_stage === "awaiting_acceptance" ? "打开成品，走一遍主流程。走通了就可以验收；没走通或还有其他问题，写在反馈里再改一版。" : run.current_stage === "delivered" ? "下载包含源码、需求文档和验证记录的交付包，或继续打磨下一版。" : "阶段进度会自动更新，生成的需求、代码和说明统一放在成果区。"}</p>
                </div>
                {["awaiting_acceptance", "delivered"].includes(run.current_stage) && <div className="flex flex-wrap gap-2"><button className="button-primary" onClick={handlePreview}><ArrowUpRight size={15} />打开成品</button><button className="button-secondary" onClick={() => { const field = document.querySelector<HTMLTextAreaElement>("#revision-form textarea"); field?.scrollIntoView({ behavior: "smooth", block: "center" }); field?.focus({ preventScroll: true }); }}><GitBranch size={15} />提出修改</button></div>}
              </div>
              {run.execution_mode === "agent_team" && run.status === "paused" && <div className="wf-card flex flex-wrap items-center justify-between gap-3 p-5"><div><p className="text-sm font-medium">处理已中断</p><p className="mt-1 text-xs leading-6 text-muted">已保留当前进度，可以继续完成这一版。</p></div><button className="button-primary" disabled={!!actionBusy} onClick={() => { void handleResume().catch(showActionError); }}>{actionBusy === "resume" ? "正在继续…" : "继续处理"}<ArrowRight size={14} /></button></div>}
              {run.current_stage === "awaiting_prd_confirm" && run.acceptance_mode === "scenario" && <div className="flex gap-5 border-b border-line" role="tablist" aria-label="构建前确认"><button role="tab" aria-selected={reviewTab === "requirements"} className={cn("border-b-2 px-1 pb-3 text-xs", reviewTab === "requirements" ? "border-brand font-semibold text-brand" : "border-transparent text-muted")} onClick={() => setReviewTab("requirements")}>需求确认</button><button role="tab" aria-selected={reviewTab === "scenarios"} className={cn("border-b-2 px-1 pb-3 text-xs", reviewTab === "scenarios" ? "border-brand font-semibold text-brand" : "border-transparent text-muted")} onClick={() => setReviewTab("scenarios")}>主流程{scenarioDirty && <span className="ml-1 text-warn">· 未保存</span>}</button></div>}
              {run.current_stage === "awaiting_answers" && currentQuestion && <DecisionPrompt key={`${run.id}-${currentQuestion.code}`} decision={currentQuestion} questionNumber={questionCount - pendingQuestions.length + 1} totalQuestions={questionCount} busy={!!actionBusy} onAnswer={handleAnswer} />}
              {run.current_stage === "awaiting_prd_confirm" && (reviewTab === "requirements" || run.acceptance_mode !== "scenario") && <div className="xl:hidden"><button type="button" onClick={() => openOutput("prd")} className="button-secondary"><FolderOpen size={16} />查看需求文档</button></div>}
              {(run.current_stage === "awaiting_answers" || run.current_stage === "awaiting_prd_confirm") && <div hidden={run.current_stage === "awaiting_prd_confirm" && run.acceptance_mode === "scenario" && reviewTab !== "requirements"}><details className="rounded-xl border border-line bg-panel"><summary className="cursor-pointer px-5 py-4 text-xs font-medium text-muted">{run.current_stage === "awaiting_answers" ? "补充整体需求或约束" : "这版需求需要调整？"}</summary><div className="border-t border-line p-4"><RequirementsForm key={`requirements-${run.id}`} busy={!!actionBusy} onSubmit={handleRequirements} /></div></details></div>}
              {run.current_stage === "awaiting_prd_confirm" && reviewTab === "requirements" && <details className="rounded-xl border border-line bg-panel"><summary className="cursor-pointer px-5 py-4 text-xs font-medium text-muted">修改已确认的决策</summary><div className="border-t border-line p-5"><DecisionsInline decisions={run.decisions} onAnswer={handleAnswer} stage={run.current_stage} busy={!!actionBusy} /></div></details>}
              {run.acceptance_mode === "scenario" && run.current_stage === "awaiting_prd_confirm" && reviewTab === "scenarios" && <AcceptanceScenariosEditor key={`scenarios-${run.id}`} scenarios={scenarios} dirty={scenarioDirty} busy={!!actionBusy} onChange={(items) => setScenarioDraft({ runId: run.id, items })} onSave={handleSaveScenarios} />}
              {run.current_stage === "awaiting_prd_confirm" && <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-panel p-4"><div><div className="text-sm font-medium">需求与验收场景准备好了？</div><p className="mt-1 text-xs text-muted">{confirmHint || "确认后将按当前需求构建，后续仍可继续迭代。"}</p></div><button className="button-primary" disabled={!!actionBusy || !!confirmHint} onClick={handleConfirm}>确认需求，开始构建<ArrowRight size={15} /></button></div>}
              {run.current_stage === "awaiting_acceptance" && <MainFlowAcceptance key={run.id} run={run} busy={!!actionBusy} onAccept={handleAccept} onFeedback={handleMainFlowFeedback} />}
              {run.current_stage === "delivered" && <AcceptanceRecord run={run} />}
              <BundleDownload key={`bundle-${run.id}`} run={run} />
              {canReviseRun(run) && <RevisionForm key={`revision-${run.id}-${revisionDraft?.runId === run.id ? revisionDraft.key : "manual"}`} initialText={revisionDraft?.runId === run.id ? revisionDraft.text : ""} busy={!!actionBusy} onSubmit={handleRevise} />}
              {run.status !== "paused" && !["awaiting_answers", "awaiting_prd_confirm", "awaiting_acceptance", "delivered", "failed", "gate_failed", "cancelled"].includes(run.current_stage) && <div className="wf-card flex items-center gap-4 p-5"><span className="h-5 w-5 animate-spin rounded-full border-2 border-brand-soft border-t-brand" /><div><p className="text-sm font-medium">{pmStageLabel(run.current_stage)}</p><p className="mt-1 text-xs text-muted">正在处理当前步骤，完成后会自动进入下一阶段。</p></div></div>}
              {role === "dev" && <details className="rounded-xl border border-line bg-panel"><summary className="cursor-pointer px-5 py-4 text-xs text-muted">开发阶段详情</summary><SessionRail run={run} role={role} onConfirm={handleConfirm} confirmDisabled={!!actionBusy || !!confirmHint} confirmHint={confirmHint} /></details>}
            </div>
          )}
        </div>
      </main>

      {/* 右分隔条 */}
      {workspaceView === "work" && run && <div className="hidden w-px shrink-0 cursor-col-resize hover:bg-brand xl:block" onMouseDown={startDrag("right")} />}

      {/* 右栏：预览 */}
      {workspaceView === "work" && run && <aside className={cn("min-h-0 shrink-0 flex-col overflow-hidden border-l bg-panel", inspectorOpen ? "fixed bottom-0 right-0 top-0 z-40 flex w-[min(92vw,600px)] shadow-xl" : "hidden xl:flex")} style={{ width: inspectorOpen ? undefined : `min(${rightWidth}px, 44vw)`, borderColor: "var(--color-line)" }}>
        {inspectorOpen && <div className="flex h-12 shrink-0 items-center justify-between border-b border-line px-4 text-sm font-medium">成果区<button aria-label="关闭成果区" onClick={() => setInspectorOpen(false)}><X size={17} /></button></div>}
        <div className="min-h-0 flex-1">
        <PreviewPanel
          key={run.id}
          run={run}
          metrics={metrics}
          role={role}
          onPreview={handlePreview}
          onRunRefresh={async () => { if (run) await restore(run.id); }}
          onResume={handleResume}
          focusRequest={outputFocus}
        />
        </div>
      </aside>}

      {deleteTarget && <ProjectDeleteDialog key={deleteTarget.id} project={deleteTarget} busy={actionBusy === "delete-project"} error={deleteError} onCancel={() => { if (!actionPending.current) { setDeleteTarget(null); setDeleteError(null); } }} onConfirm={() => { void handleProjectDelete(); }} />}

      {execConfirmOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
          <div className="w-full max-w-sm rounded-2xl border p-4 shadow-lg" style={{ borderColor: "var(--color-line)", background: "var(--color-surface)" }}>
            <div className="text-sm font-semibold">确认启动本地预览？</div>
            <div className="mt-2 text-xs" style={{ color: "var(--color-muted)" }}>
              将在本机启动本轮产物的预览进程（仅本机可访问）。
            </div>
            {canShowAlwaysAllow(role) && (
              <label className="mt-3 flex items-center gap-2 text-xs">
                <input type="checkbox" checked={execAlways} onChange={(e) => setExecAlways(e.target.checked)} />
                本 Run 始终允许
              </label>
            )}
            <div className="mt-4 flex justify-end gap-2">
              <button
                className="rounded-full border px-3 py-1.5 text-xs disabled:opacity-40"
                style={{ borderColor: "var(--color-line)" }}
                disabled={execBusy}
                onClick={() => { setExecConfirmOpen(false); setExecAlways(false); }}
              >
                取消
              </button>
              <button
                className="rounded-full px-3 py-1.5 text-xs text-[#0a0b0e] disabled:opacity-40"
                style={{ background: "var(--gradient-brand)" }}
                disabled={execBusy}
                onClick={() => void confirmExecAuth()}
              >
                {execBusy ? "启动中…" : "确认启动"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
