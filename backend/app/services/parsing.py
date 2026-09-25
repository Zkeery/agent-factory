"""模型输出的确定性解析 + Pydantic 结构校验。

规则：先剥 JSON 围栏，再 JSON 解析；Pydantic 强校验；
数量/内容约束不遵守记为瑕疵，不作为解析错误反复重试。
"""
from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field


class ClarifyCard(BaseModel):
    code: str
    question: str
    options: str
    recommendation: str = ""
    consequence: str = ""
    critical: bool = True


class PrdDraft(BaseModel):
    goal_users: str = ""
    input_process_output: str = ""
    main_loop: str = ""
    quality: str = ""
    delivery: str = ""
    model_cost: str = ""
    data_nonfunc: str = ""
    launch: str = ""


def strip_fence(raw: str) -> str:
    """剥掉 ```json ... ``` 围栏，兼容前后空白。"""
    text = raw.strip()
    fence = re.match(r"^```[a-zA-Z]*\s*\n?(.*?)\n?```$", text, re.DOTALL)
    if fence:
        return fence.group(1).strip()
    return text


def strip_code_fence(raw: str) -> str:
    """去掉代码块首尾可能残留的 markdown 围栏（首行 ```lang、末行 ```）。"""
    lines = raw.strip().splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def parse_json(raw: str):
    try:
        return json.loads(strip_fence(raw))
    except json.JSONDecodeError as exc:
        raise ValueError(f"非 JSON 输出：{exc}")


def parse_clarify(raw: str) -> list[dict]:
    data = parse_json(raw)
    if isinstance(data, dict):
        # 兼容 {"cards": [...]} 包裹
        data = data.get("cards", data.get("decisions", []))
    if not isinstance(data, list):
        raise ValueError("决策卡必须是数组")
    cards = [ClarifyCard(**c) for c in data if isinstance(c, dict)]
    if not cards:
        raise ValueError("决策卡为空")
    # 数量 >5 记为瑕疵，不抛错（由产品经理判断容忍度）
    return [c.model_dump() for c in cards]


def parse_prd(raw: str) -> dict:
    data = parse_json(raw)
    if not isinstance(data, dict):
        raise ValueError("PRD 必须是对象")
    prd = PrdDraft(**data)
    return prd.model_dump()


def _strip_note_lines(block: str) -> str:
    """剥掉纯非 ASCII 备注行（模型偶在代码里夹「（见上）」「同上」等）。

    判定：一行去掉所有 ASCII 后仍非空（含中文），且去掉所有非 ASCII 后为空（无任何
    Python 代码）→ 视为备注，跳过。含 # 注释、含中文字符串字面量的合法行均保留。
    """
    kept: list[str] = []
    for line in block.splitlines():
        ascii_part = "".join(ch for ch in line if ord(ch) < 128).strip()
        non_ascii_part = "".join(ch for ch in line if ord(ch) >= 128).strip()
        if non_ascii_part and not ascii_part:
            continue
        kept.append(line)
    return "\n".join(kept)


def parse_code(raw: str) -> dict[str, str]:
    """解析代码生成的三块：===APP=== / ===REQUIREMENTS=== / ===README===。

    模型有时会在块内再套一层 markdown 围栏（```python ... ```），这里统一剥掉；
    app 块再剥纯中文备注行。
    """
    blocks: dict[str, str] = {"app": "", "requirements": "", "readme": ""}
    current: str | None = None
    for line in raw.splitlines():
        s = line.strip()
        if s == "===APP===":
            current = "app"
        elif s == "===REQUIREMENTS===":
            current = "requirements"
        elif s == "===README===":
            current = "readme"
        elif current:
            blocks[current] += line + "\n"
    blocks = {k: strip_code_fence(v) for k, v in blocks.items()}
    blocks["app"] = _strip_note_lines(blocks["app"])
    if not blocks["app"] or not blocks["requirements"] or not blocks["readme"]:
        raise ValueError("代码生成三块不完整（app/requirements/readme 缺一）")
    return blocks
