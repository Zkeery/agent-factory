"use client";

import { useState } from "react";
import { FolderOpen, GitBranch, RotateCcw, Search, Trash2 } from "lucide-react";
import { formatApiDateTime } from "@/lib/dateTime";
import { pmStageLabel, STAGE_CN, type Project, type Run, type RunSummary, type ViewRole } from "@/lib/factory";
import { matchesProject, projectEntries, projectVersionNumber, sortProjectVersions } from "@/lib/projectNavigation";
import { cn } from "@/lib/utils";

export function ProjectNavigation({ projects, runs, deletedProjects, currentId, currentProjectId, busy, role, onSelect, onDelete, onRestore }: {
  projects: Project[];
  runs: RunSummary[];
  deletedProjects: Project[];
  currentId: string | null;
  currentProjectId: string | null;
  busy: boolean;
  role: ViewRole;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onRestore: (id: string) => void;
}) {
  const [search, setSearch] = useState("");
  const [showTrash, setShowTrash] = useState(false);
  const entries = projectEntries(projects, runs);
  const visibleProjects = entries.filter((entry) => matchesProject(entry, search));
  const visibleDeleted = deletedProjects.filter((project) => project.name.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));

  return <>
    <div className="mx-4 mb-3 flex items-center gap-2 rounded-xl border border-line bg-panel px-3 py-2.5 text-muted">
      <Search size={14} />
      <input className="min-w-0 flex-1 bg-transparent py-2 text-xs outline-none" aria-label="搜索项目" placeholder="搜索项目…" value={search} onChange={(event) => setSearch(event.target.value)} />
    </div>
    <div className="mx-5 mb-2 flex items-center justify-between gap-2 text-[11px] text-muted">
      <span className="flex items-center gap-1.5"><FolderOpen size={13} />{showTrash ? "回收站" : "我的项目"}<span>{showTrash ? deletedProjects.length : entries.length}</span></span>
      <button type="button" disabled={busy} aria-pressed={showTrash} className="flex min-h-8 shrink-0 items-center gap-1 rounded-md px-1.5 hover:bg-panel hover:text-ink disabled:opacity-40" onClick={() => setShowTrash((value) => !value)}>
        {showTrash ? <FolderOpen size={13} /> : <Trash2 size={13} />}{showTrash ? "返回项目" : "回收站"}
      </button>
    </div>
    <nav aria-label={showTrash ? "已删除项目" : "项目列表"} className="workspace-scroll min-h-0 flex-1 space-y-0.5 overflow-auto px-2">
      {!showTrash && visibleProjects.map((entry) => {
        const latest = entry.versions.at(-1);
        const active = currentProjectId ? entry.key === `project:${currentProjectId}` : entry.versions.some((version) => version.id === currentId);
        const count = Math.max(entry.project?.run_count ?? 0, entry.versions.length);
        const stage = latest ? role === "pm" ? pmStageLabel(latest.current_stage) : STAGE_CN[latest.current_stage] : count ? "正在加载版本…" : "尚未开始构建";
        return <div key={entry.key} className={cn("flex items-center rounded-lg transition", active ? "bg-brand-soft" : "hover:bg-surface-2")}>
          <button type="button" disabled={busy || !latest} aria-label={`打开项目：${entry.name}`} aria-current={active ? "page" : undefined} title={entry.name}
            className="min-w-0 flex-1 rounded-lg py-3 pl-3 pr-1 text-left text-xs disabled:cursor-default"
            onClick={() => { if (latest) onSelect(latest.id); }}>
            <span className="block truncate font-medium">{entry.name}</span>
            <span className="mt-1 block truncate text-[10px] text-muted">{count ? `${count} 个版本 · ` : ""}{latest?.auto_schedule_id ? "自动 · " : ""}{stage}</span>
          </button>
          {entry.project && <button type="button" disabled={busy} aria-label={`删除项目：${entry.name}`} title="将整个项目移入回收站"
            className="mr-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted hover:bg-panel hover:text-danger disabled:opacity-40"
            onClick={() => { if (entry.project) onDelete(entry.project.id); }}><Trash2 size={13} /></button>}
        </div>;
      })}
      {showTrash && visibleDeleted.map((project) => <div key={project.id} className="flex items-center gap-2 rounded-lg px-3 py-3 text-xs hover:bg-surface-2">
        <span className="min-w-0 flex-1"><span className="block truncate" title={project.name}>{project.name}</span><span className="mt-1 block text-[10px] text-muted">{project.run_count} 个版本 · 可恢复</span></span>
        <button type="button" disabled={busy} aria-label={`恢复项目：${project.name}`} className="flex min-h-8 shrink-0 items-center gap-1 rounded-md px-1.5 text-brand hover:bg-brand-soft disabled:opacity-40" onClick={() => onRestore(project.id)}><RotateCcw size={13} />恢复</button>
      </div>)}
      {(showTrash ? !visibleDeleted.length : !visibleProjects.length) && <div className="mx-2 rounded-lg border border-dashed border-line px-3 py-5 text-center text-xs leading-6 text-muted">{search.trim() ? "没有找到相关项目" : showTrash ? "回收站为空" : <>还没有项目<br />从一个小想法开始</>}</div>}
    </nav>
  </>;
}

export function ProjectVersionPicker({ run, runs, busy, role, onSelect }: {
  run: Run;
  runs: RunSummary[];
  busy: boolean;
  role: ViewRole;
  onSelect: (id: string) => void;
}) {
  const versions = sortProjectVersions(runs.filter((item) => run.project_id ? item.project_id === run.project_id : item.id === run.id));
  const currentListed = versions.some((item) => item.id === run.id);
  return <div className="flex min-w-0 shrink-0 items-center gap-2 border-b border-line bg-panel px-4 py-2 md:px-7">
    <label htmlFor="project-version" className="flex shrink-0 items-center gap-1.5 text-xs text-muted"><GitBranch size={14} />项目版本</label>
    <select id="project-version" aria-label="切换项目版本" value={run.id} disabled={busy || versions.length < 2 || !currentListed}
      className="min-w-0 flex-1 rounded-lg border border-line bg-panel px-2 py-2 text-xs text-ink outline-none focus:border-brand disabled:opacity-70"
      onChange={(event) => { if (event.target.value !== run.id) onSelect(event.target.value); }}>
      {!currentListed && <option value={run.id}>当前版本</option>}
      {[...versions].reverse().map((version, index) => {
        const stage = version.id === run.id ? run.current_stage : version.current_stage;
        return <option key={version.id} value={version.id}>V{projectVersionNumber(version, versions)} · {version.parent_run_id ? "修改版" : "初版"}{index === 0 ? " · 最新" : ""}{version.auto_schedule_id ? " · 自动" : ""} · {formatApiDateTime(version.created_at)} · {role === "pm" ? pmStageLabel(stage) : STAGE_CN[stage]}</option>;
      })}
    </select>
  </div>;
}
