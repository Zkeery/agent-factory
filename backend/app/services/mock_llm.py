"""Mock 模型：离线占位，输出可被结构校验的固定内容，零真钱成本。

真实模型接入时替换本模块（保持相同函数签名），并走结构校验 + 有限重试。
"""
from __future__ import annotations

import re
from typing import Any

from app.services.prd_normalize import normalize_prd_fields


def _display_title(idea: str) -> str:
    """对外标题只展示原始想法首行，完整上下文仍留给生成流程。"""
    return idea.split("\n", 1)[0].strip()[:80] or "当前想法"


def _clarify_cards(idea: str) -> list[dict[str, str]]:
    """基于想法生成 3 个"必须问"关键决策卡 + 1 个非关键决策卡（演示 A+B）。"""
    return [
        {
            "code": "Q1",
            "question": f"「{_display_title(idea)}」的目标用户是谁？",
            "options": "A 个人用户 / B 企业内部 / C 对外公开",
            "recommendation": "先内部/个人验证，再考虑对外",
            "consequence": "选错用户群会影响核心任务和上线范围",
            "critical": True,
        },
        {
            "code": "Q2",
            "question": "一次完整使用要拿到什么结果？",
            "options": "A 文档 / B 代码 / C 可上线产品",
            "recommendation": "先定最小可用结果",
            "consequence": "结果边界不清会无限扩大范围",
            "critical": True,
        },
        {
            "code": "Q3",
            "question": "什么算「生成得好」？",
            "options": "A 已有数字标准 / B 待样例打分 / C 不确定",
            "recommendation": "写不出数字就先「待样例打分」",
            "consequence": "无标准就无法验收",
            "critical": True,
        },
        {
            "code": "Q4",
            "question": "界面文案风格？",
            "options": "A 简洁直白 / B 活泼俏皮 / C 正式商务",
            "recommendation": "简洁直白",
            "consequence": "仅影响观感，不影响功能范围",
            "critical": False,
        },
    ]


def generate_clarify(idea: str) -> list[dict[str, str]]:
    """生成需求澄清决策卡（≤5 个）。"""
    return _clarify_cards(idea)


def _requirement_parts(idea: str) -> list[str]:
    """Mock 中按新到旧查找明确范围；真实模型由 PRD Prompt 处理语义。"""
    parts = []
    if "需求补充与纠错" in idea:
        feedback = idea.split("需求补充与纠错", 1)[1]
        parts.extend(reversed(re.split(r"\n\d+\. ", feedback)[1:]))
    if "本次基于父版本的修改要求：\n" in idea:
        parts.append(idea.split("本次基于父版本的修改要求：\n", 1)[1].split("\n\n需求补充与纠错", 1)[0])
    parts.append(idea.split("\n\n", 1)[0])
    return parts


def _mock_output_type(idea: str, parent_output_type: str | None = None) -> str:
    parts = _requirement_parts(idea)
    # 子版本没有明确改变输出形式时继承父 PRD，不复活已被纠正的最早想法。
    if parent_output_type in {"text", "image", "video", "other"}:
        parts = parts[:-1]
    for part in parts:
        # 先识别用户明确的范围限制，不能把「不上传音视频」当作视频需求。
        text_only = re.search(r"(?:仅|只)[^，。；;\n]{0,24}(?:文字|文本|文案)", part)
        excludes_video = re.search(
            r"(?:不要|不再|无需|不需要|不生成|不做|不上传|不接收|不处理|不支持|禁止)[^，。；;\n]{0,12}(?:音视频|视频|影像)",
            part,
        )
        if text_only or excludes_video or any(word in part for word in ("纯文案", "纯文本", "视频脚本", "分镜文案")):
            return "text"
        if any(word in part.lower() for word in ("视频", "成片", "影像", "video")):
            return "video"
        if any(word in part for word in ("试衣", "试穿", "图片", "图像")):
            return "image"
        if any(word in part for word in ("摘要", "总结", "纪要", "文案", "邮件", "润色", "改写", "访谈")):
            return "text"
        if any(word in part for word in ("待办", "记账", "账本", "点单", "计算器", "购物车")):
            return "other"
    return parent_output_type or "other"


def _mock_business_task(idea: str) -> str:
    """字段和用例使用同一业务范围；普通补充不能抹掉原有业务。"""
    scope_words = ("待办", "清单", "记账", "收支", "账本", "计算器", "算式", "点单", "购物车", "奶茶", "改写", "润色", "文案", "邮件", "摘要", "总结", "纪要", "访谈", "需求", "PRD")
    return next((part for part in _requirement_parts(idea) if any(word in part for word in scope_words)), idea)


