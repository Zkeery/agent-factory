"use client";

import { useEffect, useRef, useState } from "react";
import { AlertCircle, ArrowRight, CheckCircle2, ChevronDown, Clock3, GitBranch, ListChecks, Loader2, Play, RefreshCw, Wrench } from "lucide-react";
import { agentRoleLabel, executionModeLabel, formatInsightDuration, getRunExecution, resumeExecution, type RunExecution } from "@/lib/agentInsights";
import { formatApiTime } from "@/lib/dateTime";

interface ExecutionPanelProps {
  runId: string;
  currentStage: string;
  executionMode?: string;
  onResume?: () => Promise<void>;
}

const statusLabels: Record<string, string> = {
  pending: "等待执行", queued: "等待执行", running: "执行中", interrupted: "已中断",
  completed: "已完成", failed: "失败", cancelled: "已取消",
};
const stoppedStages = new Set(["awaiting_answers", "awaiting_prd_confirm", "awaiting_acceptance", "delivered", "gate_failed", "failed", "cancelled"]);

function StatusBadge({ status }: { status: string }) {
  const tone = status === "completed" ? "bg-ok-soft text-ok"
    : status === "failed" ? "bg-danger-soft text-danger"
      : status === "running" ? "bg-brand-soft text-brand"
        : status === "interrupted" ? "bg-warn-soft text-warn" : "bg-surface-2 text-muted";
  return <span className={`inline-flex shrink-0 items-center gap-1.5 rounded-md px-2 py-1 text-[11px] font-medium ${tone}`}>
    {status === "running" && <Loader2 size={11} className="animate-spin" aria-hidden="true" />}
    {statusLabels[status] || status}
  </span>;
}

function timeLabel(value: string | null): string {
  if (!value) return "时间未记录";
  const text = formatApiTime(value);
  return text === "—" ? "时间未记录" : text;
}

function roundLabel(round: number): string { return round === 0 ? "初始轮" : `修复第 ${round} 轮`; }

/** A new key discards the previous Run's requests, errors and resume state. */
export function ExecutionPanel(props: ExecutionPanelProps) {
  return <ExecutionPanelForRun key={props.runId} {...props} />;
}

