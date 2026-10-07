"use client";

import { useRef, useState } from "react";
import {
  AlertCircle, ArrowRight, Check, CheckCircle2, ChevronDown, ClipboardCheck,
  Code2, Download, FileText, FolderArchive, GitBranch, ListChecks, Loader2,
  MessageSquareText, Plus, RotateCcw, Save, ShieldCheck, Trash2, type LucideIcon,
} from "lucide-react";
import {
  acceptanceResultError,
  acceptanceScenarioError,
  DEFAULT_ACCEPTANCE_CHECKLIST,
  downloadRunBundle,
  type AcceptanceChecklistItem,
  type AcceptanceScenario,
  type AcceptanceScenarioResult,
  type Run,
} from "@/lib/factory";
import {
  acceptanceDraftSaveError,
  createAcceptanceDrafts,
  toAcceptanceResults,
  type AcceptanceDraft,
} from "@/lib/acceptanceDraft";

const fieldClass = "input-field w-full rounded-lg border px-3 py-2.5 text-[13px] leading-relaxed outline-none transition-shadow placeholder:text-muted focus:border-brand focus:ring-2 focus:ring-brand/10 disabled:cursor-not-allowed disabled:opacity-50";
const fieldStyle = { borderColor: "var(--color-line, #e7eaf0)", background: "var(--paper)", color: "var(--ink, #182230)" };
const buttonClass = "button-primary inline-flex min-h-9 items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40";
const buttonStyle = { background: "var(--color-primary, #2563eb)", color: "var(--ink-on-brand)" };
const secondaryClass = "button-secondary inline-flex min-h-9 items-center justify-center gap-2 rounded-lg border bg-panel px-3.5 py-2 text-xs font-medium transition-colors hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-40";
const secondaryStyle = { borderColor: "var(--color-line, #e7eaf0)", color: "var(--ink, #182230)" };
const cardClass = "wf-card overflow-hidden rounded-xl border";
const cardStyle = { borderColor: "var(--color-line, #e7eaf0)", background: "var(--color-surface, #fff)", color: "var(--ink, #182230)" };
const mutedStyle = { color: "var(--color-muted, #737f91)" };
const lineStyle = { borderColor: "var(--color-line, #e7eaf0)" };
const labelClass = "block space-y-1.5 text-xs font-medium";
const checkboxClass = "h-4 w-4 shrink-0 cursor-pointer rounded border-line accent-brand disabled:cursor-not-allowed";

function PanelHeader({ icon: Icon, title, description, badge }: { icon: LucideIcon; title: string; description: string; badge?: string }) {
  return (
    <div className="wf-card-header flex items-start gap-3 border-b px-5 py-4" style={lineStyle}>
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-brand"><Icon size={18} strokeWidth={1.8} aria-hidden="true" /></span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-semibold tracking-[-0.01em]">{title}</h3>
          {badge && <span className="rounded-md bg-surface-2 px-2 py-0.5 text-[10px] font-medium text-muted">{badge}</span>}
        </div>
        <p className="mt-1 text-xs leading-relaxed" style={mutedStyle}>{description}</p>
      </div>
    </div>
  );
}

function ButtonIcon({ busy, icon: Icon }: { busy: boolean; icon: LucideIcon }) {
  return busy ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : <Icon size={14} aria-hidden="true" />;
}

function SavedMessage({ children }: { children: string }) {
  return <p role="status" className="flex items-start gap-2 rounded-lg bg-ok-soft px-3 py-2.5 text-xs leading-relaxed text-ok"><CheckCircle2 size={15} className="mt-0.5 shrink-0" aria-hidden="true" />{children}</p>;
}

function ResultBadge({ passed, recorded }: { passed: boolean; recorded: boolean }) {
  return <span className={`inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-[10px] font-medium ${!recorded ? "bg-surface-2 text-muted" : passed ? "bg-ok-soft text-ok" : "bg-danger-soft text-danger"}`}>
    {recorded && (passed ? <Check size={11} aria-hidden="true" /> : <AlertCircle size={11} aria-hidden="true" />)}
    {!recorded ? "未验证" : passed ? "已通过" : "未通过"}
  </span>;
}

