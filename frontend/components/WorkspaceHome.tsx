"use client";

import { ArrowRight, ArrowUpRight, Check, FileText, FlaskConical, GitBranch, Layers3, MessageSquareText, PackageCheck, Sparkles, Vote } from "lucide-react";
import type { ExecutionMode, LlmProfile, Run } from "@/lib/factory";

const starters = [
  { title: "把访谈变成需求", detail: "整理用户反馈，找到下一步方向", icon: MessageSquareText, idea: "做一个整理访谈记录、提取用户需求和待确认问题的小工具。支持粘贴访谈文本，按主题汇总，导出需求清单。" },
  { title: "收集读者的想法", detail: "用投票决定下一篇创作选题", icon: Vote, idea: "做一个给独立创作者收集读者选题投票的小应用。可以添加候选选题、匿名投票，按票数查看结果。" },
  { title: "管理自己的小项目", detail: "把待办、进度和记录放在一起", icon: Layers3, idea: "做一个个人项目看板，可以创建项目、添加待办，用待开始、进行中、已完成三个状态跟踪进度，并保存项目备注。" },
];

function CreationCore() {
  return <div className="studio-core" aria-hidden="true">
    <svg className="core-wire" viewBox="0 0 260 260" fill="none">
      <circle cx="130" cy="130" r="102" stroke="currentColor" strokeOpacity=".2" strokeDasharray="2 7" />
      <circle cx="130" cy="130" r="82" stroke="currentColor" strokeOpacity=".6" />
      {[28, 52, 70].map((radius) => <ellipse key={radius} cx="130" cy="130" rx={radius} ry="82" stroke="currentColor" strokeOpacity=".35" />)}
      {[28, 52, 70].map((radius) => <ellipse key={radius} cx="130" cy="130" rx="82" ry={radius} stroke="currentColor" strokeOpacity=".35" />)}
      <ellipse cx="130" cy="130" rx="125" ry="38" transform="rotate(-35 130 130)" stroke="currentColor" strokeOpacity=".65" />
      <path d="M130 13v20M130 227v20M13 130h20M227 130h20" stroke="currentColor" strokeOpacity=".5" />
      <circle cx="220" cy="65" r="4" fill="currentColor" />
      <circle cx="45" cy="192" r="3" fill="currentColor" />
    </svg>
    <span className="core-center"><Layers3 size={26} strokeWidth={1.2} /></span>
    <span className="core-caption core-caption-build">BUILD AGENT</span>
    <span className="core-caption core-caption-verify">VERIFY AGENT</span>
    <span className="core-coordinate">IDEA → REALITY</span>
  </div>;
}

