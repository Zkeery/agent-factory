"use client";

import { useEffect, useRef } from "react";
import { Trash2 } from "lucide-react";
import type { Project } from "@/lib/factory";

export function ProjectDeleteDialog({ project, busy, error, onCancel, onConfirm }: {
  project: Project;
  busy: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);

  return (
    <dialog ref={dialog} aria-labelledby="project-delete-title" aria-describedby="project-delete-description"
      className="m-auto max-w-md rounded-2xl border border-line bg-panel p-0 text-ink shadow-xl backdrop:bg-black/25"
      style={{ width: "calc(100vw - 32px)" }}
      onCancel={(event) => { event.preventDefault(); if (!busy) onCancel(); }}>
      <div className="p-6">
        <span className="mb-4 inline-flex h-10 w-10 items-center justify-center rounded-xl" style={{ color: "var(--danger)", background: "var(--danger-soft)" }}><Trash2 size={20} /></span>
        <h2 id="project-delete-title" className="text-base font-semibold">删除这个项目？</h2>
        <p className="mt-3 break-words text-sm font-medium">{project.name}</p>
        <p id="project-delete-description" className="mt-2 text-xs leading-6 text-muted">
          项目及其全部 {project.run_count} 个版本将移入回收站，可以恢复。关联的定时任务会暂停，本地工作目录保留。
        </p>
        {error && <p role="alert" className="mt-3 rounded-lg px-3 py-2 text-xs leading-5" style={{ color: "var(--danger)", background: "var(--danger-soft)" }}>{error}</p>}
        <div className="mt-6 flex justify-end gap-2">
          <button className="button-secondary" disabled={busy} onClick={onCancel}>取消</button>
          <button className="button-primary" style={{ background: "var(--danger)", borderColor: "var(--danger)" }} disabled={busy} onClick={onConfirm}>{busy ? "正在移入…" : "移入回收站"}</button>
        </div>
      </div>
    </dialog>
  );
}
