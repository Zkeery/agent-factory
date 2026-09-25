"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Search, Send } from "lucide-react";
import ReactMarkdown from "react-markdown";
import {
  acceptRun,
  authorizeWorkspace,
  canFullRetry,
  canRetestInPlace,
  canShowAlwaysAllow,
  DEFAULT_ACCEPTANCE_CHECKLIST,
  Artifact,
  ChatMessage,
  Decision,
  deriveMessages,
  filterArtifactsForRole,
  ViewRole,
  getArtifact,
  getMetrics,
  getProject,
  getRunList,
  listArtifacts,
  listProjects,
  Metrics,
  needsWorkspaceAuth,
  PM_STAGE_ORDER,
  pmStageLabel,
  pmFailureText,
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
  AppRunStatus,
} from "@/lib/factory";
import { cn } from "@/lib/utils";

/* ---------- 左栏：任务列表 ---------- */
function TaskList({
  runs,
  currentId,
  onSelect,
  role,
  onRoleChange,
  projectCount,
  schedules,
  onCreateSchedule,
  onToggleSchedule,
  onDeleteSchedule,
}: {
  runs: RunSummary[];
  currentId: string | null;
  onSelect: (id: string) => void;
  role: ViewRole;
  onRoleChange: (r: ViewRole) => void;
  projectCount: number;
  schedules: Schedule[];
  onCreateSchedule: (idea: string, triggerTime: string) => void;
  onToggleSchedule: (s: Schedule) => void;
  onDeleteSchedule: (id: string) => void;
}) {
  const [showNew, setShowNew] = useState(false);
  const [newIdea, setNewIdea] = useState("");
  const [newTime, setNewTime] = useState("09:00");
  return (
    <div className="flex h-full flex-col">
      <div className="m-3 flex items-center gap-2 rounded-lg border px-3 py-2 text-sm" style={{ borderColor: "var(--color-line)", color: "var(--color-muted)" }}>
        <Search size={14} />
        搜索任务
      </div>
      <div className="mx-3 mb-2 flex gap-1 text-xs">
        <button className={cn("rounded-full px-2 py-0.5", role === "pm" ? "bg-brand-soft text-brand-2" : "text-muted")} onClick={() => onRoleChange("pm")}>产品经理</button>
        <button className={cn("rounded-full px-2 py-0.5", role === "dev" ? "bg-brand-soft text-brand-2" : "text-muted")} onClick={() => onRoleChange("dev")}>开发者</button>
      </div>
      {projectCount > 0 && (
        <div className="mx-3 mb-2 text-[11px]" style={{ color: "var(--color-muted)" }}>{projectCount} 个项目</div>
      )}
      <div className="flex-1 space-y-0.5 overflow-auto px-2">
        {runs.map((r) => {
          const failed = r.current_stage === "failed" || r.current_stage === "gate_failed";
          return (
            <button
              key={r.id}
              onClick={() => onSelect(r.id)}
              className={cn(
                "flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition",
                r.id === currentId ? "bg-brand-soft" : "hover:bg-black/5",
              )}
            >
              {r.auto_schedule_id && (
                <span className="shrink-0 rounded-full px-1.5 py-0.5 text-[10px]" style={{ background: "var(--warn-soft)", color: "var(--warn)" }}>自动</span>
              )}
              <span className="min-w-0 flex-1 truncate">{r.idea}</span>
              <span
                className="shrink-0 rounded-full px-2 py-0.5 text-xs"
                style={failed ? { background: "var(--danger-soft)", color: "var(--danger)" } : { background: "var(--brand-soft)", color: "var(--brand)" }}
              >
                {role === "pm" ? pmStageLabel(r.current_stage) : (STAGE_CN[r.current_stage] || r.current_stage)}
              </span>
            </button>
          );
        })}
        {runs.length === 0 && <div className="px-3 py-6 text-center text-sm" style={{ color: "var(--color-muted)" }}>暂无任务</div>}
      </div>
      <div className="shrink-0 border-t px-3 py-2" style={{ borderColor: "var(--color-line)" }}>
        <div className="flex items-center justify-between">
          <span className="text-xs font-medium" style={{ color: "var(--color-muted)" }}>定时任务</span>
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
              <div>
                <div className="mb-1 text-[11px]" style={{ color: "var(--color-muted)" }}>每天时间</div>
                <input
                  className="w-20 rounded-lg border px-2 py-1.5 text-xs outline-none"
                  style={{ borderColor: "var(--color-line)", background: "var(--color-bg)" }}
                  placeholder="09:00"
                  value={newTime}
                  onChange={(e) => setNewTime(e.target.value)}
                />
              </div>
              <button
                className="rounded-full px-3 py-1 text-xs text-[#0a0b0e]"
                style={{ background: "var(--gradient-brand)" }}
                onClick={() => {
                  if (!newIdea.trim()) return;
                  onCreateSchedule(newIdea.trim(), newTime);
                  setNewIdea("");
                  setNewTime("09:00");
                }}
              >
                保存
              </button>
            </div>
          </div>
        )}
        {schedules.length > 0 && (
          <div className="mt-2 space-y-1">
            {schedules.map((s) => (
              <div key={s.id} className="flex items-center gap-1.5 text-xs">
                <span className="min-w-0 flex-1 truncate" style={{ color: s.enabled ? "var(--ink)" : "var(--color-muted)" }}>{s.idea}</span>
                <span style={{ color: "var(--color-muted)" }}>{s.trigger_time}</span>
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
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/* ---------- 中栏：消息气泡 ---------- */

/* ---------- 验收清单勾选（PRD §4.1） ---------- */
function AcceptancePanel({ onAccept }: { onAccept: (checklist: { id: string; label: string; passed: boolean }[]) => void }) {
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const allPassed = DEFAULT_ACCEPTANCE_CHECKLIST.every((i) => checked[i.id]);
  function toggle(id: string) {
    setChecked((prev) => ({ ...prev, [id]: !prev[id] }));
  }
  return (
    <div className="mt-2 rounded-xl bg-warn-soft p-3 text-sm">
      <div className="space-y-1.5">
        {DEFAULT_ACCEPTANCE_CHECKLIST.map((item) => (
          <label key={item.id} className="flex cursor-pointer items-start gap-2 text-xs" style={{ color: "var(--color-muted)" }}>
            <input
              type="checkbox"
              className="mt-0.5"
              checked={!!checked[item.id]}
              onChange={() => toggle(item.id)}
            />
            <span>{item.label}</span>
          </label>
        ))}
      </div>
      <button
        className="mt-3 rounded-full px-4 py-1.5 text-xs text-[#0a0b0e] disabled:opacity-40"
        style={{ background: "var(--gradient-brand)" }}
        disabled={!allPassed}
        onClick={() =>
          onAccept(
            DEFAULT_ACCEPTANCE_CHECKLIST.map((i) => ({
              id: i.id,
              label: i.label,
              passed: !!checked[i.id],
            })),
          )
        }
      >
        验收通过，交付
      </button>
    </div>
  );
}

const BUBBLE_TITLE: Record<string, string> = {
  text: "",
  decisions: "🧭 决策确认",
  prd: "📋 PRD",
  code: "🧩 代码产物",
  deploy: "🚀 运行说明",
  acceptance: "✅ 待验收",
  done: "🎉 已交付",
};

function Bubble({ msg, stage, onAnswer, onAccept, onPreview }: { msg: ChatMessage; stage: string | null; onAnswer: (code: string, value: string) => void; onAccept: (checklist: { id: string; label: string; passed: boolean }[]) => void; onPreview: () => void }) {
  if (msg.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[75%] rounded-[20px] rounded-br-md px-4 py-2.5 text-sm text-[#0a0b0e]" style={{ background: "var(--gradient-brand)" }}>
          {msg.content}
        </div>
      </div>
    );
  }

  const title = BUBBLE_TITLE[msg.kind] || "";

  // AI 消息：卡片化；code/deploy 只展示短摘要，不渲染大段 pre
  return (
    <div className="flex justify-start">
      <div className="max-w-[82%]">
        <div className="mb-1 text-xs" style={{ color: "var(--color-muted)" }}>造物坊 AI</div>
        <div className="rounded-[20px] rounded-bl-md border px-4 py-2.5 text-sm" style={{ borderColor: "var(--color-line)", background: "var(--color-surface)" }}>
          {title && (
            <div className="mb-1.5 text-xs font-semibold" style={{ color: "var(--color-primary)" }}>
              {title}
            </div>
          )}
          {(msg.kind === "text" || msg.kind === "decisions") && msg.content}
          {msg.kind === "decisions" && msg.decisions && (
            <DecisionsInline decisions={msg.decisions} onAnswer={onAnswer} stage={stage} />
          )}
          {msg.kind === "prd" && (
            <div className="mt-1 rounded-xl bg-surface-2 p-3">
              <div className="prose prose-sm prose-invert max-w-none text-xs leading-relaxed" style={{ color: "var(--color-muted)" }}>
                <ReactMarkdown>{msg.content}</ReactMarkdown>
              </div>
            </div>
          )}
          {msg.kind === "code" && (
            <div className="mt-1 rounded-xl bg-surface-2 p-3 text-xs leading-relaxed" style={{ color: "var(--color-muted)" }}>
              {msg.content}
            </div>
          )}
          {msg.kind === "deploy" && (
            <div className="mt-1 rounded-xl bg-surface-2 p-3 text-xs" style={{ color: "var(--color-muted)" }}>
              {msg.content}
            </div>
          )}
          {msg.kind === "acceptance" && (
            <div className="mt-1 space-y-2">
              <div className="rounded-xl bg-warn-soft p-3 text-sm">
                <div className="font-medium">{msg.content}</div>
              </div>
              {stage === "awaiting_acceptance" && <AcceptancePanel onAccept={onAccept} />}
            </div>
          )}
          {msg.kind === "done" && (
            <div className="mt-1 rounded-xl bg-ok-soft p-3 text-sm">
              <div className="font-medium" style={{ color: "var(--color-ok)" }}>{msg.content}</div>
              <button className="mt-2 rounded-full px-4 py-1.5 text-xs text-[#0a0b0e] transition hover:opacity-90" style={{ background: "var(--gradient-brand)" }} onClick={onPreview}>
                预览成品 →
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ---------- 决策卡快捷按钮 ---------- */
function DecisionsInline({ decisions, onAnswer, stage }: { decisions: Decision[]; onAnswer: (code: string, value: string) => void; stage: string | null }) {
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
          <button key={o} className="rounded-full px-4 py-1.5 text-xs transition hover:opacity-80" style={{ background: "var(--surface-2)", color: "var(--ink-soft)" }} onClick={() => { onAnswer(d.code, o); setEditing(null); }}>
            {o}
          </button>
        );
      })}
      <button className="rounded-full px-4 py-1.5 text-xs text-[#0a0b0e] transition hover:opacity-90" style={{ background: "var(--gradient-brand)" }} onClick={() => { onAnswer(d.code, "按推荐"); setEditing(null); }}>
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
            {d.is_critical ? "✓" : "⚙️"} {d.question} → {d.answer}
            {!d.is_critical && editable && (
              <>
                <span style={{ color: "var(--color-muted)" }}>（已按推荐自动）</span>
                <button className="ml-2 rounded-full px-2 py-0.5 text-xs transition hover:opacity-80" style={{ background: "var(--surface-2)", color: "var(--ink-soft)" }} onClick={() => setEditing(editing === d.code ? null : d.code)}>
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
  onAccept,
}: {
  run: ReturnType<typeof useFactoryRun>["run"];
  role: ViewRole;
  onConfirm: () => void;
  onAccept: (checklist: { id: string; label: string; passed: boolean }[]) => void;
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
              <button className="rounded-full px-3 py-1 text-xs text-[#0a0b0e]" style={{ background: "var(--gradient-brand)" }} onClick={onConfirm}>
                确认 PRD
              </button>
            </>
          )}
          {current === "awaiting_acceptance" && (
            <>
              <span className="h-1.5 w-1.5 animate-pulse-dot rounded-full" style={{ background: "var(--warn)" }} />
              <span className="text-xs font-medium" style={{ color: "var(--warn)" }}>
                待验收：请在下方对话区勾选验收清单，点「验收通过，交付」
              </span>
            </>
          )}
        </div>
      )}
    </div>
  );
}

/* ---------- 预览栏：产物 + 本地运行 ---------- */
function PreviewPanel({
  run,
  metrics,
  role,
  onPreview,
  onRunRefresh,
}: {
  run: ReturnType<typeof useFactoryRun>["run"];
  metrics: Metrics | null;
  role: ViewRole;
  onPreview: () => void | Promise<void>;
  onRunRefresh: () => Promise<void>;
}) {
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [selected, setSelected] = useState<Artifact | null>(null);
  const visibleArtifacts = filterArtifactsForRole(artifacts, role);
  const [workspace, setWorkspace] = useState("");
  const [previewBusy, setPreviewBusy] = useState(false);
  const [stopBusy, setStopBusy] = useState(false);
  const [appStatus, setAppStatus] = useState<AppRunStatus | null>(null);
  const [syncBusy, setSyncBusy] = useState(false);
  const [writeConfirmOpen, setWriteConfirmOpen] = useState(false);
  const [writeAlways, setWriteAlways] = useState(false);
  type PreviewTab = "run" | "decisions" | "artifacts" | "quality";
  const [tab, setTab] = useState<PreviewTab>("run");
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
        setArtifacts(items);
        setSelected((prev) => items.find((a) => a.id === prev?.id) || items[0] || null);
      })
      .catch(() => {
        if (!cancelled) setArtifacts([]);
      });
    return () => {
      cancelled = true;
    };
  }, [runId, run?.current_stage, run?.evidence?.length]);

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

  // 默认页签：切换 Run 时有产物优先「产物」，否则「运行」；产物首次到达且仍在「运行」则切到「产物」
  useEffect(() => {
    const has = filterArtifactsForRole(artifacts, role).length > 0;
    setTab(has ? "artifacts" : "run");
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 仅随 Run 切换重置默认
  }, [runId]);

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
        <div className="mb-2 text-sm font-semibold">预览</div>
        <div className="flex flex-wrap gap-1 pb-2">
          {(
            [
              { id: "run" as const, label: "运行" },
              { id: "decisions" as const, label: "决策" },
              { id: "artifacts" as const, label: "产物" },
              ...(role === "dev" ? [{ id: "quality" as const, label: "质量" }] : []),
            ]
          ).map((t) => (
            <button
              key={t.id}
              className={cn(
                "rounded-full px-3 py-1 text-xs",
                tab === t.id ? "text-[#0a0b0e]" : "border",
              )}
              style={
                tab === t.id
                  ? { background: "var(--gradient-brand)" }
                  : { borderColor: "var(--color-line)", color: "var(--color-muted)" }
              }
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-auto p-4">
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
          <section>
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
          <section className="min-h-0">
            <div className="mb-2 text-xs font-medium" style={{ color: "var(--color-muted)" }}>产物</div>
            {!run || visibleArtifacts.length === 0 ? (
              <div className="text-sm" style={{ color: "var(--color-muted)" }}>
                {!run || artifacts.length === 0
                  ? "暂无产物"
                  : "当前视图无可预览产物（代码与闸门证据仅开发者可见）"}
              </div>
            ) : (
              <div className="space-y-2">
                <div className="flex flex-wrap gap-1">
                  {visibleArtifacts.map((a) => (
                    <button
                      key={a.id}
                      className={cn("rounded-full border px-2 py-0.5 text-xs", selected?.id === a.id ? "bg-brand-soft" : "")}
                      style={{ borderColor: "var(--color-line)" }}
                      onClick={() => setSelected(a)}
                    >
                      {a.title}
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
                      className="prose prose-sm prose-invert max-h-[60vh] max-w-none overflow-auto rounded-xl border p-3 text-xs leading-relaxed"
                      style={{ borderColor: "var(--color-line)", background: "var(--color-bg)" }}
                    >
                      <ReactMarkdown>{(selected.content || "加载中…").slice(0, 5000)}</ReactMarkdown>
                    </div>
                  ) : (
                    <pre className="max-h-[60vh] overflow-auto rounded-lg p-3 text-[11px] leading-relaxed" style={{ background: "#0d0f13", color: "#c3ccd8", whiteSpace: "pre-wrap" }}>
                      {(selected.content || "加载中…").slice(0, 5000)}
                    </pre>
                  )
                )}
              </div>
            )}
          </section>
        )}

        {tab === "quality" && role === "dev" && (
          <section className="space-y-3">
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
                    const r = await comparePrd(run.idea);
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
    <div className="flex h-dvh items-center justify-center px-4" style={{ background: "var(--color-bg)" }}>
      <div className="w-full max-w-sm rounded-2xl border p-6" style={{ borderColor: "var(--color-line)", background: "var(--color-surface)" }}>
        <div className="text-3xl">🏭</div>
        <div className="mt-2 text-lg font-semibold">登录 Agent造物坊</div>
        <div className="mt-1 text-sm" style={{ color: "var(--color-muted)" }}>手机号验证码登录（本地模式验证码会直接显示）</div>
        <div className="mt-4 flex gap-2">
          <input
            ref={phoneRef}
            className="flex-1 rounded-full border px-4 py-2.5 text-sm outline-none"
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
          <button className="rounded-full px-4 py-2.5 text-sm text-[#0a0b0e]" style={{ background: "var(--gradient-brand)" }} onClick={handleRequestCode} disabled={busy}>
            获取验证码
          </button>
        </div>
        {sent && (
          <div className="mt-3 flex gap-2">
            <input
              ref={codeRef}
              className="flex-1 rounded-full border px-4 py-2.5 text-sm outline-none"
              style={inputStyle}
              placeholder="验证码"
              name="code"
              autoComplete="one-time-code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              onInput={(e) => setCode((e.target as HTMLInputElement).value)}
              onKeyDown={(e) => e.key === "Enter" && handleLogin()}
            />
            <button className="rounded-full px-4 py-2.5 text-sm text-[#0a0b0e]" style={{ background: "var(--gradient-brand)" }} onClick={handleLogin} disabled={busy}>
              登录
            </button>
          </div>
        )}
        {err && <div className="mt-3 text-xs" style={{ color: "var(--color-danger)" }}>⚠️ {err}</div>}
      </div>
    </div>
  );
}

export default function Page() {
  const { run, submit, answer, confirm, restore, cancel, retry, retest, isTerminal, failure, reset } = useFactoryRun();
  const [idea, setIdea] = useState("");
  const [llmProvider, setLlmProvider] = useState<string>("");
  const [llmProfiles, setLlmProfiles] = useState<LlmProfile[]>([]);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [runList, setRunList] = useState<RunSummary[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [role, setRole] = useState<ViewRole>("pm");
  const [execConfirmOpen, setExecConfirmOpen] = useState(false);
  const [execAlways, setExecAlways] = useState(false);
  const [execBusy, setExecBusy] = useState(false);

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
  const [leftWidth, setLeftWidth] = useState(220);
  const [rightWidth, setRightWidth] = useState(320);
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
        const min = side === "left" ? 180 : 260;
        const max = side === "left" ? 300 : 440;
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

  const messages = useMemo(() => deriveMessages(run, role), [run, role]);

  const loadAll = () => {
    getMetrics().then(setMetrics).catch(() => {});
    getRunList().then((d) => setRunList(d.runs)).catch(() => {});
    listProjects().then((d) => setProjects(d.projects)).catch(() => {});
    listSchedules().then(setSchedules).catch(() => {});
  };

  async function handleCreateSchedule(idea: string, triggerTime: string) {
    await createSchedule({ idea, trigger_time: triggerTime });
    listSchedules().then(setSchedules).catch(() => {});
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

  // 定时无人值守：每 30s 刷新任务列表与定时任务，自动生成的新 Run 自动出现
  useEffect(() => {
    if (authPhase !== "authed") return;
    const timer = setInterval(() => {
      getRunList().then((d) => setRunList(d.runs)).catch(() => {});
      listSchedules().then(setSchedules).catch(() => {});
    }, 30000);
    return () => clearInterval(timer);
  }, [authPhase]);

  async function handleSend() {
    const text = idea.trim();
    if (!text) return;
    setIdea("");
    await submit(text, llmProvider ? { llm_provider: llmProvider } : undefined);
    loadAll();
  }

  async function handleAnswer(code: string, value: string) {
    await answer(code, value);
  }

  async function handleConfirm() {
    await confirm();
  }

  async function handleAccept(checklist: { id: string; label: string; passed: boolean }[]) {
    if (!run) return;
    try {
      await acceptRun(run.id, checklist);
      await restore(run.id);
      loadAll();
    } catch (e) {
      alert((e as Error).message);
    }
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
    await restore(id);
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
    clearToken();
    reset();
    setPhone(null);
    setAuthPhase("guest");
    setRunList([]);
    setMetrics(null);
  }

  if (authPhase === "checking") {
    return <div className="flex h-dvh items-center justify-center text-sm" style={{ color: "var(--color-muted)" }}>加载中…</div>;
  }
  if (!phone) {
    return <LoginScreen onLoggedIn={handleLoggedIn} />;
  }

  return (
    <div className="flex h-dvh">
      {/* 左栏 */}
      <aside className="hidden shrink-0 border-r md:block" style={{ width: leftWidth, borderColor: "var(--color-line)", background: "var(--color-surface)" }}>
        <TaskList runs={runList} currentId={run?.id ?? null} onSelect={handleSelect} role={role} onRoleChange={handleRoleChange} projectCount={projects.length} schedules={schedules} onCreateSchedule={handleCreateSchedule} onToggleSchedule={handleToggleSchedule} onDeleteSchedule={handleDeleteSchedule} />
        {phone && (
          <div className="border-t p-3 text-sm" style={{ borderColor: "var(--color-line)" }}>
            <div className="flex items-center justify-between gap-2">
              <span className="min-w-0 truncate" style={{ color: "var(--color-muted)" }}>{phone}</span>
              <button className="shrink-0 text-xs transition hover:underline" style={{ color: "var(--color-muted)" }} onClick={handleLogout}>退出</button>
            </div>
          </div>
        )}
      </aside>

      {/* 左分隔条（拖动调宽） */}
      <div className="hidden w-1 shrink-0 cursor-col-resize transition hover:bg-black/5 md:block" style={{ background: "var(--color-line)" }} onMouseDown={startDrag("left")} />

      {/* 中栏：会话 + 内嵌编排 */}
      <main className="flex min-w-0 flex-1 flex-col" style={{ background: "var(--color-bg)" }}>
        <div className="flex h-12 shrink-0 items-center gap-2 border-b px-4 text-sm font-semibold" style={{ borderColor: "var(--color-line)", background: "var(--color-surface)" }}>
          <span className="min-w-0 flex-1 truncate">{run ? run.idea : "新想法"}</span>
          {run && !isTerminal && (
            <button className="rounded-full border px-3 py-1 text-xs font-normal transition hover:bg-black/5" style={{ borderColor: "var(--color-line)", color: "var(--color-muted)" }} onClick={() => cancel()}>
              取消
            </button>
          )}
        </div>
        <SessionRail run={run} role={role} onConfirm={handleConfirm} onAccept={handleAccept} />
        {(failure || (run && (run.current_stage === "failed" || run.current_stage === "gate_failed" || run.current_stage === "cancelled"))) && (
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
                  <div>⚠️ {pmFailureText(run?.failure_code).message}</div>
                  <div className="mt-0.5 opacity-80">{pmFailureText(run?.failure_code).suggestion}</div>
                </>
              )}
            </div>
            {run && canFullRetry(run.current_stage) && (
              <div className="flex shrink-0 items-center gap-2">
                {canRetestInPlace(run.current_stage) && (
                  <button
                    className="rounded-full px-3 py-1 text-xs font-medium text-white transition"
                    style={{ background: "#ef4444" }}
                    onClick={() => retest().catch(() => {})}
                  >
                    仅重测
                  </button>
                )}
                <button
                  className="rounded-full border px-3 py-1 text-xs transition hover:bg-black/5"
                  style={{ borderColor: "var(--danger)", color: "var(--danger)" }}
                  onClick={() => retry().catch(() => {})}
                >
                  整段重跑
                </button>
              </div>
            )}
          </div>
        )}
        <div className="flex-1 space-y-3 overflow-auto px-4 py-4">
          {messages.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center text-center">
              <div className="text-4xl">🏭</div>
              <div className="mt-3 text-lg font-semibold">开始造一个产品吧</div>
              <div className="mt-1 text-sm" style={{ color: "var(--color-muted)" }}>在下方输入你的想法，工厂会把它做成可上线的 AI 产品</div>
            </div>
          ) : (
            messages.map((m, i) => <Bubble key={i} msg={m} stage={run?.current_stage ?? null} onAnswer={handleAnswer} onAccept={handleAccept} onPreview={handlePreview} />)
          )}
        </div>
        <div className="shrink-0 px-4 pb-4">
          <div className="flex items-center gap-2 rounded-full border p-1.5" style={{ borderColor: "var(--color-line)", background: "var(--color-surface)", boxShadow: "var(--shadow-md)" }}>
            <select
              className="shrink-0 rounded-full border px-3 py-2 text-xs outline-none"
              style={{ borderColor: "var(--color-line)", background: "var(--color-bg)" }}
              value={llmProvider}
              onChange={(e) => setLlmProvider(e.target.value)}
              aria-label="选择本轮模型"
              title="选择本轮模型"
            >
              <option value="">跟随全局默认</option>
              {llmProfiles.map((p) => (
                <option key={p.id} value={p.id} disabled={!p.available}>
                  {p.label}{p.available ? "" : "（未配置 Key）"}
                </option>
              ))}
            </select>
            <input
              className="min-w-0 flex-1 bg-transparent px-3 py-2.5 text-sm outline-none"
              placeholder="给造物坊 AI 发消息，描述你的产品想法…"
              value={idea}
              onChange={(e) => setIdea(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSend()}
            />
            <button className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-[#0a0b0e] transition hover:opacity-90" style={{ background: "var(--gradient-brand)" }} onClick={handleSend}>
              <Send size={18} />
            </button>
          </div>
        </div>
      </main>

      {/* 右分隔条 */}
      <div className="hidden w-1 shrink-0 cursor-col-resize transition hover:bg-black/5 lg:block" style={{ background: "var(--color-line)" }} onMouseDown={startDrag("right")} />

      {/* 右栏：预览 */}
      <aside className="hidden shrink-0 border-l lg:block" style={{ width: rightWidth, borderColor: "var(--color-line)", background: "var(--color-surface)" }}>
        <PreviewPanel
          run={run}
          metrics={metrics}
          role={role}
          onPreview={handlePreview}
          onRunRefresh={async () => { if (run) await restore(run.id); }}
        />
      </aside>

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