export function WorkspaceHome({ idea, onIdeaChange, onSubmit, busy, provider, profiles, onProviderChange, executionMode, onExecutionModeChange }: {
  idea: string; onIdeaChange: (value: string) => void; onSubmit: () => void; busy: boolean;
  provider: string; profiles: LlmProfile[]; onProviderChange: (value: string) => void;
  executionMode: ExecutionMode; onExecutionModeChange: (value: ExecutionMode) => void;
}) {
  return <div className="workspace-home">
    <div className="studio-hero">
      <div>
        <div className="studio-kicker flex items-center gap-2.5"><span className="h-1.5 w-1.5 rounded-full bg-brand" />YOUR NEXT BUILD STARTS HERE</div>
        <h1 className="studio-title">好想法，<br /><strong>现在就造。</strong></h1>
        <p className="studio-description">用自然语言定义产品，与 Agent 一起构建。<br />你把握方向，让开发、验证与迭代在这里发生。</p>
      </div>
      <CreationCore />
    </div>

    <div className="idea-composer">
      <div className="composer-label"><span className="flex items-center gap-2"><Sparkles size={12} className="text-brand" />描述你的下一个作品</span><span>IDEA INPUT / 01</span></div>
      <label htmlFor="project-idea" className="sr-only">描述你的产品想法</label>
      <textarea id="project-idea" rows={3} value={idea} disabled={busy} onChange={(e) => onIdeaChange(e.target.value)}
        placeholder={"一个帮我整理访谈的工具？一个收集灵感的小应用？\n说说给谁用、解决什么问题，剩下的一起拆解。"}
        onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && !e.nativeEvent.isComposing) { e.preventDefault(); onSubmit(); } }} />
      <div className="composer-toolbar flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3">
        <div className="flex min-w-0 flex-wrap items-center gap-3 text-xs text-muted"><span className="flex items-center gap-2"><Sparkles size={15} />
          <select aria-label="选择本轮模型" className="max-w-[180px] bg-transparent py-1 text-xs text-ink outline-none" value={provider} disabled={busy} onChange={(e) => onProviderChange(e.target.value)}>
            <option value="">默认模型</option>{profiles.map((p) => <option key={p.id} value={p.id} disabled={!p.available}>{p.label}{p.available ? "" : "（未配置）"}</option>)}
          </select></span>
          <span className="flex items-center gap-2 border-l border-line pl-3"><GitBranch size={15} /><select aria-label="选择执行方式" className="max-w-[190px] bg-transparent py-1 text-xs text-ink outline-none" value={executionMode} disabled={busy} onChange={(e) => onExecutionModeChange(e.target.value as ExecutionMode)}><option value="agent_team">Agent 协作 · 开发＋验证</option><option value="workflow">标准工作流</option></select></span>
        </div>
        <button className="button-primary" disabled={busy || !idea.trim()} onClick={onSubmit}>{busy ? "正在创建…" : "开始共创"}<ArrowRight size={16} /></button>
      </div>
    </div>
    <div className="mb-6 mt-3 flex items-center justify-between gap-2 text-[11px] leading-5 text-muted"><span>{executionMode === "agent_team" ? "先确认需求。开发与验证 Agent 分工执行，检查失败后最多自动修复 3 轮。" : "先确认需求，再按固定阶段构建。你随时可以补充或纠正。"}</span><span className="hidden shrink-0 lg:inline">⌘ / Ctrl + Enter</span></div>

    <div className="mb-3 mt-7 flex items-center justify-between"><h2 className="text-xs font-medium text-ink">从一个方向开始</h2><span className="studio-kicker" style={{ color: "var(--muted-2)", fontSize: 9 }}>QUICK START ↗</span></div>
    <div className="grid gap-3 min-[701px]:grid-cols-3">
      {starters.map(({ title, detail, icon: Icon, idea: value }) => <button key={title} disabled={busy} className="starter-card group" onClick={() => { onIdeaChange(value); document.getElementById("project-idea")?.focus(); }}>
        <span className="starter-icon shrink-0"><Icon size={17} /></span>
        <span className="min-w-0 w-full flex-1"><span className="flex items-center justify-between gap-2 text-[12px] font-medium text-ink">{title}<ArrowUpRight size={14} className="text-muted transition group-hover:text-brand" /></span><span className="mt-1.5 block text-[11px] leading-5 text-muted">{detail}</span></span>
      </button>)}
    </div>
    <div className="studio-footer">
      <div className="studio-footer-label">THE<br />PROCESS</div>
      <div className="studio-footer-path">
        {[
          { icon: FileText, title: "01  理清需求", detail: "共同确认需求文档，提前约定验收场景" },
          { icon: FlaskConical, title: "02  验证成品", detail: "在本地试用，用真实任务记录结果" },
          { icon: PackageCheck, title: "03  交付与迭代", detail: "打包源码和验证记录，沿着当前版本继续改" },
        ].map(({ icon: Icon, title, detail }) => <div key={title} title={detail}><div className="flex items-center gap-2 text-[11px] font-medium text-muted"><Icon size={13} className="text-brand" />{title}</div></div>)}
      </div>
    </div>
  </div>;
}

export function WorkflowProgress({ run }: { run: Run }) {
  const stage = run.current_stage;
  const phase = ["idea_submitted", "clarifying", "awaiting_answers", "prd_drafting", "awaiting_prd_confirm"].includes(stage) ? 0
    : ["awaiting_acceptance"].includes(stage) ? 2 : stage === "delivered" ? 3 : 1;
  const failed = ["failed", "gate_failed", "cancelled"].includes(stage);
  return <div className="grid grid-cols-4 gap-2 border-b border-line bg-panel px-5 py-4 md:px-7">
    {["需求共创", "构建应用", "任务验证", "交付迭代"].map((title, i) => <div key={title} className="phase-step" data-state={i === phase && !failed ? "current" : i < phase ? "done" : "pending"}>
      <span className="phase-step-number">{i < phase ? <Check size={12} /> : i + 1}</span><span className="truncate text-[11px] sm:text-xs">{title}</span>
    </div>)}
  </div>;
}
