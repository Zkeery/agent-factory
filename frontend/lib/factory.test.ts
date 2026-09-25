import { describe, it, expect } from "vitest";
import {
  STAGE_CN,
  STAGE_ORDER,
  deriveMessages,
  filterArtifactsForRole,
  needsWorkspaceAuth,
  canShowAlwaysAllow,
  canRetestInPlace,
  canFullRetry,
  summarizeAppStatus,
  summarizeDecisionLedger,
  pmFailureText,
  Artifact,
  Decision,
  Run,
} from "./factory";

describe("失败人话 pmFailureText", () => {
  it("已知 code 返回对应文案", () => {
    const t = pmFailureText("sandbox_blocked");
    expect(t.message).toContain("安全");
    expect(t.suggestion.length).toBeGreaterThan(0);
  });

  it("未知或空 code 走兜底", () => {
    expect(pmFailureText("").message).toBe("这次没做成功");
    expect(pmFailureText(null).message).toBe("这次没做成功");
    expect(pmFailureText("unknown_xyz").message).toBe("这次没做成功");
  });
});

describe("阶段映射", () => {
  it("STAGE_ORDER 覆盖主路径工序", () => {
    expect(STAGE_ORDER[0]).toBe("idea_submitted");
    expect(STAGE_ORDER).toContain("deploying");
    expect(STAGE_ORDER).toContain("testing");
    expect(STAGE_ORDER).toContain("awaiting_acceptance");
    expect(STAGE_ORDER).toContain("delivered");
  });

  it("每个 STAGE_ORDER 阶段都有中文名", () => {
    for (const s of STAGE_ORDER) {
      expect(STAGE_CN[s]).toBeTruthy();
    }
  });

  it("deploying 在 testing 之后", () => {
    const t = STAGE_ORDER.indexOf("testing");
    const d = STAGE_ORDER.indexOf("deploying");
    expect(d).toBeGreaterThan(t);
  });
});

describe("对话流重建 deriveMessages", () => {
  const baseRun: Run = {
    id: "1",
    idea: "做一个工具",
    status: "running",
    current_stage: "awaiting_answers",
    failure_reason: null,
    decisions: [
      {
        code: "Q1",
        question: "关键",
        options: "A/B",
        recommendation: "A",
        consequence: "x",
        answer: "A",
        status: "answered",
        is_critical: true,
      },
      {
        code: "Q2",
        question: "非关键",
        options: "A/B",
        recommendation: "B",
        consequence: "x",
        answer: "B",
        status: "answered",
        is_critical: false,
      },
    ],
    evidence: [],
    metric: null,
  };

  it("非关键决策自动回答不伪装成用户消息", () => {
    const msgs = deriveMessages(baseRun);
    const userMsgs = msgs.filter((m) => m.role === "user");
    expect(userMsgs).toHaveLength(2);
    expect(userMsgs[1].content).toBe("A");
  });

  it("失败时展示具体原因", () => {
    const failed: Run = {
      ...baseRun,
      current_stage: "failed",
      failure_reason: "代码生成格式校验失败",
    };
    const msgs = deriveMessages(failed);
    const fail = msgs.find((m) => m.content.includes("运行失败"));
    expect(fail?.content).toContain("代码生成格式校验失败");
  });

  it("代码/部署气泡用短摘要，不塞源码", () => {
    const withCode: Run = {
      ...baseRun,
      current_stage: "awaiting_acceptance",
      evidence: [
        { stage: "prd", title: "PRD", content: "# PRD", content_path: "" },
        { stage: "code", title: "代码", content: "print(1)\nprint(2)\nprint(3)", content_path: "" },
        { stage: "deploy", title: "部署", content: "uvicorn app:app\n# long script", content_path: "" },
      ],
    };
    const pm = deriveMessages(withCode, "pm");
    const pmCode = pm.find((m) => m.kind === "code");
    expect(pmCode).toBeTruthy();
    expect(pmCode?.content).toContain("产物");
    expect(pmCode?.content).not.toContain("print(1)");
    const pmDeploy = pm.find((m) => m.kind === "deploy");
    expect(pmDeploy?.content).toContain("右侧");
    expect(pmDeploy?.content).not.toContain("uvicorn");

    const dev = deriveMessages(withCode, "dev");
    const devCode = dev.find((m) => m.kind === "code");
    expect(devCode?.content).toContain("代码产物已生成");
    expect(devCode?.content).not.toContain("print(1)");
    expect(dev.find((m) => m.kind === "deploy")?.content).not.toContain("uvicorn");
  });

  it("验收气泡保留说明文案", () => {
    const withCode: Run = {
      ...baseRun,
      current_stage: "awaiting_acceptance",
      evidence: [{ stage: "prd", title: "PRD", content: "# PRD", content_path: "" }],
    };
    const msgs = deriveMessages(withCode, "pm");
    const acc = msgs.find((m) => m.kind === "acceptance");
    expect(acc?.content).toContain("验收");
  });
});