def generate_prd(idea: str, decisions: list[dict[str, Any]], source_context: dict | None = None) -> dict[str, str]:
    """离线业务示例，展示完整需求合同；不是模拟真实模型质量。"""
    from app.services.decision_context import decision_model_context
    from app.services.prd_quality import validate_generated_prd

    def cell(value: object) -> str:
        return str(value).replace("|", "\\|").replace("\n", "；").replace("\r", "")

    def section(title: str, body: str) -> str:
        return f"### {title}\n\n{body}\n\n"

    context = [decision_model_context(d) for d in decisions]
    answers = {d["code"]: (d.get("answer") or "未答") for d in context}
    current_task = _requirement_parts(idea)[0].strip()
    business_task = _mock_business_task(idea)
    output_type = _mock_output_type(idea, (source_context or {}).get("prd", {}).get("output_type"))
    labels = {"text": "文本结果", "image": "图片", "video": "可播放视频", "other": "交互工具的操作结果"}
    cases = generate_acceptance_scenarios(idea, {"output_type": output_type})
    decisions_text = "\n".join(
        f"- 决策 {d['code']}：{d['question'] or d['code']} → {d['answer'] or '未回答'}"
        + (f"（待确认：{d['answer_gap']}）" if d.get("answer_gap") else "")
        for d in context
    ) or "- 尚无决策记录，以下操作规则为建议，待确认。"
    # 根据业务选择字段和结果，避免把工厂的澄清/开发阶段塞入成品。
    if any(word in business_task for word in ("待办", "事项清单", "todo")):
        fields = "| 事项名称 | 文本 | 是 | 无 | 去除首尾空白后不能为空，长度上限待确认 |\n| 完成状态 | 布尔 | 修改时 | 未完成 | 只能修改选中的事项 |"
        result = "事项列表展示名称和完成状态；新增后为未完成，完成指定事项不会改变其他记录。"
        object_fields = "事项：标识、名称、完成状态。记录来源为用户输入；是否需要持久化待确认。"
    elif any(word in business_task for word in ("记账", "收支", "账本")):
        fields = "| 收支类型 | 收入/支出 | 是 | 无 | 只能选择一种类型 |\n| 金额 | 数字 | 是 | 无 | 非数字不能保存，允许范围待确认 |\n| 说明 | 文本 | 待确认 | 无 | 与该笔记录关联 |"
        result = "输出收支明细、收入合计、支出合计和余额；金额计算以有效保存记录为依据。"
        object_fields = "账目：标识、收支类型、金额、说明。合计为记录的计算结果，不作为独立输入。"
    elif any(word in business_task for word in ("计算器", "算式")):
        fields = "| 算式 | 文本/按钮输入 | 是 | 空 | 不合法表达式显示可读错误，不执行任意代码 |"
        result = "显示当前算式与计算结果；按等号后计算，新算式如何开始由验收用例约定。"
        object_fields = "算式草稿和最近结果；本期是否保留计算历史待确认。"
    else:
        fields = "| 任务材料 | 与主路径匹配的文本或素材 | 是 | 无 | 未提供必要材料时提示补充；具体格式待确认 |\n| 结果约束 | 文本 | 否 | 沿用已确认要求 | 用户填写的约束应进入处理过程 |"
        result = f"主路径交付{labels[output_type]}；输出应对应用户输入和已确认约束，不能用示例内容伪装真实结果。"
        object_fields = "任务材料、结果约束、输出结果；图片或视频的素材格式及存储方式须另行确认。"
    feature_rows = []
    acceptance_rows = []
    for i, case in enumerate(cases, 1):
        fid = f"F{i:02d}"
        feature_rows.append(
            f"| {fid} | {cell(case['title'])} | P0（建议） | 主操作页 | {cell(case['input'])} | {cell(case['expected_output'])} | 无效输入不得提交为成功，保留可修正输入 |"
        )
        kind = ("正常任务", "边界/不同输入", "明确约束")[min(i - 1, 2)]
        acceptance_rows.append(
            f"| AC{i:02d} | {fid} | {kind} | {cell(case['input'])} | {cell(case['expected_output'])} |"
        )
    parent_note = ""
    if source_context:
        parent_note = "\n- 子版本：在父版本功能基础上修改，未要求改变的功能保留；本次具体改动以最新要求为准，Mock 不能替代逐项核对。\n- 父版本试用观察：" + str(source_context.get("acceptance_results", []))
    raw = {
        "goal_users": (
            section("用户与场景", f"本次业务任务：{current_task}\n\n目标用户（决策 Q1：{answers.get('Q1', '未答')}）；在需要完成这项任务时，从已有材料或操作开始，获得{labels[output_type]}。")
            + section("问题与目标", f"围绕「{_display_title(idea)}」明确输入、操作和结果。建议本期目标：用户能按下文场景完成任务，并能识别输入不足或处理失败。")
            + section("依据与假设", "**Mock 演示草稿：功能表和用例是可编辑示例，需人工核对，不代表实际用户调研或模型效果。**\n\n" + decisions_text)
        ),
        "input_process_output": (
            section("输入与校验", "| 字段 | 类型/格式 | 必填 | 默认值 | 校验与错误 |\n| --- | --- | --- | --- | --- |\n" + fields)
            + section("处理步骤", "1. 用户在主操作页填写或选择任务材料。\n2. 先校验必要输入，校验失败显示原因，保留可修改内容。\n3. 执行选定业务操作，依据实际输入形成结果。\n4. 展示结果或可读失败原因，由用户核对后决定继续操作。\n\n最新范围依据：" + current_task)
            + section("结果与保存", result + "\n\n保存/复制/导出方式：建议按主路径提供适用的结果获取入口；是否长期保留和允许哪些格式待确认。")
        ),
        "main_loop": (
            section("页面与字段", "| 页面 | 入口 | 职责 | 关键字段/组件 | 下一步 |\n| --- | --- | --- | --- | --- |\n| 主操作页 | 打开成品 | 完成本期业务任务 | 下文输入字段、操作按钮、结果区和错误提示 | 核对结果或修正输入 |")
            + section("功能规格", "以下功能为业务示例提案，优先级待人工确认。\n\n| 功能 | 行为 | 优先级 | 入口 | 用户操作 | 系统响应 | 异常与边界 |\n| --- | --- | --- | --- | --- | --- | --- |\n" + "\n".join(feature_rows))
            + section("状态与异常", "建议以下最小状态规则，不额外建立后台任务系统：\n\n| 状态 | 用户看到什么 | 可以做 | 不可以做 |\n| --- | --- | --- | --- |\n| 空态/编辑中 | 输入区与必要提示 | 填写材料、调整约束 | 把空材料作为成功结果 |\n| 提交处理 | 当前操作的处理反馈；同步操作可瞬时完成 | 等待，保留输入 | 对同一操作重复提交产生重复结果 |\n| 成功 | 实际结果和核对入口 | 核对或开始下一次操作 | 声称未执行的操作已成功 |\n| 失败 | 具体原因与原有可编辑内容 | 修正后重新提交 | 用示例结果掩盖失败 |")
        ),
        "quality": (
            section("业务验收", "以下输入是测试材料，不是调研数据；请在构建前改为适合自己业务的样例。\n\n| 编号 | 功能 | 类型 | 输入或操作 | 可观察的预期 |\n| --- | --- | --- | --- | --- |\n" + "\n".join(acceptance_rows))
            + section("质量边界", "自动检查只判断工程可运行，业务结果仍需人工按场景核对。不得编造输入中不存在的事实，不得将未知信息写成已确认结论。视觉、措辞等容忍度待样例打分；本轮没有真实模型质量成绩。" + parent_note)
        ),
        "delivery": (
            section("本期范围", "建议 P0：F01、F02、F03，以及主操作页、输入校验、结果和错误反馈；对应业务内容以本次输入为准。交付源码、依赖、使用说明、PRD 与场景记录。" + parent_note)
            + section("暂不做", "未明确要求的账号、支付、协作、复杂权限和外部接入不自动进入本期。最新范围：" + current_task)
            + section("后续迭代", "按实际试用问题排序；先修正核心任务与验收缺口，再讨论保存、导出或其他增强。未约定开发日期和人员。")
        ),
        "model_cost": (
            section("模型使用", "当前用本地 Mock 生成示例需求，不调用真实模型。成品是否需要运行时 AI、使用哪家模型，应依据业务任务及用户决定另行确认。")
            + section("费用与限制", "Mock 本身无模型费用；真实运行时模型或其他服务的预算、计费方式与限额待确认，不预设数额。")
            + section("失败处理", "缺少配置或外部服务不可用时明确提示，保留输入；不把演示内容当作真实接口结果。无外部依赖的业务按功能表校验输入。")
        ),
        "data_nonfunc": (
            section("数据对象", object_fields)
            + section("保存与恢复", "建议保留当前操作草稿与已生成结果；具体存储介质、期限和重启恢复要求待确认。本地未上传的文件不能承诺刷新后自动恢复。")
            + section("数据边界", "仅处理本任务明确提供的材料，不虚构资料来源。部署地区、第三方传输和隐私要求尚未确认，不能承诺国内部署或数据不出境。")
        ),
        "launch": (
            section("运行与交付", "当前工厂交付本地可运行小应用及源码材料；本份 Mock 需求是建议合同，成品实际行为仍须人工核对。主路径产物：" + labels[output_type])
            + section("账号与配置", "是否需要业务账号、外部服务和上线环境须依用户明确要求确认；不默认加入注册或管理员入口。")
            + section("待确认问题", "核对示例功能是否符合真实任务、保存/导出方式、输入限制、账号与外部接入、预算和质量容忍度；已有明确答案的项目不必重问。\n\n已记录的决定：\n" + decisions_text)
        ),
        "output_type": output_type,
    }
    return validate_generated_prd(normalize_prd_fields(raw))


