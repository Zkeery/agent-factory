import type { Project, RunSummary } from "./factory";

export interface ProjectEntry {
  key: string;
  name: string;
  project?: Project;
  versions: RunSummary[];
}

export function sortProjectVersions(runs: RunSummary[]): RunSummary[] {
  return [...runs].sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id));
}

/** 可见版本按创建时间、再按标识连续编号，从 1 开始。列表里不应再包含被替代的失败版本。 */
export function projectVersionNumber(version: { id: string; created_at?: string }, versions: { id: string; created_at: string }[]): number {
  const ordered = [...versions].sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id));
  const index = ordered.findIndex((item) => item.id === version.id);
  return index >= 0 ? index + 1 : 1;
}

/** Group by identity, never by title: two projects can legitimately share a name. */
export function projectEntries(projects: Project[], runs: RunSummary[]): ProjectEntry[] {
  const entries = new Map<string, ProjectEntry>(projects.map((project) => [
    `project:${project.id}`, { key: `project:${project.id}`, name: project.name, project, versions: [] },
  ]));
  for (const run of runs) {
    const key = run.project_id ? `project:${run.project_id}` : `run:${run.id}`;
    const entry: ProjectEntry = entries.get(key) ?? { key, name: run.idea.split("\n")[0], versions: [] };
    entry.versions.push(run);
    entries.set(key, entry);
  }
  return [...entries.values()].map((entry) => ({ ...entry, versions: sortProjectVersions(entry.versions) }))
    .sort((a, b) => {
      const aDate = a.versions.at(-1)?.created_at ?? a.project?.updated_at ?? "";
      const bDate = b.versions.at(-1)?.created_at ?? b.project?.updated_at ?? "";
      return bDate.localeCompare(aDate) || a.key.localeCompare(b.key);
    });
}

export function matchesProject(entry: ProjectEntry, query: string): boolean {
  const search = query.trim().toLocaleLowerCase();
  return !search || [entry.name, entry.project?.idea_summary ?? "", ...entry.versions.map((run) => run.idea)]
    .some((value) => value.toLocaleLowerCase().includes(search));
}