function ExecutionPanelForRun({ runId, currentStage, executionMode, onResume }: ExecutionPanelProps) {
  const [data, setData] = useState<RunExecution | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [resuming, setResuming] = useState(false);
  const [reload, setReload] = useState(0);
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const mounted = useRef(false);
  const resumePending = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();
    async function refresh() {
      let keepPolling = !stoppedStages.has(currentStage);
      try {
        const next = await getRunExecution(runId, controller.signal);
        if (cancelled) return;
        if (next.run_id !== runId) throw new Error("执行记录与当前版本不匹配，请刷新重试。");
        setData(next);
        setError(null);
        setUpdatedAt(new Date().toISOString());
        keepPolling = next.execution_mode === "agent_team" && ["pending", "running"].includes(next.status) && !stoppedStages.has(currentStage);
      } catch (err) {
        if (cancelled || controller.signal.aborted) return;
        setError(err instanceof Error ? err.message : "执行记录读取失败，请重试。");
      } finally {
        if (!cancelled) setLoading(false);
      }
      if (!cancelled && keepPolling) timer = setTimeout(() => { void refresh(); }, 4000);
    }
    void refresh();
    return () => { cancelled = true; controller.abort(); if (timer) clearTimeout(timer); };
  }, [runId, currentStage, reload]);

  const refreshNow = () => { setLoading(true); setReload((value) => value + 1); };
  const workflow = (data?.execution_mode || executionMode) === "workflow";
  const resume = async () => {
    if (resumePending.current || !data?.resumable) return;
    resumePending.current = true;
    setResuming(true);
    setError(null);
    try {
      if (onResume) await onResume();
      else await resumeExecution(runId);
      if (mounted.current) refreshNow();
    } catch (err) {
      if (mounted.current) setError(err instanceof Error ? err.message : "恢复失败，请重试。");
    } finally {
      resumePending.current = false;
      if (mounted.current) setResuming(false);
    }
  };

  return <section className="wf-card execution-panel" aria-label="协作执行记录">
    <div className="wf-card-header">
      <div className="flex min-w-0 items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-brand"><GitBranch size={18} strokeWidth={1.8} aria-hidden="true" /></span>
        <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><h3 className="text-sm font-semibold">{workflow ? "固定流程执行" : "协作执行"}</h3><span className="status-badge">{executionModeLabel(data?.execution_mode || executionMode)}</span>{data && !workflow && <StatusBadge status={data.status} />}</div><p className="mt-1 text-xs leading-relaxed text-muted">{workflow ? "查看当前版本的执行方式。" : "开发与验证分工执行，检查结果决定是否进入修复。"}</p></div>
      </div>
      <button type="button" className="shrink-0 rounded-md p-1.5 text-muted transition hover:bg-surface-2 disabled:opacity-40" aria-label="刷新执行记录" disabled={loading || resuming} onClick={refreshNow}><RefreshCw size={15} className={loading ? "animate-spin" : ""} /></button>
    </div>
    <div className="wf-card-body space-y-4">
      {error && <div role="alert" className="flex items-start gap-2 rounded-lg border border-danger/25 bg-danger-soft p-3 text-xs leading-relaxed text-danger"><AlertCircle size={15} className="mt-0.5 shrink-0" aria-hidden="true" />{error}</div>}
      {!data && loading && <div role="status" className="flex items-center gap-2 py-3 text-xs text-muted"><Loader2 size={15} className="animate-spin" aria-hidden="true" />正在读取执行记录…</div>}
      {workflow ? <div className="rounded-lg border border-line bg-surface-2 p-4 text-xs leading-6 text-muted">当前版本使用固定流程。没有独立 Agent 的任务与交接记录，不计作多 Agent 协作。</div> : data && <>
        <div className="grid gap-3 rounded-lg border border-line bg-surface-2 p-4 sm:grid-cols-3">
          <div><p className="text-[11px] text-muted">当前执行者</p><p className="mt-1.5 text-xs font-semibold">{agentRoleLabel(data.active_role)}</p></div>
          <div><p className="text-[11px] text-muted">修复轮次</p><p className="mt-1.5 text-xs font-semibold tabular-nums">{data.repair_rounds} / {data.limits.max_repair_rounds}<span className="ml-1 font-normal text-muted">轮</span></p></div>
          <div><p className="text-[11px] text-muted">每位 Agent 单轮调用上限</p><p className="mt-1.5 text-xs font-semibold tabular-nums">{data.limits.max_turns_per_agent}<span className="ml-1 font-normal text-muted">次</span></p></div>
        </div>
        {data.stop_reason && <div className={`rounded-lg border p-3 text-xs leading-relaxed ${data.status === "completed" ? "border-ok/25 bg-ok-soft text-ok" : "border-warn/25 bg-warn-soft text-warn"}`}><span className="font-medium">{data.status === "completed" ? "执行结果：" : "停止原因："}</span>{data.stop_reason}</div>}
        {data.resumable && <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-brand/25 bg-brand-soft p-3"><p className="text-xs leading-relaxed text-brand">可从已保存的执行记录继续。</p><button type="button" className="button-primary" disabled={resuming || loading} onClick={() => { void resume(); }}>{resuming ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : <Play size={14} aria-hidden="true" />}{resuming ? "正在恢复…" : "继续协作执行"}</button></div>}
        <div>
          <h4 className="mb-3 flex items-center gap-2 text-xs font-semibold"><ListChecks size={15} className="text-muted" aria-hidden="true" />Agent 任务<span className="font-normal text-muted">{data.tasks.length} 项</span></h4>
          {data.tasks.length === 0 ? <p className="rounded-lg border border-dashed border-line p-4 text-xs leading-relaxed text-muted">尚无 Agent 任务记录。执行开始后会显示实际分工与结果。</p> : <div className="space-y-2.5">{data.tasks.map((task) => <div key={task.id} className="rounded-lg border border-line p-3.5">
            <div className="flex items-start justify-between gap-2"><div className="min-w-0"><div className="flex flex-wrap items-center gap-2 text-xs font-medium"><span>{agentRoleLabel(task.role)}</span><span className="rounded bg-surface-2 px-1.5 py-0.5 text-[10px] font-normal text-muted">{roundLabel(task.round)}</span></div><p className="mt-1.5 break-words text-xs leading-relaxed">{task.title}</p></div><StatusBadge status={task.status} /></div>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-muted"><Clock3 size={11} aria-hidden="true" /><span>{timeLabel(task.started_at)}{task.finished_at ? ` → ${timeLabel(task.finished_at)}` : ""}</span></div>
            {(task.input_summary || task.output_summary) && <details className="group mt-3 border-t border-line pt-2.5"><summary className="flex cursor-pointer list-none items-center justify-between text-[11px] text-muted [&::-webkit-details-marker]:hidden">输入与执行结果<ChevronDown size={13} className="transition-transform group-open:rotate-180" aria-hidden="true" /></summary><dl className="mt-3 space-y-3 text-xs leading-relaxed">{task.input_summary && <div><dt className="mb-1 text-[10px] text-muted">输入</dt><dd className="whitespace-pre-wrap break-words">{task.input_summary}</dd></div>}{task.output_summary && <div><dt className="mb-1 text-[10px] text-muted">结果</dt><dd className="whitespace-pre-wrap break-words">{task.output_summary}</dd></div>}</dl></details>}
          </div>)}</div>}
        </div>
        {(data.handoffs.length > 0 || data.checks.length > 0) && <div className="grid gap-4 xl:grid-cols-2">
          <div><h4 className="mb-3 text-xs font-semibold">Agent 交接</h4>{data.handoffs.length ? <ol className="space-y-2.5">{data.handoffs.map((handoff) => <li key={handoff.id} className="rounded-lg border border-line bg-surface-2 p-3"><div className="flex flex-wrap items-center gap-1.5 text-[11px] font-medium">{agentRoleLabel(handoff.from_role)}<ArrowRight size={12} className="text-muted" aria-hidden="true" />{agentRoleLabel(handoff.to_role)}</div><p className="mt-2 whitespace-pre-wrap break-words text-xs leading-relaxed text-muted">{handoff.reason}</p><p className="mt-2 text-[10px] text-muted">{roundLabel(handoff.round)} · {timeLabel(handoff.created_at)}</p></li>)}</ol> : <p className="text-xs text-muted">暂无交接记录</p>}</div>
          <div><h4 className="mb-3 text-xs font-semibold">检查与修复依据</h4>{data.checks.length ? <ol className="space-y-2.5">{data.checks.map((check) => <li key={check.id} className={`rounded-lg border p-3 ${check.passed ? "border-ok/25 bg-ok-soft" : "border-[#f3d0c9] bg-[#fff8f7]"}`}><div className={`flex items-center gap-1.5 text-[11px] font-medium ${check.passed ? "text-ok" : "text-danger"}`}>{check.passed ? <CheckCircle2 size={13} aria-hidden="true" /> : <AlertCircle size={13} aria-hidden="true" />}{check.passed ? "自动检查通过" : "自动检查未通过"}<span className="ml-auto text-[10px] font-normal text-muted">{roundLabel(check.round)}</span></div><p className="mt-2 whitespace-pre-wrap break-words text-xs leading-relaxed">{check.summary}</p><p className="mt-2 text-[10px] text-muted">{timeLabel(check.created_at)}</p></li>)}</ol> : <p className="text-xs text-muted">暂无检查记录</p>}</div>
        </div>}
        <details className="group rounded-lg border border-line">
          <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-xs font-medium [&::-webkit-details-marker]:hidden"><Wrench size={14} className="text-muted" aria-hidden="true" />工具执行明细<span className="font-normal text-muted">{data.steps.length} 条</span><ChevronDown size={14} className="ml-auto text-muted transition-transform group-open:rotate-180" aria-hidden="true" /></summary>
          <ol className="max-h-[480px] space-y-3 overflow-auto border-t border-line p-4">{data.steps.length === 0 && <li className="text-xs text-muted">尚无工具执行记录</li>}{[...data.steps].sort((a, b) => a.sequence - b.sequence).map((step) => <li key={step.id} className="border-b border-line pb-3 last:border-0 last:pb-0"><div className="flex flex-wrap items-center gap-2 text-xs"><span className="font-medium">{agentRoleLabel(step.role)}</span><code className="rounded bg-surface-2 px-1.5 py-0.5 text-[10px] text-muted">{step.tool}</code><StatusBadge status={step.status} /></div><p className="mt-2 whitespace-pre-wrap break-words text-xs leading-relaxed">{step.summary || "未记录执行摘要"}</p><div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-muted"><span>{roundLabel(step.round)} · {timeLabel(step.created_at)}</span><span>耗时 {step.duration_ms == null ? "—" : formatInsightDuration(step.duration_ms / 1000)}</span><span>Token 输入 {step.input_tokens ?? "—"} / 输出 {step.output_tokens ?? "—"}</span></div></li>)}</ol>
        </details>
        <p className="text-[11px] leading-relaxed text-muted">自动检查通过后，仍需用真实任务完成人工验收。</p>
      </>}
      {updatedAt && <p className="text-[10px] text-muted">记录更新于 {timeLabel(updatedAt)}{data?.status === "running" ? " · 执行中自动刷新" : ""}</p>}
    </div>
  </section>;
}