def generate_acceptance_scenarios(idea: str, prd: dict) -> list[dict]:
    """离线示例场景；使用具体业务输入，供用户在 PRD 确认前改成自己的样例。"""
    task = idea.split("\n", 1)[0].strip()[:100]
    idea = _mock_business_task(idea)
    if any(word in idea for word in ("待办", "事项清单", "todo")):
        cases = [
            ("新增事项", "添加「周五发送产品周报」", "列表中出现该事项，初始为未完成"),
            ("完成指定事项", "添加「整理访谈」，再勾选完成", "整理访谈标为已完成，其他事项状态不变"),
            ("拒绝空事项", "输入只有空格的事项并提交", "不新增空白事项，显示需要填写内容的提示"),
        ]
    elif any(word in idea for word in ("记账", "收支", "账本")):
        cases = [
            ("计算收支", "记录收入100元、午餐支出30元", "收入100、支出30、余额70，明细保留午餐"),
            ("继续记账", "在上述记录后添加交通支出12.5元", "支出合计42.5、余额57.5，原有记录仍在"),
            ("金额校验", "金额填写abc并保存", "提示金额无效，不产生错误账目"),
        ]
    elif any(word in idea for word in ("计算器", "算式")):
        cases = [
            ("四则计算", "输入5×7并按=", "按=后显示35，输入途中不提前求值"),
            ("括号优先级", "输入(2+3)×4并按=", "显示20"),
            ("重新开始算式", "2+3按=后输入8", "新算式为8，不拼接为58"),
        ]
    elif any(word in idea for word in ("点单", "购物车", "奶茶")):
        cases = [
            ("菜单加购", "从菜单选一个商品加入购物车", "购物车出现所选商品，单价与菜单一致"),
            ("数量与合计", "把同一商品数量改为2", "数量为2，合计等于菜单单价乘2"),
            ("移除商品", "将购物车中的商品移除", "该商品不再计入合计，空车不能生成有效订单"),
        ]
    elif any(word in idea for word in ("改写", "润色", "文案", "邮件")):
        cases = [
            ("保留事实改写", "请礼貌改写：明天15点前发我报告，项目预算为2000元。", "语气礼貌，仍保留明天15点和2000元，不捏造新承诺"),
            ("遵守长度约束", "把“我们推出了一款面向产品经理的访谈整理工具”改写为20字内标题", "标题不超过20字，保留产品经理与访谈整理主题"),
            ("空文本处理", "不填写原文直接提交", "提示补充原文，不生成与需求无关的内容"),
        ]
    elif any(word in idea for word in ("摘要", "总结", "纪要", "访谈", "需求", "PRD")):
        cases = [
            ("提取具体事实", "周会：小李负责登录页，周五交付；支付功能因接口延期两天。", "结果保留小李、登录页、周五和支付延期两天，不新增负责人或日期"),
            ("区分确定与待定", "访谈：用户每周花2小时整理表格，愿不愿付费还没问。", "保留每周2小时，付费意愿标为未知，不写成已验证愿付费"),
            ("识别缺失信息", "帮我处理这条需求，但我还没提供任何内容。", "请求补充任务所需材料，不编造访谈、调研或业务结论"),
        ]
    else:
        cases = [
            (f"完成{task[:24]}任务", f"按「{task}」处理示例：用户小林每周花2小时手工整理资料，希望缩短准备时间。", f"围绕「{task}」给出对应产物，保留小林、每周2小时与缩短准备时间这些输入事实"),
            ("处理带约束的同类输入", f"按「{task}」处理：本次只供个人使用，预算0元，结果限3条。", "输出遵守个人使用、0元、最多3条约束，不扩展成团队或付费方案"),
            ("缺少任务材料", "输入留空后提交", "提示补充必要输入，不生成虚构业务结果"),
        ]
    return [
        {"id": f"scenario-{i + 1}", "title": title, "input": value, "expected_output": expected}
        for i, (title, value, expected) in enumerate(cases)
    ]


