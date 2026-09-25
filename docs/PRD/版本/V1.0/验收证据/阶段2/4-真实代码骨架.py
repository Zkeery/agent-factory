# 骨架占位：接入真实模型与业务逻辑的 TODO
def growth_record_app(user_input: str) -> dict:
    """
    固定流程 AI 应用骨架：帮家长记录孩子成长点滴
    输入：家长输入的一段关于孩子的描述/事件
    输出：结构化的成长记录卡片
    """
    # 步骤1：接收并整理输入
    raw_text = user_input.strip()
    if not raw_text:
        return {"success": False, "error": "输入不能为空"}

    # 步骤2：调用占位 AI 处理（TODO: 替换为真实 LLM 调用）
    ai_result = _placeholder_ai_process(raw_text)

    # 步骤3：组装并返回结果
    record = {
        "success": True,
        "original_text": raw_text,
        "title": ai_result["title"],
        "summary": ai_result["summary"],
        "tags": ai_result["tags"],
        "emotion": ai_result["emotion"],
        "age_stage": ai_result["age_stage"],
        "suggested_media": ai_result["suggested_media"],
    }
    return record


def _placeholder_ai_process(text: str) -> dict:
    """
    占位 AI 处理函数。
    TODO: 接入真实大模型（如 OpenAI / 通义千问 / 文心一言等），
          用 prompt 要求模型输出 JSON，然后解析。
    当前仅用简单规则模拟，保证骨架可运行。
    """
    keywords = ["第一次", "学会", "笑了", "走路", "说话", "生日", "上学"]
    hit = [k for k in keywords if k in text]

    if hit:
        title = f"宝贝的{hit[0]}时刻"
    else:
        title = "成长小记录"

    summary = text if len(text) <= 50 else text[:50] + "..."

    tags = []
    if any(w in text for w in ["笑", "开心", "高兴", "玩"]):
        tags.append("快乐")
    if any(w in text for w in ["哭", "怕", "摔倒", "生病"]):
        tags.append("需要安抚")
    if any(w in text for w in ["学会", "第一次", "自己"]):
        tags.append("成长里程碑")
    if not tags:
        tags.append("日常")

    if any(w in text for w in ["笑", "开心", "高兴"]):
        emotion = "positive"
    elif any(w in text for w in ["哭", "怕", "生病"]):
        emotion = "negative"
    else:
        emotion = "neutral"

    if any(w in text for w in ["奶", "爬", "翻身"]):
        age_stage = "婴儿期"
    elif any(w in text for w in ["走路", "说话", "玩具"]):
        age_stage = "幼儿期"
    elif any(w in text for w in ["上学", "作业", "朋友"]):
        age_stage = "学龄期"
    else:
        age_stage = "未知"

    suggested_media = "建议配一张当时的照片或一小段视频"

    return {
        "title": title,
        "summary": summary,
        "tags": tags,
        "emotion": emotion,
        "age_stage": age_stage,
        "suggested_media": suggested_media,
    }


if __name__ == "__main__":
    sample = "今天宝宝第一次自己走路，走了三步就笑了，全家都好开心！"
    result = growth_record_app(sample)
    import json
    print(json.dumps(result, ensure_ascii=False, indent=2))