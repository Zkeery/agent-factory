import { describe, expect, it } from "vitest";
import {
  acceptanceDraftSaveError,
  buildFailureRevisionDraft,
  createAcceptanceDrafts,
  toAcceptanceResults,
  type AcceptanceDraft,
} from "./acceptanceDraft";
import { acceptanceResultError, type AcceptanceScenario } from "./factory";

const scenarios: AcceptanceScenario[] = [
  { id: "turn", title: "AI 回合", input: "玩家在天元落子", expected_output: "AI 在一个空位落下一颗白子" },
  { id: "occupied", title: "重复落子", input: "点击已有棋子的交叉点", expected_output: "不新增棋子，不切换回合" },
  { id: "restart", title: "重新开始", input: "点击重新开始", expected_output: "棋盘清空，由玩家先行" },
];

describe("人工验收的三态草稿", () => {
  it("历史 false 空记录恢复为未验证，有实际结果才恢复为不通过", () => {
    const drafts = createAcceptanceDrafts(scenarios, [
      { scenario_id: "turn", passed: false, observation: "玩家落子后 AI 没有响应" },
      { scenario_id: "occupied", passed: false, observation: " " },
      { scenario_id: "restart", passed: true, observation: "棋盘清空，轮到黑子" },
    ]);
    expect(drafts.map((draft) => draft.status)).toEqual(["failed", "untested", "passed"]);
    expect(drafts[0].observation).toBe("玩家落子后 AI 没有响应");
  });

  it("未填写的新场景不会默认为失败，旧版本场景不会混入", () => {
    const drafts = createAcceptanceDrafts(scenarios, [{ scenario_id: "old", passed: false, observation: "旧问题" }]);
    expect(drafts.map((draft) => draft.status)).toEqual(["untested", "untested", "untested"]);
    expect(toAcceptanceResults(drafts)).toEqual([]);
  });

  it("填写观察不自动判失败，选择结果前不能保存含糊状态", () => {
    const drafts = createAcceptanceDrafts(scenarios);
    drafts[0].observation = "AI 没有响应";
    expect(acceptanceDraftSaveError(drafts)).toContain("请选择");
    expect(toAcceptanceResults(drafts)).toEqual([]);
  });

  it("选择通过或不通过都需要实际结果，且约束4000字", () => {
    for (const status of ["passed", "failed"] as const) {
      const draft: AcceptanceDraft = { scenario_id: "turn", status, observation: " " };
      expect(acceptanceDraftSaveError([draft])).toContain("实际看到了什么");
      expect(acceptanceDraftSaveError([{ ...draft, observation: "字".repeat(4001) }])).toContain("4000");
    }
  });

  it("只保存已判定场景，失败与通过刷新后保留，未测场景不伪造布尔结果", () => {
    const drafts = createAcceptanceDrafts(scenarios);
    drafts[0] = { scenario_id: "turn", status: "failed", observation: "AI 没有落子" };
    drafts[2] = { scenario_id: "restart", status: "passed", observation: "棋盘已清空" };
    expect(acceptanceDraftSaveError(drafts)).toBeNull();
    const results = toAcceptanceResults(drafts);
    expect(results).toEqual([
      { scenario_id: "turn", passed: false, observation: "AI 没有落子" },
      { scenario_id: "restart", passed: true, observation: "棋盘已清空" },
    ]);
    expect(createAcceptanceDrafts(scenarios, results)).toEqual(drafts);
    expect(acceptanceResultError(scenarios, results)).not.toBeNull();
  });

  it("全部实际通过才满足场景交付条件，失败记录只可保存", () => {
    const drafts: AcceptanceDraft[] = scenarios.map((scenario) => ({ scenario_id: scenario.id, status: "passed", observation: scenario.expected_output }));
    expect(acceptanceResultError(scenarios, toAcceptanceResults(drafts))).toBeNull();
    drafts[0].status = "failed";
    expect(acceptanceDraftSaveError(drafts)).toBeNull();
    expect(acceptanceResultError(scenarios, toAcceptanceResults(drafts))).toContain("未通过");
    const sideIssue = drafts.map((draft, index) => index === 0
      ? { ...draft, status: "passed" as const, observation: "主流程走通" }
      : index === 1
        ? { ...draft, status: "failed" as const, observation: "重复点击仍新增了一颗棋子" }
        : draft);
    expect(acceptanceResultError(scenarios, toAcceptanceResults(sideIssue))).toBeNull();
  });
});

describe("失败场景修复草稿", () => {
  it("保留每个失败的标题、输入、预期和实际，排除通过与外部场景", () => {
    const text = buildFailureRevisionDraft(scenarios, [
      { scenario_id: "turn", passed: false, observation: "AI 没有落子" },
      { scenario_id: "occupied", passed: true, observation: "不会重复落子" },
      { scenario_id: "restart", passed: false, observation: "重新开始后旧棋子仍在" },
      { scenario_id: "old", passed: false, observation: "旧版失败" },
    ]);
    for (const value of ["标题：AI 回合", "输入：玩家在天元落子", "预期：AI 在一个空位落下一颗白子", "实际：AI 没有落子", "标题：重新开始", "实际：重新开始后旧棋子仍在"]) expect(text).toContain(value);
    expect(text).not.toContain("标题：重复落子");
    expect(text).not.toContain("旧版失败");
  });

  it("没有已记录失败时不提供修复草稿", () => {
    expect(buildFailureRevisionDraft(scenarios, [])).toBe("");
    expect(buildFailureRevisionDraft(scenarios, [
      { scenario_id: "turn", passed: true, observation: "完成" },
      { scenario_id: "restart", passed: false, observation: " " },
    ])).toBe("");
  });

  it("十个大文本失败均分摘要长度，不因前面的长文本丢掉后续场景", () => {
    const many = Array.from({ length: 10 }, (_, index) => ({
      id: `s-${index}`, title: `任务${index}标题${"标题".repeat(100)}`,
      input: `任务${index}输入${"输".repeat(2000)}`,
      expected_output: `任务${index}预期${"期".repeat(2000)}`,
    }));
    const results = many.map((scenario, index) => ({ scenario_id: scenario.id, passed: false, observation: `任务${index}实际${"实".repeat(4000)}` }));
    const text = buildFailureRevisionDraft(many, results);
    expect(text.length).toBeLessThanOrEqual(4000);
    expect(text).toContain("完整输入、预期和实际记录已保存");
    for (let index = 0; index < 10; index++) {
      for (const field of ["标题", "输入", "预期", "实际"]) expect(text).toContain(`${field}：任务${index}${field}`);
    }
    expect((text.match(/场景 \d+\n/g) || []).length).toBe(10);
  });
});