def _safe_comment(idea: str) -> str:
    return idea.replace("\r", " ").replace("\n", " ").strip() or "未命名想法"


def _is_video_idea(idea: str, prd: dict[str, str] | None = None) -> bool:
    """想法或 PRD 含视频类关键词，且目标是生成影像（非纯脚本写作工具）。"""
    if prd and prd.get("output_type"):
        return prd["output_type"] == "video"
    blob = (idea or "").lower()
    if prd:
        blob += " " + " ".join(str(v) for v in prd.values()).lower()
    keys = ("视频", "短视频", "video", "成片", "mp4", "影像")
    if not any(k.lower() in blob if k.isascii() else k in blob for k in keys):
        return False
    # 排除「只写脚本/提示词」专用表述占主导且无生成影像意图时仍偏保守：有「视频」即视为视频类
    script_only = ("脚本写作", "分镜文案工具", "提示词生成器")
    if any(s in (idea or "") for s in script_only) and "生成视频" not in (idea or "") and "短视频" not in (idea or ""):
        return False
    return True



def _is_tryon_idea(idea: str, prd: dict[str, str] | None = None) -> bool:
    """想法或 PRD 含试衣/试穿/换装等，目标是出上身预览图。"""
    if prd and prd.get("output_type"):
        return prd["output_type"] == "image"
    blob = (idea or "").lower()
    if prd:
        blob += " " + " ".join(str(v) for v in prd.values()).lower()
    keys = (
        "试衣", "试穿", "换装", "虚拟试穿", "try-on", "tryon", "virtual try-on",
        "上身效果", "看上身",
    )
    return any(k.lower() in blob if k.isascii() else k in blob for k in keys)


