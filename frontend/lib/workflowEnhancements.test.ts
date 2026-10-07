import { afterEach, describe, expect, it, vi } from "vitest";
import {
  acceptanceResultError,
  acceptanceScenarioError,
  acceptRun,
  canReviseRun,
  confirmPrd,
  deriveMessages,
  downloadRunBundle,
  latestEvidence,
  reviseRun,
  saveAcceptanceResults,
  selectArtifactAfterRefresh,
  type AcceptanceScenario,
  type Artifact,
  type Run,
} from "./factory";

const scenarios: AcceptanceScenario[] = [
  { id: "normal", title: "正常输入", input: "一段真实访谈", expected_output: "提取明确需求并保留来源" },
  { id: "missing", title: "缺少信息", input: "只提供问题，没有用户身份", expected_output: "列出待确认项，不编造身份" },
  { id: "empty", title: "空输入", input: "空白", expected_output: "提示填写内容，不开始生成" },
];

const run: Run = {
  id: "parent",
  idea: "整理访谈",
  status: "waiting",
  current_stage: "awaiting_acceptance",
  failure_reason: null,
  decisions: [],
  evidence: [{ stage: "prd", title: "PRD", content_path: "prd.md" }, { stage: "code", title: "Code", content_path: "app.py" }],
  metric: null,
};

afterEach(() => vi.unstubAllGlobals());

describe("按具体任务验收", () => {
  it("确认附带当前需求版本，后端可拒绝陈旧批准", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(run), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await confirmPrd("parent", 3);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ confirmed: true, prd_revision: 3 });
  });

  it("未定义完整的至少三个场景时不能确认", () => {
    expect(acceptanceScenarioError(scenarios)).toBeNull();
    expect(acceptanceScenarioError(scenarios.slice(0, 2))).not.toBeNull();
    expect(acceptanceScenarioError(scenarios.map((item, i) => i === 1 ? { ...item, expected_output: " " } : item))).not.toBeNull();
    expect(acceptanceScenarioError([scenarios[0], scenarios[0], scenarios[2]])).not.toBeNull();
  });

  it("必须覆盖全部场景、实际观察非空且通过，草稿不能冒充交付", () => {
    const complete = scenarios.map((item) => ({ scenario_id: item.id, passed: true, observation: "实际输入并检查，结果符合预期。" }));
    expect(acceptanceResultError(scenarios, complete)).toBeNull();
    expect(acceptanceResultError(scenarios, complete.slice(0, 2))).not.toBeNull();
    expect(acceptanceResultError(scenarios, [complete[0], complete[0], complete[2]])).not.toBeNull();
    expect(acceptanceResultError(scenarios, complete.map((item, i) => i === 0 ? { ...item, passed: false } : item))).not.toBeNull();
    expect(acceptanceResultError(scenarios, complete.map((item, i) => i === 0 ? { ...item, observation: " " } : item))).not.toBeNull();
  });

  it("失败的真实观察可以保存，但验收提交仍带逐项结果", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(run), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const results = [{ scenario_id: "missing", passed: false, observation: "输出编造了用户身份" }];
    await saveAcceptanceResults("parent", results);
    expect(fetchMock.mock.calls[0][0]).toContain("/parent/acceptance-results");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ scenario_results: results });
    fetchMock.mockResolvedValue(new Response(JSON.stringify(run), { status: 200 }));
    await acceptRun("parent", [], "验证记录", results);
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ checklist: [], note: "验证记录", scenario_results: results });
  });
});

describe("版本与交付记录", () => {
  it("已有成品的可编辑阶段才显示继续修改", () => {
    expect(canReviseRun(run)).toBe(true);
    expect(canReviseRun({ ...run, current_stage: "building" })).toBe(false);
    expect(canReviseRun({ ...run, evidence: run.evidence.slice(0, 1) })).toBe(false);
  });

  it("同一修改重试保留请求标识，避免新建重复子版本", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response(JSON.stringify({ ...run, id: "child", parent_run_id: "parent" })));
    vi.stubGlobal("fetch", fetchMock);
    await reviseRun("parent", "修复空输入", "same-request");
    await reviseRun("parent", "修复空输入", "same-request");
    const bodies = fetchMock.mock.calls.map((call) => JSON.parse(call[1].body));
    expect(bodies[0]).toEqual({ change_request: "修复空输入", request_id: "same-request" });
    expect(bodies[1]).toEqual(bodies[0]);
  });

  it("历史回放保留本版修改和补充要求", () => {
    const messages = deriveMessages({ ...run, change_request: "增加复制按钮", requirement_feedback: [{ id: "f1", feedback: "复制结果不要带标题", created_at: "2026-10-05" }] });
    expect(messages.map((item) => item.content)).toContain("本版修改：增加复制按钮");
    expect(messages.map((item) => item.content)).toContain("补充需求：复制结果不要带标题");
  });

  it("需求正文按证据编号使用最新稿，不依赖响应顺序", () => {
    const oldPrd = { id: 2, stage: "prd", title: "初稿", content_path: "old.md", content: "Q1 未回答" };
    const newPrd = { id: 5, stage: "prd", title: "新稿", content_path: "new.md", content: "Q1 个人用户" };
    for (const evidence of [[oldPrd, newPrd], [newPrd, oldPrd]]) {
      expect(latestEvidence(evidence, "prd")).toEqual(newPrd);
      expect(deriveMessages({ ...run, evidence }).find((item) => item.kind === "prd")?.content).toBe("Q1 个人用户");
    }
    expect(latestEvidence(run.evidence, "prd")).toEqual(run.evidence[0]);
  });

  it("需求更新自动打开最新稿，其他刷新保留主动选择的历史稿", () => {
    const oldPrd: Artifact = { id: 2, kind: "prd", stage: "prd", title: "初稿", previewable: true };
    const newPrd: Artifact = { ...oldPrd, id: 5, title: "新稿" };
    const code: Artifact = { ...oldPrd, id: 8, kind: "code", stage: "code" };
    for (const artifacts of [[oldPrd, newPrd, code], [code, newPrd, oldPrd]]) {
      expect(selectArtifactAfterRefresh(artifacts, oldPrd.id, true)).toEqual(newPrd);
      expect(selectArtifactAfterRefresh(artifacts, oldPrd.id, false)).toEqual(oldPrd);
      expect(selectArtifactAfterRefresh(artifacts, null, false)).toEqual(newPrd);
    }
    expect(selectArtifactAfterRefresh([], null, true)).toBeNull();
  });

  it("交付包失败返回可理解的后端原因，并在请求头传鉴权", async () => {
    vi.stubGlobal("window", {});
    vi.stubGlobal("localStorage", { getItem: () => "test-token" });
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { message: "交付材料还未齐全" } }), { status: 409 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(downloadRunBundle("parent")).rejects.toThrow("交付材料还未齐全");
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe("Bearer test-token");
    expect(fetchMock.mock.calls[0][0]).not.toContain("test-token");
  });
});
