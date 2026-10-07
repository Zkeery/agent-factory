"""新生成 PRD 的最低完整性检查；历史快照不以新规则重新判失败。"""
from __future__ import annotations

import re


REQUIRED_SECTIONS = {
    "goal_users": ("用户与场景", "问题与目标", "依据与假设"),
    "input_process_output": ("输入与校验", "处理步骤", "结果与保存"),
    "main_loop": ("页面与字段", "功能规格", "状态与异常"),
    "quality": ("业务验收", "质量边界"),
    "delivery": ("本期范围", "暂不做", "后续迭代"),
    "model_cost": ("模型使用", "费用与限制", "失败处理"),
    "data_nonfunc": ("数据对象", "保存与恢复", "数据边界"),
    "launch": ("运行与交付", "账号与配置", "待确认问题"),
}
_PLACEHOLDERS = {"", "待定", "tbd", "待补充", "...", "…", "同上", "符合需求", "可用", "正常运行"}


class PrdCompletenessError(ValueError):
    """字段格式正确，但缺少开发或验收所需信息。"""


def _sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        heading = re.match(r"^\s*###\s+(.+?)\s*$", line)
        if heading:
            current = re.sub(r"^\d+(?:\.\d+)*[.、）)\s]+", "", heading.group(1)).strip()
            sections.setdefault(current, [])
        elif current:
            sections[current].append(line)
    return {key: "\n".join(lines).strip() for key, lines in sections.items()}


def generated_prd_issues(prd: dict) -> list[str]:
    """检查信息位置、行为合同与功能追踪；不以篇幅判定质量。"""
    if not isinstance(prd, dict):
        return ["PRD 必须是对象"]
    issues: list[str] = []
    for field, headings in REQUIRED_SECTIONS.items():
        value = prd.get(field)
        if not isinstance(value, str) or value.strip().lower() in _PLACEHOLDERS:
            issues.append(f"{field} 缺少具体内容")
            continue
        sections = _sections(value)
        for heading in headings:
            body = sections.get(heading, "")
            # 未确认的细节可明确写出缺口，但不能只有标题或笼统占位。
            if body.strip().lower() in _PLACEHOLDERS:
                issues.append(f"{field} 缺少「{heading}」正文")
    flow = prd.get("main_loop", "")
    acceptance = prd.get("quality", "")
    flow = flow if isinstance(flow, str) else ""
    acceptance = acceptance if isinstance(acceptance, str) else ""
    feature_ids = set(re.findall(r"\bF\d{2}\b", flow))
    referenced = set(re.findall(r"\bF\d{2}\b", acceptance))
    case_ids = set(re.findall(r"\bAC\d{2}\b", acceptance))
    if not feature_ids:
        issues.append("功能规格需要 F01 等稳定功能编号")
    if feature_ids - referenced:
        issues.append("业务验收未覆盖功能：" + ", ".join(sorted(feature_ids - referenced)))
    if referenced - feature_ids:
        issues.append("业务验收引用了未定义功能：" + ", ".join(sorted(referenced - feature_ids)))
    if len(case_ids) < 3:
        issues.append("业务验收至少需要 AC01–AC03 三个具体用例")
    for label in ("用户操作", "系统响应", "可以做", "不可以做"):
        if label not in flow:
            issues.append(f"页面与功能规格缺少「{label}」规则")
    for label in ("正常", "边界", "约束", "预期"):
        if label not in acceptance:
            issues.append(f"业务验收缺少「{label}」内容")
    if prd.get("output_type") not in {"text", "image", "video", "other"}:
        issues.append("output_type 必须反映本版主路径产物")
    return issues


def validate_generated_prd(prd: dict) -> dict:
    issues = generated_prd_issues(prd)
    if issues:
        raise PrdCompletenessError("；".join(issues))
    return prd
