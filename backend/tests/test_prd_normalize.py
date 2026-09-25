"""第十二刀：PRD 字段规范化。"""
from __future__ import annotations

from app.services.prd_normalize import normalize_prd_fields, PRD_FIELD_TITLES
from app.services import mock_llm


def test_normalize_empty_and_title_echo():
    raw = {
        "goal_users": "  ",
        "input_process_output": "输入、过程和产物",
        "main_loop": "Agent 主链路待定",
        "quality": "什么算生成得好：待定",
        "delivery": "交付阶段与优先级：交付阶段与优先级待定",
        "model_cost": "待定",
        "data_nonfunc": "TBD",
        "launch": "上线与账号 - TBD",
    }
    out = normalize_prd_fields(raw)
    for key in PRD_FIELD_TITLES:
        assert out[key] == "待定", (key, out[key])


def test_normalize_keeps_real_content():
    raw = {
        "goal_users": "个人用户做短视频片头",
        "input_process_output": "输入文案 → 合成短片 → 可播放 mp4",
        "main_loop": "一次生成",
        "quality": "能播即可",
        "delivery": "第一版最小可用",
        "model_cost": "本地演示，无云端视频 Key",
        "data_nonfunc": "不出境",
        "launch": "本地验证",
    }
    out = normalize_prd_fields(raw)
    assert out["goal_users"] == "个人用户做短视频片头"
    assert out["delivery"] == "第一版最小可用"
    assert "交付阶段" not in out["delivery"]


def test_mock_generate_prd_is_normalized():
    prd = mock_llm.generate_prd("随便想法", [{"code": "Q1", "answer": "个人"}])
    for key, title in PRD_FIELD_TITLES.items():
        val = prd[key]
        assert val.strip()
        assert val != title
        assert not val.startswith(title + "待定")
        assert val != f"{title}：{title}待定"
