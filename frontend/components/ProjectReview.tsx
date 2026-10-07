"use client";

import { useEffect, useState } from "react";
import { AlertCircle, ArrowLeft, ArrowUpRight, BarChart3, CheckCircle2, Clock3, Coins, Download, Filter, FlaskConical, GitBranch, Loader2, PackageCheck, RefreshCw } from "lucide-react";
import type { Project } from "@/lib/factory";
import {
  downloadProjectReview, executionModeLabel, formatInsightCost, formatInsightDuration,
  formatReviewMetric, getProjectReview, REVIEW_METRICS, reviewSourceLabel,
  type ProjectReviewData, type ReviewDays, type ReviewFilters, type ReviewMetricKey, type ReviewSource,
} from "@/lib/agentInsights";

interface ProjectReviewProps {
  projects: Project[];
  onSelectRun: (id: string) => void;
  onBack: () => void;
}

const metricIcons = { delivery_rate: PackageCheck, automatic_check_rate: CheckCircle2, delivery_seconds: Clock3, execution_seconds: Clock3, estimated_cost: Coins, iteration_fix_rate: GitBranch };
const stageNames: Record<string, string> = {
  idea_submitted: "已提交", clarifying: "澄清需求", awaiting_answers: "待回答", prd_drafting: "起草需求",
  awaiting_prd_confirm: "待确认需求", building: "构建中", testing: "检查中", deploying: "准备运行",
  evidence_ready: "材料已就绪", gate_passed: "自动检查通过", awaiting_acceptance: "待人工验收",
  delivered: "已交付", gate_failed: "检查未通过", failed: "失败", cancelled: "已取消",
};

