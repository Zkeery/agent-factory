"use client";

import { useRef, useState } from "react";
import {
  AlertCircle, ArrowRight, Check, CheckCircle2, ChevronDown, ClipboardCheck,
  Code2, Download, FileText, FolderArchive, GitBranch, ListChecks, Loader2,
  MessageSquareText, Save, type LucideIcon,
} from "lucide-react";
import {
  acceptanceScenarioError,
  DEFAULT_ACCEPTANCE_CHECKLIST,
  downloadRunBundle,
  mainFlowScenario,
  preservedScenarioResults,
  type AcceptanceChecklistItem,
  type AcceptanceScenario,
  type AcceptanceScenarioResult,
  type Run,
} from "@/lib/factory";

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
  const main = mainFlowScenario(scenarios);
  const mainIndex = main ? scenarios.findIndex((item) => item.id === main.id) : -1;
  const extraCount = scenarios.filter((item) => item.id !== main?.id).length;
  const validation = acceptanceScenarioError(scenarios);
  const update = (field: "title" | "input" | "expected_output", value: string) => {
    if (mainIndex < 0) return;
    setSaved(false);
    onChange(scenarios.map((item, index) => index === mainIndex ? { ...item, [field]: value } : item));
  };

  return (
    <form className={cardClass} style={cardStyle} onSubmit={async (event) => {
      event.preventDefault();
      if (busy || validation || !main) return;
      setError(null);
      try {
        await onSave();
        setSaved(true);
      } catch (err) {
        setError(err instanceof Error ? err.message : "验收场景未保存，请重试。");
      }
    }}>
      <PanelHeader icon={ListChecks} title="约定主流程" badge="只问这一件事" description="写清主流程怎么操作、怎样算走通。成品完成后只问这一件事。需求文档里的其他验收标准仍保留，验收时不再逐条提问。" />
      <div className="wf-card-body space-y-4 p-5">
        {main ? (
          <fieldset className="overflow-hidden rounded-lg border bg-surface-2" style={lineStyle} disabled={busy}>
            <legend className="sr-only">主流程</legend>
            <div className="space-y-3 p-3.5">
              <label className={labelClass}>
                <span>主流程名称</span>
                <input className={fieldClass} style={fieldStyle} value={main.title} maxLength={200} onChange={(event) => update("title", event.target.value)} />
              </label>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className={labelClass}>
                  <span>主流程怎么操作</span>
                  <textarea className={fieldClass} style={fieldStyle} rows={3} value={main.input} maxLength={2000} onChange={(event) => update("input", event.target.value)} />
                </label>
                <label className={labelClass}>
                  <span>主流程预期结果</span>
                  <textarea className={fieldClass} style={fieldStyle} rows={3} value={main.expected_output} maxLength={2000} onChange={(event) => update("expected_output", event.target.value)} />
                </label>
              </div>
            </div>
          </fieldset>
        ) : <p className="text-xs leading-relaxed" style={mutedStyle}>请写清主流程：怎么操作，以及怎样算走通。</p>}
        {extraCount > 0 && <p className="text-xs leading-relaxed" style={mutedStyle}>这一版还留着更早的 {extraCount} 条场景。验收时不再逐条提问，保存时会一并保留。</p>}
        {validation && <p className="text-xs leading-relaxed" style={mutedStyle}>{validation}</p>}
        <ErrorMessage message={error} />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t bg-surface-2 px-5 py-3" style={lineStyle}>
        <span role="status" className="flex items-center gap-1.5 text-[11px]" style={dirty ? { color: "var(--warn)" } : mutedStyle}>{dirty ? <span className="h-1.5 w-1.5 rounded-full bg-[#d69c35]" /> : <CheckCircle2 size={13} aria-hidden="true" />}{dirty ? "有未保存的修改，保存后再确认需求。" : saved ? "主流程已保存。" : "主流程已保存，可确认需求。"}</span>
        <button className={buttonClass} style={buttonStyle} disabled={busy || !!validation || !dirty} type="submit"><ButtonIcon busy={busy} icon={Save} />{busy ? "保存中…" : "保存验收场景"}</button>
      </div>
    </form>
  );
}