function ErrorMessage({ message }: { message: string | null }) {
  return message ? <p role="alert" className="flex items-start gap-2 rounded-lg border border-danger/25 bg-danger-soft px-3 py-2.5 text-xs leading-relaxed text-danger"><AlertCircle size={15} className="mt-0.5 shrink-0" aria-hidden="true" />{message}</p> : null;
}

export function RequirementsForm({ busy, onSubmit }: { busy: boolean; onSubmit: (feedback: string) => Promise<void> }) {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  return (
    <form className={cardClass} style={cardStyle} onSubmit={async (event) => {
      event.preventDefault();
      if (busy || !text.trim()) return;
      setError(null);
      setSaved(false);
      try {
        await onSubmit(text.trim());
        setText("");
        setSaved(true);
      } catch (err) {
        setError(err instanceof Error ? err.message : "补充需求未保存，请重试。");
      }
    }}>
      <PanelHeader icon={MessageSquareText} title="需求纠错" badge="生成前可调整" description="补充遗漏、纠正理解，让需求与实际使用场景保持一致。" />
      <div className="wf-card-body space-y-4 p-5">
        <label className={labelClass}>
          <span>补充内容</span>
          <textarea className={fieldClass} style={fieldStyle} rows={3} maxLength={4000} value={text} disabled={busy}
            placeholder="例如：用户可以重复使用已有模板；不要自动删除原始内容。"
            onChange={(event) => { setText(event.target.value); setSaved(false); }} />
        </label>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-[11px] leading-relaxed" style={mutedStyle}>更新后，请重新检查需求和验收场景。</p>
          <span className="text-[10px] tabular-nums" style={mutedStyle}>{text.length} / 4000</span>
        </div>
        <ErrorMessage message={error} />
        {saved && <SavedMessage>需求已补充。请查看最新 PRD，再确认下一步。</SavedMessage>}
      </div>
      <div className="flex justify-end border-t bg-surface-2 px-5 py-3" style={lineStyle}>
        <button className={buttonClass} style={buttonStyle} disabled={busy || !text.trim()} type="submit"><ButtonIcon busy={busy} icon={ArrowRight} />{busy ? "处理中…" : "补充并更新需求"}</button>
      </div>
    </form>
  );
}

export function RevisionForm({ busy, initialText = "", onSubmit }: { busy: boolean; initialText?: string; onSubmit: (changeRequest: string, requestId: string) => Promise<void> }) {
  const [text, setText] = useState(initialText);
  const [error, setError] = useState<string | null>(null);
  const submission = useRef<{ text: string; requestId: string } | null>(null);

  return (
    <form id="revision-form" className={cardClass} style={cardStyle} onSubmit={async (event) => {
      event.preventDefault();
      const change = text.trim();
      if (busy || !change) return;
      if (submission.current?.text !== change) submission.current = { text: change, requestId: crypto.randomUUID() };
      setError(null);
      try {
        await onSubmit(change, submission.current.requestId);
        setText("");
        submission.current = null;
      } catch (err) {
        setError(err instanceof Error ? err.message : "新版本未创建，请重试。");
      }
    }}>
      <PanelHeader icon={GitBranch} title={initialText ? "修复未通过的问题" : "继续修改这个成品"} badge="保留当前版本" description="把修改要求带入新版本，继续完善已有需求和代码。" />
      <div className="wf-card-body space-y-4 p-5">
        {initialText && <div className="flex items-start gap-2 rounded-lg border border-brand/25 bg-brand-soft px-3 py-2.5 text-xs leading-relaxed text-brand"><ClipboardCheck size={15} className="mt-0.5 shrink-0" aria-hidden="true" />已带入试用反馈。确认或调整下面的修改要求，再创建新版本。</div>}
        <label className={labelClass}>
          <span>这次想改什么</span>
          <textarea className={fieldClass} style={fieldStyle} rows={initialText ? 6 : 3} maxLength={4000} value={text} disabled={busy} autoFocus={!!initialText}
            placeholder="例如：保留现有功能，增加一键复制结果；空输入时给出清楚提示。"
            onChange={(event) => setText(event.target.value)} />
        </label>
        <ErrorMessage message={error} />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t bg-surface-2 px-5 py-3" style={lineStyle}>
        <p className="text-[11px]" style={mutedStyle}>新版本将重新确认需求、运行和验收。</p>
        <button className={buttonClass} style={buttonStyle} disabled={busy || !text.trim()} type="submit"><ButtonIcon busy={busy} icon={GitBranch} />{busy ? "创建中…" : initialText ? "生成修复版" : "基于此版继续修改"}</button>
      </div>
    </form>
  );
}