def _demo_app_source(title: str) -> str:
    """拼出可演示的 app.py 源码；HTML 用 r\"\"\"，避免护栏误杀。"""
    parts = [
        "# 本文件由 Agent造物坊 mock 生成（最小可演示 AI 应用）。",
        f"# 想法：{title}",
        "import os",
        "from fastapi import FastAPI",
        "from fastapi.responses import HTMLResponse",
        "from pydantic import BaseModel",
        "",
        "app = FastAPI()",
        "",
        "HOME_HTML = r\"\"\"<!DOCTYPE html>",
        "<html lang=\"zh-CN\">",
        "<head>",
        "<meta charset=\"utf-8\"/>",
        f"<title>{title}</title>",
        "<style>",
        "body { font-family: system-ui, sans-serif; max-width: 640px; margin: 2rem auto; padding: 0 1rem; }",
        "input { width: 70%; padding: 0.4rem; }",
        "button { padding: 0.4rem 0.8rem; margin-left: 0.4rem; }",
        "pre { background: #f4f4f5; padding: 0.8rem; border-radius: 6px; white-space: pre-wrap; }",
        ".hint { color: #666; font-size: 0.9rem; }",
        "</style>",
        "</head>",
        "<body>",
        f"<h1>{title}</h1>",
        "<p class=\"hint\">本地演示页（mock）。无 DEEPSEEK_API_KEY 时 /generate 仍返回 HTTP 200 本地结果。</p>",
        "<input id=\"inp\" placeholder=\"输入一句话，例如：你好\"/>",
        "<button id=\"btn\" type=\"button\">发送</button>",
        "<pre id=\"out\">等待发送…</pre>",
        "<script>",
        "(function () {",
        "  var inp = document.getElementById(\"inp\");",
        "  var btn = document.getElementById(\"btn\");",
        "  var out = document.getElementById(\"out\");",
        "  btn.addEventListener(\"click\", function () {",
        "    var text = (inp.value || \"\").trim() || \"你好\";",
        "    out.textContent = \"请求中…\";",
        "    fetch(\"/generate\", {",
        "      method: \"POST\",",
        "      headers: {\"Content-Type\": \"application/json\"},",
        "      body: JSON.stringify({input: text})",
        "    }).then(function (r) { return r.json().then(function (data) {",
        "      return { ok: r.ok, status: r.status, data: data };",
        "    }); }).then(function (res) {",
        "      var data = res.data || {};",
        "      out.textContent = (data.result != null ? data.result : JSON.stringify(data))",
        "        + \"\\n(HTTP \" + res.status + \")\";",
        "    }).catch(function (err) {",
        "      out.textContent = \"失败: \" + err;",
        "    });",
        "  });",
        "})();",
        "</script>",
        "</body>",
        "</html>",
        '"""',
        "",
        "",
        "class Req(BaseModel):",
        "    input: str",
        "",
        "",
        "@app.get(\"/\", response_class=HTMLResponse)",
        "def home():",
        "    return HOME_HTML",
        "",
        "",
        '@app.post("/generate")',
        "def generate(req: Req):",
        '    """无 Key → HTTP 200 本地回落；有 Key 可走 OpenAI 兼容，失败仍本地回落（禁止故意 5xx）。"""',
        '    text = (req.input or "").strip() or "（空输入）"',
        '    local = {"result": f"（本地回落）已收到：{text}"}',
        '    key = os.getenv("DEEPSEEK_API_KEY")',
        "    if not key:",
        "        return local",
        "    try:",
        "        from openai import OpenAI",
        "",
        "        client = OpenAI(",
        "            api_key=key,",
        '            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),',
        "        )",
        "        resp = client.chat.completions.create(",
        '            model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),',
        '            messages=[{"role": "user", "content": text}],',
        "        )",
        '        content = (resp.choices[0].message.content or "").strip()',
        '        return {"result": content or local["result"]}',
        "    except Exception:",
        "        return local",
        "",
    ]
    return "\n".join(parts)


