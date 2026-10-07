"use client";

import { useId, useRef, useState } from "react";
import type { Decision } from "@/lib/factory";

export interface DecisionPromptProps {
  decision: Decision;
  questionNumber: number;
  totalQuestions: number;
  busy: boolean;
  onAnswer: (code: string, value: string) => Promise<boolean>;
}

export function DecisionPrompt({
  decision,
  questionNumber,
  totalQuestions,
  busy,
  onAnswer,
}: DecisionPromptProps) {
  const questionId = useId();
  const inputId = useId();
  const [answer, setAnswer] = useState("");
  const [pending, setPending] = useState(false);
  const sending = useRef(false);
  const disabled = busy || pending;
  const options = [...new Set((decision.options || "").split("/").map((option) => option.trim()).filter(Boolean))];
  const recommendation = (decision.recommendation || "").trim();

  async function submit(value: string) {
    if (busy || sending.current || !value.trim()) return;
    sending.current = true;
    setPending(true);
    try {
      if (await onAnswer(decision.code, value)) setAnswer("");
    } catch {
      // 父级呈现提交错误，卡片保留用户回答以便重试。
    } finally {
      sending.current = false;
      setPending(false);
    }
  }

  return (
    <section
      aria-labelledby={questionId}
      aria-busy={disabled}
      className="rounded-2xl border border-line bg-panel p-5 text-ink sm:p-6"
    >
      <header aria-live="polite" aria-atomic="true">
        <p className="mb-2 text-xs font-medium text-muted">问题 {questionNumber}/{totalQuestions}</p>
        <h2 id={questionId} className="text-base font-semibold leading-relaxed">
          {decision.question}
        </h2>
      </header>

      {options.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-2" role="group" aria-label="选择一个回答">
          {options.map((option) => (
            <button
              key={option}
              type="button"
              disabled={disabled}
              onClick={() => void submit(option)}
              className="rounded-full border border-line bg-background px-4 py-2 text-left text-sm leading-relaxed text-ink transition hover:bg-brand-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:cursor-wait disabled:opacity-50"
            >
              {option}
            </button>
          ))}
        </div>
      )}

      {recommendation && (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          <p className="min-w-0 flex-1 leading-relaxed text-muted">推荐：{recommendation}</p>
          <button
            type="button"
            disabled={disabled}
            onClick={() => void submit("按推荐")}
            aria-label={`按推荐回答：${recommendation}`}
            className="rounded-full border border-line bg-brand-soft px-3 py-1.5 font-medium text-ink transition hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:cursor-wait disabled:opacity-50"
          >
            按推荐
          </button>
        </div>
      )}

      <div className="mt-5 border-t border-line pt-4">
        <label htmlFor={inputId} className="mb-2 block text-xs text-muted">或写下你的回答</label>
        <textarea
          id={inputId}
          rows={2}
          value={answer}
          disabled={disabled}
          onChange={(event) => setAnswer(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.nativeEvent.isComposing) {
              event.preventDefault();
              void submit(answer.trim());
            }
          }}
          placeholder="例如：我想先面向个人用户，保留后续扩展空间。"
          className="w-full resize-none rounded-xl border border-line bg-background px-3 py-2.5 text-sm leading-relaxed text-ink outline-none transition focus:border-brand disabled:opacity-50"
        />
        <div className="mt-3 flex items-center justify-between gap-3">
          <span className="text-[11px] text-muted">Ctrl / ⌘ + Enter 发送</span>
          <button
            type="button"
            disabled={disabled || !answer.trim()}
            onClick={() => void submit(answer.trim())}
            className="rounded-full bg-brand px-4 py-2 text-sm font-medium text-ink transition hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:cursor-not-allowed disabled:opacity-50"
          >
            {pending ? "正在发送…" : "发送回答"}
          </button>
        </div>
      </div>
    </section>
  );
}