export function AcceptanceScenariosEditor({ scenarios, dirty, busy, onChange, onSave }: {
  scenarios: AcceptanceScenario[];
  dirty: boolean;
  busy: boolean;
  onChange: (scenarios: AcceptanceScenario[]) => void;
  onSave: () => Promise<void>;
}) {
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const validation = acceptanceScenarioError(scenarios);
  const update = (index: number, field: "title" | "input" | "expected_output", value: string) => {
    setSaved(false);
    onChange(scenarios.map((item, i) => i === index ? { ...item, [field]: value } : item));
  };

  return (
    <form className={cardClass} style={cardStyle} onSubmit={async (event) => {
      event.preventDefault();
      if (busy || validation) return;
      setError(null);
      try {
        await onSave();
        setSaved(true);
      } catch (err) {
        setError(err instanceof Error ? err.message : "验收场景未保存，请重试。");
      }
    }}>
      <PanelHeader icon={ListChecks} title="约定验证任务" badge={`${scenarios.length} 个场景`} description="至少 3 个具体场景，明确输入与预期结果。成品完成后，按这些任务逐项验证。" />
      <div className="wf-card-body space-y-4 p-5">
        <div className="space-y-4">
          {scenarios.map((item, index) => (
            <fieldset key={item.id} className="overflow-hidden rounded-lg border bg-surface-2" style={lineStyle} disabled={busy}>
              <legend className="sr-only">场景 {index + 1}</legend>
              <div className="flex items-center justify-between border-b px-3.5 py-2.5" style={lineStyle}>
                <div className="flex items-center gap-2 text-xs font-medium"><span className="inline-flex h-5 w-5 items-center justify-center rounded bg-surface-2 text-[10px] tabular-nums text-muted">{String(index + 1).padStart(2, "0")}</span>验证任务</div>
                {scenarios.length > 3 && <button type="button" className="inline-flex items-center gap-1 rounded px-1.5 py-1 text-[11px] text-muted hover:bg-danger-soft hover:text-danger" onClick={() => { setSaved(false); onChange(scenarios.filter((_, i) => i !== index)); }}><Trash2 size={12} aria-hidden="true" />移除场景 {index + 1}</button>}
              </div>
              <div className="space-y-3 p-3.5">
                <label className={labelClass}>
                  <span>场景 {index + 1} 名称</span>
                  <input className={fieldClass} style={fieldStyle} value={item.title} maxLength={200} onChange={(event) => update(index, "title", event.target.value)} />
                </label>
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className={labelClass}>
                    <span>场景 {index + 1} 输入</span>
                    <textarea className={fieldClass} style={fieldStyle} rows={3} value={item.input} maxLength={2000} onChange={(event) => update(index, "input", event.target.value)} />
                  </label>
                  <label className={labelClass}>
                    <span>场景 {index + 1} 预期结果</span>
                    <textarea className={fieldClass} style={fieldStyle} rows={3} value={item.expected_output} maxLength={2000} onChange={(event) => update(index, "expected_output", event.target.value)} />
                  </label>
                </div>
              </div>
            </fieldset>
          ))}
        </div>
        <button type="button" className={`${secondaryClass} w-full border-dashed`} style={secondaryStyle} disabled={busy || scenarios.length >= 10}
          onClick={() => { setSaved(false); onChange([...scenarios, { id: crypto.randomUUID(), title: "", input: "", expected_output: "" }]); }}><Plus size={14} aria-hidden="true" />增加场景</button>
        {validation && <p className="text-xs leading-relaxed" style={mutedStyle}>{validation}</p>}
        <ErrorMessage message={error} />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t bg-surface-2 px-5 py-3" style={lineStyle}>
        <span role="status" className="flex items-center gap-1.5 text-[11px]" style={dirty ? { color: "var(--warn)" } : mutedStyle}>{dirty ? <span className="h-1.5 w-1.5 rounded-full bg-[#d69c35]" /> : <CheckCircle2 size={13} aria-hidden="true" />}{dirty ? "有未保存的修改，保存后再确认 PRD。" : saved ? "验收场景已保存。" : "场景已保存，可确认 PRD。"}</span>
        <button className={buttonClass} style={buttonStyle} disabled={busy || !!validation || !dirty} type="submit"><ButtonIcon busy={busy} icon={Save} />{busy ? "保存中…" : "保存验收场景"}</button>
      </div>
    </form>
  );
}