describe("产物角色过滤", () => {
  const items: Artifact[] = [
    { id: 1, kind: "prd", stage: "prd", title: "PRD", previewable: true },
    { id: 2, kind: "code", stage: "code", title: "代码", previewable: true },
    { id: 3, kind: "gate", stage: "gate", title: "闸门", previewable: true },
    { id: 4, kind: "deploy", stage: "deploy", title: "说明", previewable: true },
    { id: 5, kind: "readme", stage: "readme", title: "运行说明", previewable: true },
  ];

  it("产品经理只看 prd/deploy/readme", () => {
    const pm = filterArtifactsForRole(items, "pm");
    expect(pm.map((a) => a.kind).sort()).toEqual(["deploy", "prd", "readme"]);
  });

  it("开发者看全部", () => {
    expect(filterArtifactsForRole(items, "dev")).toHaveLength(5);
  });
});

describe("工作区授权纯函数", () => {
  const base: Run = {
    id: "1",
    idea: "x",
    status: "done",
    current_stage: "awaiting_acceptance",
    failure_reason: null,
    decisions: [],
    evidence: [],
    metric: null,
  };

  it("未授权时 write/exec 都需要确认", () => {
    expect(needsWorkspaceAuth(base, "write")).toBe(true);
    expect(needsWorkspaceAuth(base, "exec")).toBe(true);
    expect(needsWorkspaceAuth(null, "exec")).toBe(true);
  });

  it("已 exec 授权则不再要 exec 确认，仍要 write", () => {
    const r = { ...base, workspace_exec_authorized: true };
    expect(needsWorkspaceAuth(r, "exec")).toBe(false);
    expect(needsWorkspaceAuth(r, "write")).toBe(true);
  });

  it("always 时写盘与启动都不需要再确认", () => {
    const r = { ...base, workspace_always_allow: true };
    expect(needsWorkspaceAuth(r, "write")).toBe(false);
    expect(needsWorkspaceAuth(r, "exec")).toBe(false);
  });

  it("仅开发者可展示始终允许", () => {
    expect(canShowAlwaysAllow("dev")).toBe(true);
    expect(canShowAlwaysAllow("pm")).toBe(false);
  });
});



describe("预览运行态文案", () => {
  it("未运行", () => {
    expect(summarizeAppStatus(null)).toBe("未运行");
    expect(summarizeAppStatus({ running: false, url: null, port: null })).toBe("未运行");
  });

  it("运行中带端口", () => {
    expect(
      summarizeAppStatus({ running: true, url: "http://127.0.0.1:8002", port: 8002 }),
    ).toBe("运行中 · 端口 8002");
  });

  it("运行中无端口", () => {
    expect(summarizeAppStatus({ running: true, url: "http://127.0.0.1:8002", port: null })).toBe(
      "运行中",
    );
  });
});


describe("决策台账摘要", () => {
  const base: Decision = {
    code: "Q1",
    question: "用户是谁？",
    options: "A/B",
    recommendation: "A",
    consequence: "x",
    answer: null,
    status: "open",
    is_critical: true,
  };

  it("空列表", () => {
    const s = summarizeDecisionLedger([]);
    expect(s.total).toBe(0);
    expect(s.answered).toBe(0);
    expect(s.pending).toBe(0);
    expect(s.lines).toEqual([]);
  });

  it("部分已答", () => {
    const s = summarizeDecisionLedger([
      { ...base, code: "Q1", status: "answered", answer: "个人", is_critical: true },
      { ...base, code: "Q2", question: "范围", status: "open", answer: null, is_critical: false },
    ]);
    expect(s.total).toBe(2);
    expect(s.answered).toBe(1);
    expect(s.pending).toBe(1);
    expect(s.lines[0].answer).toBe("个人");
    expect(s.lines[0].critical).toBe(true);
    expect(s.lines[1].answer).toBeNull();
  });

  it("全部已答", () => {
    const s = summarizeDecisionLedger([
      { ...base, code: "Q1", status: "answered", answer: "A" },
      { ...base, code: "Q2", status: "answered", answer: "B", is_critical: false },
    ]);
    expect(s.total).toBe(2);
    expect(s.answered).toBe(2);
    expect(s.pending).toBe(0);
  });
});


describe("就地重测 / 整段重跑条件", () => {
  it("gate_failed / failed 可仅重测", () => {
    expect(canRetestInPlace("gate_failed")).toBe(true);
    expect(canRetestInPlace("failed")).toBe(true);
    expect(canRetestInPlace("cancelled")).toBe(false);
    expect(canRetestInPlace("awaiting_acceptance")).toBe(false);
  });

  it("gate_failed / failed / cancelled 可整段重跑", () => {
    expect(canFullRetry("gate_failed")).toBe(true);
    expect(canFullRetry("failed")).toBe(true);
    expect(canFullRetry("cancelled")).toBe(true);
    expect(canFullRetry("awaiting_acceptance")).toBe(false);
  });
});