def _video_app_source(title: str) -> str:
    """视频类 idea：表单 → 本地合成演示片 → HTML5 <video> 可播。"""
    b64_chunks = [
        "AAAAIGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDEAAAAIZnJlZQAABjBtZGF0AAACrgYF",
        "//+q3EXpvebZSLeWLNgg2SPu73gyNjQgLSBjb3JlIDE2NSByMzIyMiBiMzU2MDVhIC0gSC4y",
        "NjQvTVBFRy00IEFWQyBjb2RlYyAtIENvcHlsZWZ0IDIwMDMtMjAyNSAtIGh0dHA6Ly93d3cu",
        "dmlkZW9sYW4ub3JnL3gyNjQuaHRtbCAtIG9wdGlvbnM6IGNhYmFjPTEgcmVmPTMgZGVibG9j",
        "az0xOjA6MCBhbmFseXNlPTB4MzoweDExMyBtZT1oZXggc3VibWU9NyBwc3k9MSBwc3lfcmQ9",
        "MS4wMDowLjAwIG1peGVkX3JlZj0xIG1lX3JhbmdlPTE2IGNocm9tYV9tZT0xIHRyZWxsaXM9",
        "MSA4eDhkY3Q9MSBjcW09MCBkZWFkem9uZT0yMSwxMSBmYXN0X3Bza2lwPTEgY2hyb21hX3Fw",
        "X29mZnNldD0tMiB0aHJlYWRzPTcgbG9va2FoZWFkX3RocmVhZHM9MSBzbGljZWRfdGhyZWFk",
        "cz0wIG5yPTAgZGVjaW1hdGU9MSBpbnRlcmxhY2VkPTAgYmx1cmF5X2NvbXBhdD0wIGNvbnN0",
        "cmFpbmVkX2ludHJhPTAgYmZyYW1lcz0zIGJfcHlyYW1pZD0yIGJfYWRhcHQ9MSBiX2JpYXM9",
        "MCBkaXJlY3Q9MSB3ZWlnaHRiPTEgb3Blbl9nb3A9MCB3ZWlnaHRwPTIga2V5aW50PTI1MCBr",
        "ZXlpbnRfbWluPTI1IHNjZW5lY3V0PTQwIGludHJhX3JlZnJlc2g9MCByY19sb29rYWhlYWQ9",
        "NDAgcmM9Y3JmIG1idHJlZT0xIGNyZj0yMy4wIHFjb21wPTAuNjAgcXBtaW49MCBxcG1heD02",
        "OSBxcHN0ZXA9NCBpcF9yYXRpbz0xLjQwIGFxPTE6MS4wMACAAAAAQWWIhAA7//7jq/gU2FBU",
        "dEzFKP6FtGNPzxSXbPITNxyv/gd9NWAALGGW9CnGTJVG0AEsAAASwM2GMJqpyTz6+ldRAAAA",
        "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",
        "ABxkYXRhAAAAAQAAAABMYXZmNjMuMS4xMDI=",
    ]
    b64_joined = "\n".join(f'    "{c}"' for c in b64_chunks)
    parts = [
        "# 本文件由 Agent造物坊 mock 生成（视频类：本地合成可播短片）。",
        f"# 想法：{title}",
        "import base64",
        "import os",
        "import shutil",
        "import subprocess",
        "from pathlib import Path",
        "",
        "from fastapi import FastAPI",
        "from fastapi.responses import FileResponse, HTMLResponse",
        "from pydantic import BaseModel",
        "",
        "app = FastAPI()",
        "OUT_DIR = Path(__file__).resolve().parent / \"_demo_clips\"",
        "OUT_DIR.mkdir(exist_ok=True)",
        "CLIP_PATH = OUT_DIR / \"demo.mp4\"",
        "",
        "# 内置可播短片（约 2s）；无 ffmpeg 时回落此字节",
        "MINI_MP4_B64 = (",
    ]
    parts.extend(f'        "{c}"' for c in b64_chunks)
    parts.append(")")
    parts.extend([
        "",
        "HOME_HTML = r\"\"\"<!DOCTYPE html>",
        "<html lang=\"zh-CN\">",
        "<head>",
        "<meta charset=\"utf-8\"/>",
        f"<title>{title} · 生成视频</title>",
        "<style>",
        "body { font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; }",
        "input { width: 70%; padding: 0.4rem; }",
        "button { padding: 0.4rem 0.8rem; margin-left: 0.4rem; }",
        "video { width: 100%; max-height: 360px; background: #111; border-radius: 8px; margin-top: 1rem; }",
        ".hint { color: #666; font-size: 0.9rem; }",
        "pre { background: #f4f4f5; padding: 0.8rem; border-radius: 6px; white-space: pre-wrap; }",
        "</style>",
        "</head>",
        "<body>",
        f"<h1>{title}</h1>",
        "<p class=\"hint\">这是「生成视频」本地演示：无云端视频 API Key 时合成<strong>本地演示片</strong>（可播放短视频，不是提示词）。</p>",
        "<input id=\"inp\" placeholder=\"片头标题，例如：我的短片\"/>",
        "<button id=\"btn\" type=\"button\">生成视频</button>",
        "<pre id=\"out\">等待生成…</pre>",
        "<video id=\"player\" controls playsinline></video>",
        "<p><a id=\"dl\" href=\"/download.mp4\" download=\"demo.mp4\">下载 mp4</a></p>",
        "<script>",
        "(function () {",
        "  var inp = document.getElementById(\"inp\");",
        "  var btn = document.getElementById(\"btn\");",
        "  var out = document.getElementById(\"out\");",
        "  var player = document.getElementById(\"player\");",
        "  btn.addEventListener(\"click\", function () {",
        "    var text = (inp.value || \"\").trim() || \"本地演示片\";",
        "    out.textContent = \"合成中…\";",
        "    fetch(\"/generate\", {",
        "      method: \"POST\",",
        "      headers: {\"Content-Type\": \"application/json\"},",
        "      body: JSON.stringify({input: text})",
        "    }).then(function (r) { return r.json().then(function (data) {",
        "      return { ok: r.ok, status: r.status, data: data };",
        "    }); }).then(function (res) {",
        "      var data = res.data || {};",
        "      out.textContent = (data.result != null ? data.result : JSON.stringify(data))",
        "        + \"\\n(HTTP \" + res.status + \")\";",
        "      var url = data.video_url || \"/download.mp4\";",
        "      player.src = url + (url.indexOf(\"?\") >= 0 ? \"&\" : \"?\") + \"t=\" + Date.now();",
        "      player.load();",
        "    }).catch(function (err) {",
        "      out.textContent = \"失败: \" + err;",
        "    });",
        "  });",
        "})();",
        "</script>",
        "</body>",
        "</html>",
        '"""',
        "",
        "",
        "def _write_demo_clip(title_text: str) -> Path:",
        '    """优先 ffmpeg；否则回落内置可播 mp4；可选 Pillow 标题帧。"""',
        "    (OUT_DIR / \"title.txt\").write_text(title_text, encoding=\"utf-8\")",
        "    label = \"\".join(c if (c.isalnum() or c in \" _-\") else \" \" for c in (title_text or \"本地演示片\"))[:40]",
        "    ffmpeg = shutil.which(\"ffmpeg\")",
        "    if ffmpeg:",
        "        try:",
        "            subprocess.run(",
        "                [",
        "                    ffmpeg, \"-y\",",
        "                    \"-f\", \"lavfi\", \"-i\", \"color=c=0x1e40af:s=640x360:d=3\",",
        "                    \"-vf\", f\"drawtext=text={label}:fontsize=36:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2\",",
        "                    \"-c:v\", \"libx264\", \"-pix_fmt\", \"yuv420p\", \"-t\", \"3\", \"-an\",",
        "                    str(CLIP_PATH),",
        "                ],",
        "                check=True,",
        "                capture_output=True,",
        "                timeout=30,",
        "            )",
        "            if CLIP_PATH.exists() and CLIP_PATH.stat().st_size > 100:",
        "                return CLIP_PATH",
        "        except Exception:",
        "            pass",
        "    try:",
        "        from PIL import Image, ImageDraw",
        "",
        "        img = Image.new(\"RGB\", (640, 360), color=(30, 64, 175))",
        "        draw = ImageDraw.Draw(img)",
        "        draw.text((40, 160), (title_text or \"本地演示片\")[:40], fill=(255, 255, 255))",
        "        img.save(OUT_DIR / \"frame.png\")",
        "    except Exception:",
        "        pass",
        "    CLIP_PATH.write_bytes(base64.b64decode(MINI_MP4_B64))",
        "    return CLIP_PATH",
        "",
        "",
        "class Req(BaseModel):",
        "    input: str",
        "",
        "",
        "@app.get(\"/\", response_class=HTMLResponse)",
        "def home():",
        "    return HOME_HTML",
        "",
        "",
        '@app.get("/download.mp4")',
        "def download_mp4():",
        "    if not CLIP_PATH.exists():",
        '        _write_demo_clip("本地演示片")',
        '    return FileResponse(str(CLIP_PATH), media_type="video/mp4", filename="demo.mp4")',
        "",
        "",
        '@app.post("/generate")',
        "def generate(req: Req):",
        '    """无云端视频 Key：本地合成演示片，HTTP 200；禁止只返回提示词。"""',
        '    text = (req.input or "").strip() or "本地演示片"',
        "    path = _write_demo_clip(text)",
        "    return {",
        '        "result": f"已生成本地演示片（标题：{text}），可在页面播放或下载。",',
        '        "video_url": "/download.mp4",',
        '        "path": str(path),',
        "    }",
        "",
    ])
    return "\n".join(parts)



