"""失败原因分类与 PM 人话映射（第十六刀，PRD §3.4）。"""
from __future__ import annotations

# code -> (PM 人话, 建议动作)
PM_TEXT: dict[str, tuple[str, str]] = {
    "sandbox_blocked": ("生成的内容没过安全检查", "换个说法再试，或让开发者看看具体原因"),
    "code_syntax": ("生成的代码有问题，跑不起来", "点「整段重跑」重新生成一次"),
    "code_guard": ("生成的代码有问题，跑不起来", "点「整段重跑」重新生成一次"),
    "code_deps": ("生成的代码有问题，跑不起来", "点「整段重跑」重新生成一次"),
    "code_runtime": ("生成的代码跑不起来", "点「整段重跑」重新生成一次"),
    "gate_failed": ("生成的代码没通过自动检查", "点「整段重跑」重新生成一次"),
    "llm_key_missing": ("模型没连上，多半是 Key 没配好", "检查 .env 里的 LLM_API_KEY 后重试"),
    "llm_call_failed": ("模型没连上，多半是 Key 或网络问题", "检查 Key 和网络后重试"),
    "unknown_llm_provider": ("选的模型不认识", "换个模型或跟随全局默认再试"),
    "run_stuck": ("这一步做太久，已经被中断", "点「整段重跑」重新试一次"),
    "internal_error": ("这次没做成功", "点「整段重跑」再试，或让开发者看看原因"),
}


def classify_test_reason(reason: str) -> str:
    """把测试工序的原始 reason 归类成稳定 failure_code。"""
    r = reason or ""
    if "沙箱拒绝" in r or "禁止" in r:
        return "sandbox_blocked"
    if "语法错误" in r:
        return "code_syntax"
    if "成品护栏" in r:
        return "code_guard"
    if "requirements" in r or "缺少" in r:
        return "code_deps"
    return "code_runtime"


def pm_text(code: str) -> tuple[str, str]:
    return PM_TEXT.get(code or "", PM_TEXT["internal_error"])