export function ScenarioAcceptancePanel({ run, busy, onAccept, onSave, onRequestRevision }: {
  run: Run;
  busy: boolean;
  onAccept: (checklist: AcceptanceChecklistItem[], results: AcceptanceScenarioResult[]) => Promise<void>;
  onSave: (results: AcceptanceScenarioResult[]) => Promise<void>;
  onRequestRevision: (results: AcceptanceScenarioResult[]) => Promise<void>;
}) {
  const scenarios = run.acceptance_scenarios || [];
  const [drafts, setDrafts] = useState(() => createAcceptanceDrafts(scenarios, run.acceptance_results));
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<"save" | "repair" | "accept" | null>(null);
  const actionPending = useRef(false);
  const results = toAcceptanceResults(drafts);
  const draftValidation = acceptanceDraftSaveError(drafts);
  const validation = draftValidation || acceptanceResultError(scenarios, results);
  const disabled = busy || pendingAction !== null;
  const allChecked = DEFAULT_ACCEPTANCE_CHECKLIST.every((item) => checked[item.id]);
  const passedCount = drafts.filter((item) => item.status === "passed").length;
  const failedCount = drafts.filter((item) => item.status === "failed").length;
  const untestedCount = drafts.filter((item) => item.status === "untested").length;
  const update = (id: string, patch: Partial<AcceptanceDraft>) => {
    setSavedMessage(null);
    setError(null);
    setChecked({});
    setDrafts((previous) => previous.map((item) => item.scenario_id === id ? { ...item, ...patch } : item));
  };

  async function performAction(action: "save" | "repair" | "accept") {
    if (busy || actionPending.current) return;
    if (draftValidation) { setError(draftValidation); return; }
    if (action === "repair" && !failedCount) return;
    if (action === "accept" && (validation || !allChecked)) return;
    actionPending.current = true;
    setPendingAction(action);
    setError(null);
    setSavedMessage(null);
    try {
      if (action === "accept") {
        await onAccept(DEFAULT_ACCEPTANCE_CHECKLIST.map((item) => ({ ...item, passed: !!checked[item.id] })), results);
      } else if (action === "repair") {
        await onRequestRevision(results);
        setSavedMessage("记录已保存，修复要求已准备好。请在修改区确认后生成修复版。");
      } else {
        await onSave(results);
        setSavedMessage("试用记录已保存，刷新后可以继续验证。本次保存不会完成交付。");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作未完成，请重试。");
    } finally {
      actionPending.current = false;
      setPendingAction(null);
    }
  }

  return (
    <form className={cardClass} style={{ ...cardStyle, overflow: "clip" }} onSubmit={(event) => {
      event.preventDefault();
      void performAction("accept");
    }}>
      <PanelHeader icon={ClipboardCheck} title="真实任务验证" badge="人工验收" description="打开成品实际操作，选择通过或不通过，并填写实际结果。" />
      <div className="wf-card-body space-y-5 p-5">
        <div className="sticky top-0 z-10 space-y-3 rounded-lg border bg-panel p-3 shadow-sm" style={lineStyle}>
        <div className="flex flex-wrap gap-x-5 gap-y-2 text-xs" aria-live="polite">
          <span className="text-muted">未验证 <b className="ml-1 tabular-nums">{untestedCount}</b></span>
          <span className="text-ok">通过 <b className="ml-1 tabular-nums">{passedCount}</b></span>
          <span className={failedCount ? "text-danger" : "text-muted"}>不通过 <b className="ml-1 tabular-nums">{failedCount}</b></span>
        </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" className={`${secondaryClass} w-full sm:w-auto`} style={secondaryStyle} disabled={disabled} onClick={() => void performAction("save")}><ButtonIcon busy={pendingAction === "save"} icon={Save} />{pendingAction === "save" ? "保存中…" : "保存试用记录"}</button>
            <button type="button" className={`${failedCount ? buttonClass : secondaryClass} w-full sm:w-auto`} style={failedCount ? buttonStyle : secondaryStyle} disabled={disabled || !failedCount} onClick={() => void performAction("repair")}><ButtonIcon busy={pendingAction === "repair"} icon={RotateCcw} />{pendingAction === "repair" ? "准备修复要求…" : "修复未通过场景"}</button>
          </div>
          <p className="text-[11px] leading-relaxed text-muted">{failedCount ? "修复会先保存记录，再准备修改要求；确认后创建新版本。" : "保存后可继续验证，不会自动交付。"}</p>
          {savedMessage && <SavedMessage>{savedMessage}</SavedMessage>}
          <ErrorMessage message={error} />
        </div>
        <div className="space-y-4">
          {scenarios.map((item, index) => {
            const draft = drafts.find((entry) => entry.scenario_id === item.id);
            return (
              <fieldset key={item.id} className="min-w-0 overflow-hidden rounded-lg border" style={{ borderColor: draft?.status === "failed" ? "var(--danger)" : "var(--color-line, #e7eaf0)" }} disabled={disabled}>
                <legend className="sr-only">{index + 1}. {item.title}</legend>
                <div className="flex items-center justify-between gap-3 border-b bg-surface-2 px-4 py-3" style={lineStyle}>
                  <div className="flex min-w-0 items-center gap-2.5"><span className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md border bg-panel text-[10px] font-medium tabular-nums text-muted" style={lineStyle}>{String(index + 1).padStart(2, "0")}</span><h4 className="text-xs font-semibold leading-relaxed">{item.title}</h4></div>
                </div>
                <div className="space-y-4 p-4">
                  <dl className="grid gap-3 rounded-lg bg-surface-2 p-3 text-xs leading-relaxed sm:grid-cols-2">
                    <div className="min-w-0"><dt className="mb-1 text-[10px] font-medium text-muted">任务输入</dt><dd className="whitespace-pre-wrap break-words">{item.input}</dd></div>
                    <div className="min-w-0"><dt className="mb-1 text-[10px] font-medium text-muted">预期结果</dt><dd className="whitespace-pre-wrap break-words">{item.expected_output}</dd></div>
                  </dl>
                  <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label={`场景 ${index + 1} 验证结果`}>
                    {([
                      { value: "untested", label: "未验证" },
                      { value: "passed", label: "通过" },
                      { value: "failed", label: "不通过" },
                    ] as const).map((option) => (
                      <label key={option.value} className={`flex min-w-0 cursor-pointer items-center justify-center gap-1.5 rounded-lg border px-2 py-2.5 text-xs ${draft?.status === option.value ? option.value === "failed" ? "border-danger/30 bg-danger-soft text-danger" : option.value === "passed" ? "border-ok/30 bg-ok-soft text-ok" : "border-line bg-surface-2 text-ink" : "border-line bg-panel text-muted"}`}>
                        <input type="radio" name={`scenario-${run.id}-${item.id}`} value={option.value} checked={(draft?.status || "untested") === option.value} className="h-3.5 w-3.5 shrink-0 accent-brand" onChange={() => update(item.id, { status: option.value })} />
                        {option.label}
                      </label>
                    ))}
                  </div>
                  <label className={labelClass}>
                    <span>场景 {index + 1} 实际结果</span>
                    <textarea className={fieldClass} style={fieldStyle} rows={3} maxLength={4000} value={draft?.observation || ""}
                      placeholder={draft?.status === "failed" ? "记录失败现象、错误提示，或与预期不一致的结果。" : "记录实际输出、操作结果或遇到的问题。"}
                      onChange={(event) => update(item.id, { observation: event.target.value })} />
                  </label>
                </div>
              </fieldset>
            );
          })}
        </div>
      </div>
      <div className="space-y-4 border-t bg-surface-2 p-5" style={lineStyle}>
        <div className="flex items-start gap-2.5"><ShieldCheck size={17} className="mt-0.5 shrink-0 text-brand" aria-hidden="true" /><div><h4 className="text-sm font-semibold">确认交付</h4><p className="mt-1 text-[11px] leading-relaxed" style={mutedStyle}>全部场景验证通过后，完成以下确认，保存正式验收记录。</p></div></div>
        <div className="space-y-2.5 text-xs">
          {DEFAULT_ACCEPTANCE_CHECKLIST.map((item) => <label key={item.id} className="flex cursor-pointer items-start gap-2.5 leading-relaxed"><input className={`${checkboxClass} mt-0.5`} type="checkbox" checked={!!checked[item.id]} disabled={disabled || !!validation} onChange={(event) => setChecked((previous) => ({ ...previous, [item.id]: event.target.checked }))} />{item.label}</label>)}
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4" style={lineStyle}>
          <p className="min-w-0 flex-1 text-[11px] leading-relaxed" style={mutedStyle}>{validation || (!allChecked ? "请完成上方交付确认。" : "所有验证与确认已完成，可以交付。")}</p>
          <button className={buttonClass} style={buttonStyle} disabled={disabled || !!validation || !allChecked} type="submit"><ButtonIcon busy={pendingAction === "accept"} icon={CheckCircle2} />{pendingAction === "accept" ? "保存验收中…" : "验收通过，交付"}</button>
        </div>
      </div>
    </form>
  );
}

export function AcceptanceRecord({ run }: { run: Run }) {
  if (!run.acceptance_results?.length) return null;
  const scenarios = run.acceptance_scenarios || [];
  const recordedCount = scenarios.filter((scenario) => run.acceptance_results?.some((item) => item.scenario_id === scenario.id && item.observation.trim())).length;
  return (
    <details className={`${cardClass} group`} style={cardStyle}>
      <summary className="flex cursor-pointer list-none items-center gap-3 px-5 py-4 [&::-webkit-details-marker]:hidden">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-2 text-muted"><ClipboardCheck size={16} aria-hidden="true" /></span>
        <span className="min-w-0 flex-1"><span className="block text-xs font-semibold">已保存的验收记录</span><span className="mt-0.5 block text-[11px]" style={mutedStyle}>{recordedCount} / {scenarios.length} 个场景有实际记录 · {run.current_stage === "delivered" ? "正式验收" : "试用草稿"}</span></span>
        <ChevronDown size={15} className="shrink-0 text-muted transition-transform group-open:rotate-180" aria-hidden="true" />
      </summary>
      <div className="space-y-4 border-t p-5" style={lineStyle}>
        {scenarios.map((scenario, index) => {
          const result = run.acceptance_results?.find((item) => item.scenario_id === scenario.id);
          return <div key={scenario.id} className="overflow-hidden rounded-lg border text-xs" style={lineStyle}>
            <div className="flex items-center justify-between gap-2 border-b bg-surface-2 px-3.5 py-2.5" style={lineStyle}><span className="font-medium">{index + 1}. {scenario.title}</span><ResultBadge passed={Boolean(result?.passed)} recorded={Boolean(result?.observation.trim())} /></div>
            <dl className="space-y-3 px-3.5 py-3 text-xs leading-relaxed">
              <div><dt className="mb-1 text-[10px]" style={mutedStyle}>输入</dt><dd className="whitespace-pre-wrap break-words">{scenario.input}</dd></div>
              <div><dt className="mb-1 text-[10px]" style={mutedStyle}>预期结果</dt><dd className="whitespace-pre-wrap break-words">{scenario.expected_output}</dd></div>
              <div className="border-t pt-3" style={lineStyle}><dt className="mb-1 text-[10px]" style={mutedStyle}>实际结果</dt><dd className="whitespace-pre-wrap break-words">{result?.observation || "未记录"}</dd></div>
            </dl>
          </div>;
        })}
      </div>
    </details>
  );
}

export function BundleDownload({ run }: { run: Run }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!["gate_passed", "awaiting_acceptance", "delivered"].includes(run.current_stage)) return null;
  const delivered = run.current_stage === "delivered";
  return (
    <section className={cardClass} style={cardStyle}>
      <div className="flex items-start gap-3 border-b px-5 py-4" style={lineStyle}>
        <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${delivered ? "bg-ok-soft text-ok" : "bg-brand-soft text-brand"}`}><FolderArchive size={18} strokeWidth={1.8} aria-hidden="true" /></span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2"><h3 className="text-sm font-semibold">完整交付包</h3><span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[10px] font-medium ${delivered ? "bg-ok-soft text-ok" : "bg-warn-soft text-warn"}`}>{delivered && <Check size={11} aria-hidden="true" />}{delivered ? "已验收交付" : "待人工验收"}</span></div>
          <p className="mt-1 text-xs leading-relaxed" style={mutedStyle}>{delivered ? "本版完整材料与正式验收记录，可留存或继续使用。" : "先下载材料运行和检查；验收通过后可下载正式交付版。"}</p>
        </div>
      </div>
      <div className="space-y-4 p-5">
        <div className="grid gap-2 sm:grid-cols-3">
          {[{ icon: Code2, title: "项目代码", detail: "代码与运行依赖" }, { icon: FileText, title: "使用说明", detail: "本地运行与需求" }, { icon: ClipboardCheck, title: "验收材料", detail: delivered ? "场景与正式记录" : "场景与当前记录" }].map(({ icon: Icon, title, detail }) => <div key={title} className="rounded-lg border bg-surface-2 p-3" style={lineStyle}><Icon size={16} className="mb-2 text-muted" strokeWidth={1.8} aria-hidden="true" /><div className="text-xs font-medium">{title}</div><div className="mt-1 text-[10px] leading-relaxed" style={mutedStyle}>{detail}</div></div>)}
        </div>
        <ErrorMessage message={error} />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t bg-surface-2 px-5 py-3" style={lineStyle}>
        <span className="text-[11px]" style={mutedStyle}>{delivered ? "ZIP 文件 · 包含本版验收结果" : "ZIP 文件 · 待验收版"}</span>
        <button className={buttonClass} style={buttonStyle} disabled={busy} onClick={async () => {
          setBusy(true);
          setError(null);
          try { await downloadRunBundle(run.id, delivered); }
          catch (err) { setError(err instanceof Error ? err.message : "交付包下载失败，请重试。"); }
          finally { setBusy(false); }
        }}><ButtonIcon busy={busy} icon={Download} />{busy ? "准备下载…" : delivered ? "下载完整交付包" : "下载待验收版"}</button>
      </div>
    </section>
  );
}