def _tryon_app_source(title: str) -> str:
    """试衣类 idea：可选上传 + 衣服描述 → Pillow 本地演示图 → <img> 展示。"""
    parts = [
        "# 本文件由 Agent造物坊 mock 生成（试衣类：本地合成可查看预览图）。",
        f"# 想法：{title}",
        "import base64",
        "import io",
        "import os",
        "from pathlib import Path",
        "",
        "from fastapi import FastAPI, File, Form, UploadFile",
        "from fastapi.responses import FileResponse, HTMLResponse",
        "from pydantic import BaseModel",
        "",
        "app = FastAPI()",
        'OUT_DIR = Path(__file__).resolve().parent / "_demo_previews"',
        "OUT_DIR.mkdir(exist_ok=True)",
        'PREVIEW_PATH = OUT_DIR / "preview.png"',
        "",
        'HOME_HTML = r"""<!DOCTYPE html>',
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="utf-8"/>',
        f"<title>{title} · 试穿预览</title>",
        "<style>",
        "body { font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; }",
        "input[type=text] { width: 70%; padding: 0.4rem; }",
        "button { padding: 0.4rem 0.8rem; margin-left: 0.4rem; }",
        "img.result { max-width: 100%; border-radius: 8px; margin-top: 1rem; background: #f4f4f5; }",
        ".hint { color: #666; font-size: 0.9rem; }",
        "pre { background: #f4f4f5; padding: 0.8rem; border-radius: 6px; white-space: pre-wrap; }",
        "</style>",
        "</head>",
        "<body>",
        f"<h1>{title}</h1>",
        '<p class="hint">这是「试穿预览」本地演示：无云端图像 API Key 时用 Pillow 合成<strong>本地演示图</strong>（可查看预览图，不是换装方案/提示词）。</p>',
        '<p><label>全身照（可选） <input id="photo" type="file" accept="image/*"/></label></p>',
        '<input id="inp" placeholder="想试穿的衣服，例如：白色衬衫 + 蓝色牛仔裤"/>',
        '<button id="btn" type="button">生成试穿预览</button>',
        '<pre id="out">等待生成…</pre>',
        '<img id="preview" class="result" alt="试穿预览"/>',
        '<p><a id="dl" href="/preview.png" download="preview.png">下载预览图</a></p>',
        "<script>",
        "(function () {",
        '  var inp = document.getElementById("inp");',
        '  var btn = document.getElementById("btn");',
        '  var out = document.getElementById("out");',
        '  var preview = document.getElementById("preview");',
        '  btn.addEventListener("click", function () {',
        '    var text = (inp.value || "").trim() || "白色衬衫";',
        '    out.textContent = "合成中…";',
        '    fetch("/generate", {',
        '      method: "POST",',
        '      headers: {"Content-Type": "application/json"},',
        "      body: JSON.stringify({input: text})",
        "    }).then(function (r) { return r.json().then(function (data) {",
        "      return { ok: r.ok, status: r.status, data: data };",
        "    }); }).then(function (res) {",
        "      var data = res.data || {};",
        '      out.textContent = (data.result != null ? data.result : JSON.stringify(data))',
        '        + "\\n(HTTP " + res.status + ")";',
        "      if (data.image_base64) {",
        '        preview.src = "data:image/png;base64," + data.image_base64;',
        "      } else {",
        '        var url = data.preview_url || "/preview.png";',
        '        preview.src = url + (url.indexOf("?") >= 0 ? "&" : "?") + "t=" + Date.now();',
        "      }",
        "    }).catch(function (err) {",
        '      out.textContent = "失败: " + err;',
        "    });",
        "  });",
        "})();",
        "</script>",
        "</body>",
        "</html>",
        '"""',
        "",
        "",
        "def _compose_demo_preview(outfit: str) -> tuple[Path, str]:",
        '    """Pillow 本地演示图；返回路径与 base64。"""',
        "    from PIL import Image, ImageDraw",
        "",
        '    img = Image.new("RGB", (640, 800), color=(245, 245, 247))',
        "    draw = ImageDraw.Draw(img)",
        "    # 简易人物剪影",
        "    draw.ellipse((270, 40, 370, 140), fill=(220, 190, 170))",
        "    draw.rectangle((250, 150, 390, 420), fill=(60, 90, 160))  # 上衣色块",
        "    draw.rectangle((260, 420, 380, 700), fill=(40, 40, 50))  # 下装色块",
        '    label = (outfit or "本地演示图")[:36]',
        '    draw.text((40, 720), f"本地演示图 · {label}", fill=(30, 30, 30))',
        "    buf = io.BytesIO()",
        '    img.save(buf, format="PNG")',
        "    raw = buf.getvalue()",
        "    PREVIEW_PATH.write_bytes(raw)",
        '    return PREVIEW_PATH, base64.b64encode(raw).decode("ascii")',
        "",
        "",
        "class Req(BaseModel):",
        '    input: str = ""',
        "",
        "",
        '@app.get("/", response_class=HTMLResponse)',
        "def home():",
        "    return HOME_HTML",
        "",
        "",
        '@app.get("/preview.png")',
        "def preview_png():",
        "    if not PREVIEW_PATH.exists():",
        '        _compose_demo_preview("本地演示图")',
        '    return FileResponse(str(PREVIEW_PATH), media_type="image/png", filename="preview.png")',
        "",
        "",
        '@app.post("/generate")',
        "def generate(req: Req):",
        '    """无云端图像 Key：Pillow 本地演示图，HTTP 200；禁止只返回换装文案。"""',
        '    text = (req.input or "").strip() or "白色衬衫"',
        "    path, b64 = _compose_demo_preview(text)",
        "    return {",
        '        "result": f"已生成本地演示图（试穿：{text}），可在页面查看。",',
        '        "image_base64": b64,',
        '        "preview_url": "/preview.png",',
        '        "path": str(path),',
        "    }",
        "",
    ]
    return "\n".join(parts)


