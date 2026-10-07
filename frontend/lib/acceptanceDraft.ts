import type { AcceptanceScenario, AcceptanceScenarioResult } from "./factory";

export type AcceptanceDraftStatus = "untested" | "passed" | "failed";

export interface AcceptanceDraft {
  scenario_id: string;
  status: AcceptanceDraftStatus;
  observation: string;
}

export function createAcceptanceDrafts(
  scenarios: AcceptanceScenario[],
  results: AcceptanceScenarioResult[] = [],
): AcceptanceDraft[] {
  const byId = new Map(results.map((result) => [result.scenario_id, result]));
  return scenarios.map((scenario) => {
    const result = byId.get(scenario.id);
    return {
      scenario_id: scenario.id,
      status: result?.passed ? "passed" : result?.observation.trim() ? "failed" : "untested",
      observation: result?.observation || "",
    };
  });
}

export function acceptanceDraftSaveError(drafts: AcceptanceDraft[]): string | null {
  for (const [index, draft] of drafts.entries()) {
    if (draft.observation.length > 4000) return `场景 ${index + 1} 的实际结果最多 4000 字。`;
    if (draft.status === "untested" && draft.observation.trim()) {
      return `场景 ${index + 1} 已填写实际结果，请选择“通过”或“不通过”后保存。`;
    }
    if (draft.status !== "untested" && !draft.observation.trim()) {
      return `请填写场景 ${index + 1} 实际看到了什么，再保存验证结果。`;
    }
  }
  return null;
}

export function toAcceptanceResults(drafts: AcceptanceDraft[]): AcceptanceScenarioResult[] {
  return drafts.filter((draft) => draft.status !== "untested").map((draft) => ({
    scenario_id: draft.scenario_id,
    passed: draft.status === "passed",
    observation: draft.observation,
  }));
}

function shorten(value: string, limit: number): string {
  const text = value.trim();
  if (text.length <= limit) return text;
  if (limit <= 0) return "";
  // Avoid leaving half of a surrogate pair at the end of a bounded field.
  return text.slice(0, limit - 1).replace(/[\uD800-\uDBFF]$/, "") + "…";
}

export function buildFailureRevisionDraft(
  scenarios: AcceptanceScenario[],
  results: AcceptanceScenarioResult[],
): string {
  const byId = new Map(results.map((result) => [result.scenario_id, result]));
  const failures = scenarios.flatMap((scenario, index) => {
    const result = byId.get(scenario.id);
    return result && !result.passed && result.observation.trim() ? [{ scenario, result, index }] : [];
  });
  if (!failures.length) return "";

  const header = "请保留已通过的功能，基于当前版本修复以下未通过场景。以下为逐项摘要，完整输入、预期和实际记录已保存，请以父版本的完整记录为准。\n\n";
  const blockBudget = Math.floor((4000 - header.length - (failures.length - 1) * 2) / failures.length);
  const blocks = failures.map(({ scenario, result, index }) => {
    const prefix = `场景 ${index + 1}\n`;
    const labels = ["标题：", "输入：", "预期：", "实际："];
    const available = Math.max(0, blockBudget - prefix.length - labels.join("\n").length);
    const titleBudget = Math.min(60, Math.floor(available / 6));
    const fieldBudget = Math.floor((available - titleBudget) / 3);
    const limits = [titleBudget, fieldBudget, fieldBudget, available - titleBudget - fieldBudget * 2];
    const values = [scenario.title, scenario.input, scenario.expected_output, result.observation];
    return prefix + labels.map((label, field) => label + shorten(values[field], limits[field])).join("\n");
  });
  return header + blocks.join("\n\n");
}