function dateLabel(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function SourceBadge({ source }: { source: string }) {
  return <span className={`inline-flex rounded-md px-1.5 py-0.5 text-[10px] font-medium ${source === "real" ? "bg-brand-soft text-brand" : source === "mock" ? "bg-warn-soft text-warn" : "bg-surface-2 text-muted"}`}>{reviewSourceLabel(source)}</span>;
}

function MetricCard({ metricKey, data }: { metricKey: ReviewMetricKey; data: ProjectReviewData }) {
  const entry = REVIEW_METRICS.find((item) => item.key === metricKey)!;
  const metric = data.metrics[metricKey];
  const Icon = metricIcons[metricKey];
  const hasValue = metric.value != null && metric.samples > 0;
  return <section className="wf-card review-metric flex flex-col p-5">
    <div className="flex items-center justify-between gap-2"><h3 className="text-xs font-medium text-muted">{entry.label}</h3><Icon size={16} className="shrink-0 text-muted" strokeWidth={1.8} aria-hidden="true" /></div>
    <div className={`my-3 font-semibold tabular-nums tracking-tight ${hasValue ? "text-[25px] leading-9 text-ink" : "text-xl leading-9 text-muted"}`}>{formatReviewMetric(metricKey, metric, data.currency)}</div>
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted">
      {metric.numerator != null && metric.denominator != null && <span className="font-medium text-ink">{metric.numerator} / {metric.denominator}</span>}
      <span>样本 {metric.samples}</span><span>未计入 {metric.excluded}</span>
    </div>
    <p className="mt-3 border-t border-line pt-3 text-[11px] leading-relaxed text-muted">{metric.definition}</p>
  </section>;
}

export function ProjectReview({ projects, onSelectRun, onBack }: ProjectReviewProps) {
  const [filters, setFilters] = useState<ReviewFilters>({ source: "real", days: "all", project_id: null });
  const [reload, setReload] = useState(0);
  const [refreshBusy, setRefreshBusy] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<{ key: string; data: ProjectReviewData | null; error: string | null } | null>(null);
  const { source, days, project_id: projectId } = filters;
  const filterKey = JSON.stringify([source, days, projectId || null]);
  const current = snapshot?.key === filterKey ? snapshot : null;
  const data = current?.data || null;
  const loading = !current || refreshBusy;

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const requestedKey = JSON.stringify([source, days, projectId || null]);
    void getProjectReview({ source, days, project_id: projectId }, controller.signal)
      .then((result) => {
        if (!cancelled) setSnapshot({ key: requestedKey, data: result, error: null });
      })
      .catch((err: unknown) => {
        if (cancelled || controller.signal.aborted) return;
        setSnapshot((previous) => ({ key: requestedKey, data: previous?.key === requestedKey ? previous.data : null, error: err instanceof Error ? err.message : "复盘数据读取失败，请重试。" }));
      })
      .finally(() => { if (!cancelled) setRefreshBusy(false); });
    return () => { cancelled = true; controller.abort(); };
  }, [source, days, projectId, reload]);

  const changeFilter = (patch: Partial<ReviewFilters>) => { setFilters((previous) => ({ ...previous, ...patch })); setExportError(null); };
  const refresh = () => { setRefreshBusy(true); setReload((value) => value + 1); };
  const exportCsv = () => {
    if (!data) return;
    setExportError(null);
    try { downloadProjectReview(data); }
    catch (err) { setExportError(err instanceof Error ? err.message : "导出失败，请重试。"); }
  };

  return <div className="mx-auto w-full max-w-[1320px] space-y-5 px-5 py-6 md:px-7 md:py-8">
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div><button type="button" className="mb-4 inline-flex items-center gap-1.5 text-xs text-muted hover:text-brand" onClick={onBack}><ArrowLeft size={14} aria-hidden="true" />返回工作台</button><div className="flex items-center gap-3"><span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-soft text-brand"><BarChart3 size={20} strokeWidth={1.8} aria-hidden="true" /></span><div><h1 className="text-xl font-semibold tracking-tight">项目复盘</h1><p className="mt-1 text-xs leading-relaxed text-muted">查看生成、交付与迭代记录，按真实样本复盘项目表现。</p></div></div></div>
      <div className="flex items-center gap-2 self-end"><button type="button" className="button-secondary" disabled={loading} onClick={refresh}><RefreshCw size={14} className={loading ? "animate-spin" : ""} aria-hidden="true" />刷新</button><button type="button" className="button-primary" disabled={!data || loading} onClick={exportCsv}><Download size={14} aria-hidden="true" />导出当前复盘 CSV</button></div>
    </div>

    <section className="wf-card p-4" aria-label="复盘筛选">
      <div className="grid gap-4 sm:grid-cols-3">
        <label className="space-y-1.5 text-xs font-medium"><span className="flex items-center gap-1.5"><Filter size={13} className="text-muted" aria-hidden="true" />数据来源</span><select className="input-field" aria-label="复盘数据来源" value={source} onChange={(event) => changeFilter({ source: event.target.value as ReviewSource })}><option value="real">真实模型</option><option value="mock">Mock 演示</option><option value="unknown">来源未知</option><option value="all">全部来源</option></select></label>
        <label className="space-y-1.5 text-xs font-medium"><span>时间范围</span><select className="input-field" aria-label="复盘时间范围" value={days} onChange={(event) => changeFilter({ days: event.target.value as ReviewDays })}><option value="all">全部时间</option><option value="7">最近 7 天</option><option value="30">最近 30 天</option><option value="90">最近 90 天</option></select></label>
        <label className="space-y-1.5 text-xs font-medium"><span>项目范围</span><select className="input-field" aria-label="复盘项目范围" value={projectId || ""} onChange={(event) => changeFilter({ project_id: event.target.value || null })}><option value="">全部项目</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
      </div>
      <p className="mt-3 text-[11px] leading-relaxed text-muted">{source === "real" ? "仅统计真实模型记录；模型执行成功仍需经过人工验收。" : source === "mock" ? "当前是 Mock 演示数据，用于核对流程，不代表真实模型质量。" : source === "unknown" ? "这些历史记录未能确认模型来源，单独列出。" : "当前包含真实模型、Mock 与来源未知记录，来源分布和明细单独标记。"}</p>
    </section>

    {(current?.error || exportError) && <div role="alert" className="flex items-start gap-2 rounded-lg border border-danger/25 bg-danger-soft p-3 text-xs leading-relaxed text-danger"><AlertCircle size={15} className="mt-0.5 shrink-0" aria-hidden="true" /><span>{exportError || current?.error}{current?.error && data ? " 当前仍显示上次成功读取的结果。" : ""}</span></div>}
    {!data && loading && <div role="status" className="flex items-center justify-center gap-2 py-16 text-sm text-muted"><Loader2 size={18} className="animate-spin" aria-hidden="true" />正在读取复盘数据…</div>}
    {data && <>
      <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-muted"><div className="flex flex-wrap gap-x-4 gap-y-1"><span className="font-medium text-ink">{data.counts.total} 条记录</span><span>已交付 {data.counts.delivered}</span><span>失败 {data.counts.failed}</span><span>取消 {data.counts.cancelled}</span><span>待完成 {data.counts.pending}</span></div><span>统计于 {dateLabel(data.generated_at)}</span></div>
      {data.counts.total === 0 && <div className="rounded-xl border border-dashed border-line bg-panel px-5 py-6 text-center"><FlaskConical size={22} className="mx-auto mb-2 text-muted" aria-hidden="true" /><p className="text-sm font-medium">当前筛选暂无记录</p><p className="mt-1 text-xs leading-relaxed text-muted">{source === "real" ? "完成真实模型任务后会积累样本，也可以切换 Mock 查看演示记录。" : "调整项目或时间范围后再查看。"}</p></div>}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{REVIEW_METRICS.map(({ key }) => <MetricCard key={key} metricKey={key} data={data} />)}</div>

      <section className="wf-card">
        <div className="wf-card-header"><div><h2 className="flex items-center gap-2 text-sm font-semibold"><GitBranch size={16} className="text-brand" aria-hidden="true" />迭代前后对照</h2><p className="mt-1 text-xs leading-relaxed text-muted">以父子版本的验证任务为依据，待验证和无法比较的记录单列。</p></div><span className="status-badge shrink-0">按当前筛选</span></div>
        <div className="wf-card-body"><div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">{[
          { label: "基线未通过", value: data.iteration.baseline_failed }, { label: "可比较", value: data.iteration.comparable },
          { label: "已修复", value: data.iteration.fixed, tone: "text-ok" }, { label: "待验证", value: data.iteration.pending },
          { label: "未计入", value: data.iteration.excluded }, { label: "新增未通过", value: data.iteration.new_failures, tone: data.iteration.new_failures ? "text-danger" : "text-ink" },
        ].map((item) => <div key={item.label} className="rounded-lg border border-line bg-surface-2 p-3"><p className="text-[11px] text-muted">{item.label}</p><p className={`mt-2 text-xl font-semibold tabular-nums ${item.tone || "text-ink"}`}>{item.value}</p></div>)}</div><p className="mt-3 text-[11px] leading-relaxed text-muted">{data.metrics.iteration_fix_rate.definition}</p></div>
      </section>

      <section className="wf-card">
        <div className="wf-card-header"><div><h2 className="text-sm font-semibold">可追溯的版本记录</h2><p className="mt-1 text-xs text-muted">点击版本回到工作台，查看需求、执行过程与验收记录。</p></div><div className="flex flex-wrap items-center gap-2 text-[10px] text-muted"><span>真实 {data.counts.real}</span><span>Mock {data.counts.mock}</span><span>未知 {data.counts.unknown}</span></div></div>
        <div className="overflow-x-auto"><table className="w-full min-w-[900px] text-left text-xs"><thead className="border-b border-line bg-surface-2 text-[11px] text-muted"><tr><th className="px-5 py-3 font-medium">项目 / 版本</th><th className="px-3 py-3 font-medium">来源与执行</th><th className="px-3 py-3 font-medium">当前状态</th><th className="px-3 py-3 font-medium">交付用时</th><th className="px-3 py-3 font-medium">执行用时</th><th className="px-3 py-3 font-medium">费用估算</th><th className="px-3 py-3 font-medium">创建时间</th></tr></thead><tbody>
          {data.rows.map((row) => <tr key={row.run_id} className="border-b border-line last:border-0 hover:bg-surface-2"><td className="max-w-[280px] px-5 py-3.5"><button type="button" className="group flex w-full items-start gap-2 text-left" onClick={() => onSelectRun(row.run_id)}><span className="min-w-0"><span className="line-clamp-2 break-words text-xs font-medium leading-relaxed group-hover:text-brand">{row.idea}</span><span className="mt-1 block text-[10px] text-muted">{projects.find((project) => project.id === row.project_id)?.name || "未关联项目"} · {row.parent_run_id ? "修改版" : "初版"}</span></span><ArrowUpRight size={13} className="mt-0.5 shrink-0 text-muted group-hover:text-brand" aria-hidden="true" /></button></td><td className="px-3 py-3.5"><SourceBadge source={row.source} /><p className="mt-1 text-[10px] text-muted">{executionModeLabel(row.execution_mode)}</p></td><td className="px-3 py-3.5"><span className={`inline-block rounded-md px-2 py-1 text-[10px] ${row.stage === "delivered" ? "bg-ok-soft text-ok" : ["failed", "gate_failed"].includes(row.stage) ? "bg-danger-soft text-danger" : "bg-surface-2 text-muted"}`}>{stageNames[row.stage] || row.stage}</span></td><td className="whitespace-nowrap px-3 py-3.5 tabular-nums">{formatInsightDuration(row.delivery_seconds)}</td><td className="whitespace-nowrap px-3 py-3.5 tabular-nums">{formatInsightDuration(row.execution_seconds)}</td><td className="whitespace-nowrap px-3 py-3.5 tabular-nums">{formatInsightCost(row.estimated_cost, data.currency)}</td><td className="whitespace-nowrap px-3 py-3.5 text-[11px] text-muted">{dateLabel(row.created_at)}</td></tr>)}
          {data.rows.length === 0 && <tr><td colSpan={7} className="px-5 py-8 text-center text-xs text-muted">没有符合当前筛选的版本记录</td></tr>}
        </tbody></table></div>
      </section>

      <div className="rounded-lg border border-line bg-surface-2 p-4 text-[11px] leading-relaxed text-muted"><p className="font-medium text-ink">统计与费用说明</p><p className="mt-2">费用为 {data.currency} 估算值，不是服务商账单。{data.pricing_basis}</p><p className="mt-1">“—”代表没有可用记录，未按 0 计算。比例按各卡片的分子、分母与样本口径解释。</p>{data.notes.length > 0 && <ul className="mt-2 list-disc space-y-1 pl-4">{data.notes.map((note, index) => <li key={index}>{note}</li>)}</ul>}</div>
    </>}
  </div>;
}