export function MainFlowAcceptance({ run, busy, onAccept, onFeedback }: {
  run: Run;
  busy: boolean;
  onAccept: (checklist: AcceptanceChecklistItem[], results: AcceptanceScenarioResult[]) => Promise<void>;
  onFeedback: (note: string, mainPassed: boolean) => Promise<void>;
}) {
  const scenarios = run.acceptance_scenarios || [];
  const main = mainFlowScenario(scenarios);
  const scenarioMode = run.acceptance_mode === "scenario";
  const extraCount = scenarios.filter((item) => item.id !== main?.id).length;
  const [choice, setChoice] = useState<"passed" | "failed" | null>(null);
  const [note, setNote] = useState(() => run.acceptance_note && run.acceptance_note !== "验收通过" ? run.acceptance_note : "");
  const [error, setError] = useState<string | null>(null);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<"accept" | "feedback" | null>(null);
  const actionPending = useRef(false);
  const disabled = busy || pendingAction !== null;
  const feedback = note.trim();
  const canAccept = choice === "passed" && !(scenarioMode && !main);
  const canFeedback = choice !== null && feedback.length > 0;

  function mainResults(passed: boolean, observation: string): AcceptanceScenarioResult[] {
    if (!scenarioMode || !main) return [];
    return [
      { scenario_id: main.id, passed, observation },
      ...preservedScenarioResults(scenarios, run.acceptance_results || [], main.id),
    ];
  }

  async function perform(action: "accept" | "feedback") {
    if (disabled || actionPending.current) return;
    if (action === "accept" && !canAccept) return;
    if (action === "feedback" && !canFeedback) return;
    actionPending.current = true;
    setPendingAction(action);
    setError(null);
    setSavedMessage(null);
    try {
      if (action === "accept") {
        await onAccept(
          DEFAULT_ACCEPTANCE_CHECKLIST.map((item) => ({ id: item.id, label: item.label, passed: true })),
          mainResults(true, feedback || "主流程走通"),
        );
      } else {
        await onFeedback(feedback, choice === "passed");
        setSavedMessage("反馈已保存。请在下方确认修改要求，再创建修改版。");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作未完成，请重试。");
    } finally {
      actionPending.current = false;
      setPendingAction(null);
    }
  }

  const hint = choice === null
    ? "先确认主流程是否走通。"
    : choice === "failed"
      ? (feedback ? "反馈会留下来，确认后才创建修改版。" : "写下没走通的地方，再准备修改版。")
      : "主流程走通就可以交付。如果还有其他问题，写在反馈里再准备修改版。";

  return (
    <form className={cardClass} style={cardStyle} onSubmit={(event) => { event.preventDefault(); void perform("accept"); }}>
      <PanelHeader icon={ClipboardCheck} title="主流程是否走通" badge="人工验收" description="打开成品，按下面的主流程走一遍。走通了就可以验收；没走通或还有其他问题，写在反馈里。" />
      <div className="wf-card-body space-y-4 p-5">
        {main && (
          <dl className="grid gap-3 rounded-lg bg-surface-2 p-3 text-xs leading-relaxed sm:grid-cols-2">
            <div className="min-w-0 sm:col-span-2"><dt className="mb-1 text-[10px] font-medium text-muted">主流程</dt><dd className="font-medium">{main.title}</dd></div>
            <div className="min-w-0"><dt className="mb-1 text-[10px] font-medium text-muted">怎么操作</dt><dd className="whitespace-pre-wrap break-words">{main.input}</dd></div>
            <div className="min-w-0"><dt className="mb-1 text-[10px] font-medium text-muted">怎样算走通</dt><dd className="whitespace-pre-wrap break-words">{main.expected_output}</dd></div>
          </dl>
        )}
        {extraCount > 0 && <p className="text-xs leading-relaxed" style={mutedStyle}>更早的其他场景仍保存在记录里，这次不再逐条提问。</p>}
        <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="主流程是否走通">
          {([
            { value: "passed", label: "走通了" },
            { value: "failed", label: "没走通" },
          ] as const).map((option) => (
            <label key={option.value} className={`flex cursor-pointer items-center justify-center gap-2 rounded-lg border px-3 py-3 text-xs ${choice === option.value ? option.value === "failed" ? "border-danger/30 bg-danger-soft text-danger" : "border-ok/30 bg-ok-soft text-ok" : "border-line bg-panel text-muted"}`}>
              <input type="radio" name={`main-flow-${run.id}`} value={option.value} checked={choice === option.value} disabled={disabled} className="h-3.5 w-3.5 shrink-0 accent-brand" onChange={() => { setChoice(option.value); setSavedMessage(null); setError(null); }} />
              {option.label}
            </label>
          ))}
        </div>
        <label className={labelClass}>
          <span>反馈</span>
          <textarea className={fieldClass} style={fieldStyle} rows={4} maxLength={4000} value={note} disabled={disabled}
            placeholder="主流程没走通，或还有其他问题，写在这里。例如：记了一笔支出后，余额没有按预期变化。"
            onChange={(event) => { setNote(event.target.value); setSavedMessage(null); }} />
        </label>
        <p className="text-[11px] leading-relaxed" style={mutedStyle}>{hint}</p>
        {savedMessage && <SavedMessage>{savedMessage}</SavedMessage>}
        <ErrorMessage message={error} />
      </div>
      <div className="flex flex-wrap items-center justify-end gap-2 border-t bg-surface-2 px-5 py-3" style={lineStyle}>
        <button type="button" className={secondaryClass} style={secondaryStyle} disabled={disabled || !canFeedback} onClick={() => void perform("feedback")}><ButtonIcon busy={pendingAction === "feedback"} icon={GitBranch} />{pendingAction === "feedback" ? "保存反馈…" : "按反馈准备修改版"}</button>
        <button className={buttonClass} style={buttonStyle} disabled={disabled || !canAccept} type="submit"><ButtonIcon busy={pendingAction === "accept"} icon={CheckCircle2} />{pendingAction === "accept" ? "保存验收中…" : "验收通过，交付"}</button>
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