def generate_code(idea: str, prd: dict[str, str], source_context: dict | None = None) -> dict[str, str]:
    """生成最小可演示 FastAPI 应用；试衣/视频类分别返回本地出图/出片模板。"""
    if source_context and source_context.get("files", {}).get("app.py"):
        files = source_context["files"]
        # Mock 只验证版本链与传参，不冒充完成任意业务修改。
        note = "Mock 子版本：保留父代码，尚未执行真实模型业务修改。修改要求：" + _safe_comment(idea)
        return {
            "app": files["app.py"].rstrip() + "\n\n# " + note + "\n",
            "requirements": files.get("requirements.txt", "fastapi\nuvicorn\n"),
            "readme": files.get("README.md", "") + "\n\n## Mock 版本说明\n\n" + note + "\n",
        }
    title = _safe_comment(idea)
    if _is_tryon_idea(idea, prd):
        app = _tryon_app_source(title)
        readme = (
            f"# {title}\n\n"
            "这是「试穿预览」本地演示成品：主路径产出**可查看预览图**（`<img>` + `image_base64` / `/preview.png`），"
            "不是换装方案/提示词。无云端图像 API Key 时用 Pillow 合成本地演示图。\n\n"
            "## 启动\n\n"
            "```sh\n"
            "pip install -r requirements.txt\n"
            "uvicorn app:app --port 8000\n"
            "```\n\n"
            "浏览器打开 http://127.0.0.1:8000/ ，输入衣服描述后点「生成试穿预览」即可查看图片。\n\n"
            "## 调用\n\n"
            "```sh\n"
            "curl -X POST http://127.0.0.1:8000/generate -H 'Content-Type: application/json' -d '{\"input\":\"白色衬衫\"}'\n"
            "curl -OJ http://127.0.0.1:8000/preview.png\n"
            "```\n"
        )
        return {
            "app": app,
            "requirements": "fastapi\nuvicorn\npillow\npython-multipart\n",
            "readme": readme,
        }
    if _is_video_idea(idea, prd):
        app = _video_app_source(title)
        readme = (
            f"# {title}\n\n"
            "这是「生成视频」本地演示成品：主路径产出**可播放短视频**（HTML5 `<video>` + `/download.mp4`），"
            "不是提示词/分镜文案。无云端视频 API Key 时写入内置最小 mp4（本地演示片）；"
            "可选安装 `pillow` 生成标题静帧预览图。系统若有 ffmpeg 可自行替换成更长成片。\n\n"
            "## 启动\n\n"
            "```sh\n"
            "pip install -r requirements.txt\n"
            "uvicorn app:app --port 8000\n"
            "```\n\n"
            "浏览器打开 http://127.0.0.1:8000/ ，输入片头标题后点「生成视频」即可播放。\n\n"
            "## 调用\n\n"
            "```sh\n"
            "curl -X POST http://127.0.0.1:8000/generate -H 'Content-Type: application/json' -d '{\"input\":\"片头\"}'\n"
            "curl -OJ http://127.0.0.1:8000/download.mp4\n"
            "```\n"
        )
        return {
            "app": app,
            "requirements": "fastapi\nuvicorn\npillow\n",
            "readme": readme,
        }
    app = _demo_app_source(title)
    readme = (
        f"# {title}\n\n"
        "本地 mock / 演示成品。无 `DEEPSEEK_API_KEY` 时 `POST /generate` 仍返回 **HTTP 200** 与本地回落结果（非 5xx）。\n\n"
        "## 启动\n\n"
        "```sh\n"
        "pip install -r requirements.txt\n"
        "# 可选：export DEEPSEEK_API_KEY=...\n"
        "uvicorn app:app --port 8000\n"
        "```\n\n"
        "浏览器打开 http://127.0.0.1:8000/ 即可点「发送」演示。\n\n"
        "## 调用\n\n"
        "```sh\n"
        "curl -X POST http://127.0.0.1:8000/generate -H 'Content-Type: application/json' -d '{\"input\":\"你好\"}'\n"
        "```\n"
    )
    return {
        "app": app,
        "requirements": "fastapi\nuvicorn\nopenai\n",
        "readme": readme,
    }
