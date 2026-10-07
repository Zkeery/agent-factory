import { describe, expect, it } from "vitest";
import type { Project, RunSummary } from "./factory";
import { matchesProject, projectEntries, sortProjectVersions } from "./projectNavigation";

const project = (id: string, name = "五子棋"): Project => ({ id, name, idea_summary: "", workspace_path: "", created_at: "2026-10-01", updated_at: "2026-10-01", run_count: 0 });
const run = (id: string, project_id: string | null, day: number, idea = "五子棋"): RunSummary => ({ id, project_id, idea, created_at: `2026-10-0${day}T10:00:00`, current_stage: "awaiting_acceptance", status: "running" });

describe("项目导航与版本归属", () => {
  it("同名项目仍分开，多个版本只产生一个项目删除目标", () => {
    const groups = projectEntries([project("one"), project("two")], [run("v2", "one", 2), run("other", "two", 1), run("v1", "one", 1)]);
    expect(groups).toHaveLength(2);
    expect(groups[0].project?.id).toBe("one");
    expect(groups[0].versions.map((item) => item.id)).toEqual(["v1", "v2"]);
    expect(groups[1].versions.map((item) => item.id)).toEqual(["other"]);
  });
  it("搜索命中旧版本仍保留完整项目版本与最新入口", () => {
    const [entry] = projectEntries([project("one", "棋盘工具")], [run("old", "one", 1, "旧版 AI 对弈"), run("new", "one", 2, "新要求")]);
    expect(matchesProject(entry, "  ai 对弈  ")).toBe(true);
    expect(entry.versions.at(-1)?.id).toBe("new");
    expect(entry.versions).toHaveLength(2);
    expect(matchesProject(entry, "不存在")).toBe(false);
  });
  it("保留空项目和未归属历史记录，不错误提供整项目删除", () => {
    const entries = projectEntries([project("empty")], [run("legacy1", null, 1), run("legacy2", null, 2)]);
    expect(entries).toHaveLength(3);
    expect(entries.filter((entry) => entry.project).map((entry) => entry.project?.id)).toEqual(["empty"]);
    expect(entries.find((entry) => entry.project)?.versions).toEqual([]);
  });
  it("项目元数据尚未加载时也按项目ID合并，不把同项目显示成多条", () => {
    expect(projectEntries([], [run("v1", "one", 1), run("v2", "one", 2)])).toHaveLength(1);
  });
  it("分支版本按生成时间编号，排序不改变原始列表", () => {
    const versions = [run("v3", "one", 3), run("v1", "one", 1), { ...run("v2", "one", 2), parent_run_id: "v1" }];
    expect(sortProjectVersions(versions).map((item) => item.id)).toEqual(["v1", "v2", "v3"]);
    expect(versions.map((item) => item.id)).toEqual(["v3", "v1", "v2"]);
  });
});
