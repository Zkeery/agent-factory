"""需求纠错、真实版本上下文和业务场景验收；不启动生成应用或调用真实模型。"""
from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.models import Decision, EvidenceItem, FactoryRun, SessionLocal, StageEvent
from app.services import deploy, engine, evidence, iteration, llm, mock_llm
from app.services.acceptance import DEFAULT_ACCEPTANCE_CHECKLIST
from app.services.codegen_guard import looks_like_video_idea
from app.services.stages import Stage


@pytest.fixture()
def local_pipeline(monkeypatch, tmp_path):
    # 文件与生成进程也隔离，避免新测试污染用户产物或占用预览端口。
    for module in (engine, deploy, evidence):
        monkeypatch.setattr(module, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(engine.testing, "run_tests", lambda run_id, idea="", output_type=None: (True, "测试替身通过"))
    monkeypatch.setattr(engine, "start_run_async", engine.advance_run)
    return tmp_path


def get_run(client, run_id):
    response = client.get(f"/api/v1/runs/{run_id}")
    assert response.status_code == 200, response.text
    return response.json()


def create_run(client, idea="产品经理的访谈摘要工具", mode="scenario"):
    response = client.post("/api/v1/runs", json={"idea": idea, "acceptance_mode": mode})
    assert response.status_code == 201, response.text
    return get_run(client, response.json()["id"])


def reach_prd(client, run):
    run_id = run["id"]
    for decision in get_run(client, run_id)["decisions"]:
        if decision["status"] == "open":
            response = client.post(
                f"/api/v1/runs/{run_id}/decisions/{decision['code']}/answer", json={"answer": "按推荐"},
            )
            assert response.status_code == 200, response.text
    result = get_run(client, run_id)
    assert result["current_stage"] == "awaiting_prd_confirm"
    return result


def reach_acceptance(client, run):
    prd = reach_prd(client, run) if run["current_stage"] != "awaiting_prd_confirm" else run
    response = client.post(
        f"/api/v1/runs/{prd['id']}/confirm-prd",
        json={"confirmed": True, "prd_revision": prd["prd_revision"]},
    )
    assert response.status_code == 200, response.text
    result = get_run(client, prd["id"])
    assert result["current_stage"] == "awaiting_acceptance", result
    return result


def checklist():
    return [{"id": item.id, "label": item.label, "passed": True} for item in DEFAULT_ACCEPTANCE_CHECKLIST]


def scenario_results(run):
    return [
        {"scenario_id": item["id"], "passed": True, "observation": "已用样例实际核对：" + item["expected_output"]}
        for item in run["acceptance_scenarios"]
    ]


def test_requirements_preserve_history_and_invalidate_stale_approval(local_pipeline, client, monkeypatch):
    run = reach_prd(client, create_run(client))
    run_id = run["id"]
    original_revision = run["prd_revision"]
    seen = []
    original = llm.MockLLM.generate_prd

    def capture(self, idea, decisions, source_context=None):
        seen.append(idea)
        return original(self, idea, decisions, source_context=source_context)

    monkeypatch.setattr(llm.MockLLM, "generate_prd", capture)
    # 人工修改的旧场景必须在需求改变时重建，不能继续当作已核对场景。
    custom = copy.deepcopy(run["acceptance_scenarios"])
    custom[0]["title"] = "旧范围的自定义场景"
    assert client.put(f"/api/v1/runs/{run_id}/acceptance-scenarios", json={"scenarios": custom}).status_code == 200
    response = client.post(f"/api/v1/runs/{run_id}/requirements", json={"feedback": "不要访谈摘要，改成每周记账汇总，输入收入100支出30，余额应为70。"})
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["current_stage"] == "awaiting_prd_confirm"
    assert updated["prd_revision"] > original_revision
    assert "每周记账汇总" in seen[-1]
    assert "最新明确要求为准" in seen[-1]
    assert updated["requirement_feedback"][0]["feedback"].startswith("不要访谈摘要")
    assert all(item["title"] != "旧范围的自定义场景" for item in updated["acceptance_scenarios"])
    assert any("70" in item["expected_output"] for item in updated["acceptance_scenarios"])
    assert len([item for item in updated["evidence"] if item["stage"] == "prd"]) == 2
    assert "每周记账汇总" in next(item["content"] for item in updated["evidence"] if item["stage"] == "prd")
    stale = client.post(f"/api/v1/runs/{run_id}/confirm-prd", json={"prd_revision": original_revision})
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "prd_revision_conflict"
    assert get_run(client, run_id)["current_stage"] == "awaiting_prd_confirm"
    assert client.post(f"/api/v1/runs/{run_id}/confirm-prd", json={"confirmed": True}).status_code == 409


def test_requirements_while_answering_do_not_skip_human_gate(local_pipeline, client):
    run = create_run(client)
    response = client.post(f"/api/v1/runs/{run['id']}/requirements", json={"feedback": "只服务个人，每次输入不超过500字"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["current_stage"] == "awaiting_answers"
    assert any(item["status"] == "open" for item in data["decisions"])
    assert len(data["acceptance_scenarios"]) == 1
    assert data["acceptance_scenarios"][0]["id"] == "main-flow"
    assert client.post(f"/api/v1/runs/{run['id']}/requirements", json={"feedback": "  "}).status_code == 422
    early_revision = data["prd_revision"]
    early_prd = next(item["content"] for item in data["evidence"] if item["stage"] == "prd")
    assert "决策 Q1：未答" in early_prd
    confirmed_draft = reach_prd(client, data)
    assert confirmed_draft["prd_revision"] > early_revision
    latest_prd = next(item["content"] for item in confirmed_draft["evidence"] if item["stage"] == "prd")
    q1 = next(item for item in confirmed_draft["decisions"] if item["code"] == "Q1")
    assert q1["answer"] == q1["recommendation"]
    assert q1["answer"] in latest_prd
    with SessionLocal() as session:
        current = session.get(FactoryRun, run["id"])
        assert q1["answer"] in json.loads(current.prd_snapshot)["goal_users"]


def test_requirement_failure_retains_feedback_but_blocks_old_prd(local_pipeline, client, monkeypatch):
    from app.core.errors import AppError

    run = reach_prd(client, create_run(client))

    def fail(*args, **kwargs):
        raise AppError("llm_call_failed", "模型暂时不可用", 502)

    monkeypatch.setattr(llm.MockLLM, "generate_prd", fail)
    response = client.post(f"/api/v1/runs/{run['id']}/requirements", json={"feedback": "新增导出摘要功能"})
    assert response.status_code == 502
    current = get_run(client, run["id"])
    assert current["current_stage"] == "failed"
    assert current["requirement_feedback"][-1]["feedback"] == "新增导出摘要功能"
    assert current["acceptance_scenarios"] == []
    assert len([item for item in current["evidence"] if item["stage"] == "prd"]) == 1
    # 旧批准不会重新启动旧 PRD 的构建。
    client.post(f"/api/v1/runs/{run['id']}/confirm-prd", json={"prd_revision": run["prd_revision"]})
    assert get_run(client, run["id"])["current_stage"] == "failed"


def test_scenarios_validate_content_and_freeze_after_confirmation(local_pipeline, client):
    run = reach_prd(client, create_run(client))
    url = f"/api/v1/runs/{run['id']}/acceptance-scenarios"
    cases = run["acceptance_scenarios"]
    assert client.put(url, json={"scenarios": []}).status_code == 422
    duplicate = copy.deepcopy(cases)
    duplicate.append(copy.deepcopy(duplicate[0]))
    assert client.put(url, json={"scenarios": duplicate}).status_code == 422
    blank = copy.deepcopy(cases)
    blank[0]["expected_output"] = "  "
    assert client.put(url, json={"scenarios": blank}).status_code == 422
    changed = copy.deepcopy(cases)
    changed[0]["input"] = "小赵周四负责发布周报；预算为120元。"
    changed[0]["expected_output"] = "保留小赵、周四、120元三个事实"
    saved = client.put(url, json={"scenarios": changed})
    assert saved.status_code == 200
    assert saved.json()["prd_revision"] == run["prd_revision"] + 1
    run = reach_acceptance(client, saved.json())
    assert client.put(url, json={"scenarios": changed}).status_code == 409
    assert client.post(f"/api/v1/runs/{run['id']}/requirements", json={"feedback": "迟到的纠错"}).status_code == 409


@pytest.mark.parametrize("invalid", ["missing", "duplicate", "unknown", "failed", "empty_observation"])
def test_scenario_acceptance_rejects_incomplete_results(local_pipeline, client, invalid):
    run = reach_acceptance(client, create_run(client))
    results = scenario_results(run)
    if invalid == "missing":
        results.clear()
    elif invalid == "duplicate":
        results.append(dict(results[0]))
    elif invalid == "unknown":
        results[0]["scenario_id"] = "previous-version-scenario"
    elif invalid == "failed":
        results[0]["passed"] = False
    else:
        results[0]["observation"] = "   "
    response = client.post(f"/api/v1/runs/{run['id']}/accept", json={"checklist": checklist(), "scenario_results": results})
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "acceptance_incomplete"
    assert get_run(client, run["id"])["accepted_at"] is None


def test_historical_extra_scenarios_stay_stored_and_do_not_block_main_flow(local_pipeline, client):
    run = reach_prd(client, create_run(client))
    cases = copy.deepcopy(run["acceptance_scenarios"])
    cases.append({"id": "side", "title": "空输入", "input": "留空后提交", "expected_output": "提示补充内容"})
    saved = client.put(f"/api/v1/runs/{run['id']}/acceptance-scenarios", json={"scenarios": cases})
    assert saved.status_code == 200, saved.text
    ready = reach_acceptance(client, saved.json())
    assert [item["id"] for item in ready["acceptance_scenarios"]] == ["main-flow", "side"]
    only_main = [{"scenario_id": "main-flow", "passed": True, "observation": "主流程走通"}]
    accepted = client.post(
        f"/api/v1/runs/{ready['id']}/accept",
        json={"checklist": checklist(), "scenario_results": only_main, "note": "主流程通过"},
    )
    assert accepted.status_code == 200, accepted.text
    restored = get_run(client, ready["id"])
    assert restored["current_stage"] == "delivered"
    assert [item["id"] for item in restored["acceptance_scenarios"]] == ["main-flow", "side"]
    assert restored["acceptance_results"] == only_main
    side_failed = [
        {"scenario_id": "main-flow", "passed": True, "observation": "主流程走通"},
        {"scenario_id": "side", "passed": False, "observation": "空输入仍生成了内容"},
    ]
    # 已交付后再提交不会改写记录；下面用另一条运行确认附带的历史失败观察不阻断主流程。
    other = reach_prd(client, create_run(client, idea="另一条需要保留历史场景的运行"))
    other_cases = copy.deepcopy(other["acceptance_scenarios"]) + cases[1:]
    other_saved = client.put(f"/api/v1/runs/{other['id']}/acceptance-scenarios", json={"scenarios": other_cases})
    other_ready = reach_acceptance(client, other_saved.json())
    kept = client.post(
        f"/api/v1/runs/{other_ready['id']}/accept",
        json={"checklist": checklist(), "scenario_results": side_failed, "note": "主流程通过，附带旧观察"},
    )
    assert kept.status_code == 200, kept.text
    assert get_run(client, other_ready["id"])["acceptance_results"] == side_failed


def test_successful_acceptance_persists_observations_and_timestamp(local_pipeline, client):
    run = reach_acceptance(client, create_run(client))
    results = scenario_results(run)
    response = client.post(f"/api/v1/runs/{run['id']}/accept", json={"checklist": checklist(), "scenario_results": results, "note": "本人逐项试用"})
    assert response.status_code == 200, response.text
    restored = get_run(client, run["id"])
    assert restored["current_stage"] == "delivered"
    assert restored["acceptance_results"] == results
    assert restored["acceptance_checklist"] == checklist()
    assert restored["acceptance_note"] == "本人逐项试用"
    assert restored["accepted_at"]
    with SessionLocal() as session:
        saved = session.get(FactoryRun, run["id"])
        assert json.loads(saved.acceptance_results) == results
        assert saved.accepted_at is not None
        assert session.query(StageEvent).filter(StageEvent.run_id == run["id"], StageEvent.event_type == "delivery_accepted").count() == 1
    # 重复点交付保持原观察与时间，不被新请求覆盖。
    repeated = client.post(f"/api/v1/runs/{run['id']}/accept", json={"checklist": [], "note": "覆盖"})
    assert repeated.json()["accepted_at"] == restored["accepted_at"]
    assert repeated.json()["acceptance_note"] == "本人逐项试用"


def test_saved_failed_observations_survive_reload_and_feed_child_generation(local_pipeline, client, monkeypatch):
    parent = reach_acceptance(client, create_run(client))
    parent_id = parent["id"]
    bad_result = [{"scenario_id": parent["acceptance_scenarios"][0]["id"], "passed": False, "observation": "摘要遗漏了小李负责周五交付"}]
    response = client.put(f"/api/v1/runs/{parent_id}/acceptance-results", json={"scenario_results": bad_result})
    assert response.status_code == 200, response.text
    with SessionLocal() as session:
        saved = session.get(FactoryRun, parent_id)
        assert json.loads(saved.acceptance_results) == bad_result
    assert get_run(client, parent_id)["acceptance_results"] == bad_result
    assert get_run(client, parent_id)["accepted_at"] is None
    for items in ([bad_result[0], bad_result[0]], [{**bad_result[0], "scenario_id": "unknown"}]):
        assert client.put(f"/api/v1/runs/{parent_id}/acceptance-results", json={"scenario_results": items}).status_code == 400

    original_path = local_pipeline / "code" / parent_id / "app.py"
    original_code = original_path.read_text() + "\n# PARENT_SOURCE_SENTINEL\n"
    original_path.write_text(original_code)
    captured = {"prd": [], "code": []}
    old_prd = llm.MockLLM.generate_prd
    old_code = llm.MockLLM.generate_code

    def capture_prd(self, idea, decisions, source_context=None):
        captured["prd"].append(copy.deepcopy(source_context))
        return old_prd(self, idea, decisions, source_context=source_context)

    def capture_code(self, idea, prd, source_context=None):
        captured["code"].append(copy.deepcopy(source_context))
        return old_code(self, idea, prd, source_context=source_context)

    monkeypatch.setattr(llm.MockLLM, "generate_prd", capture_prd)
    monkeypatch.setattr(llm.MockLLM, "generate_code", capture_code)
    response = client.post(f"/api/v1/runs/{parent_id}/revise", json={"change_request": "修复遗漏负责人和交付日的问题", "request_id": "revision-1"})
    assert response.status_code == 201, response.text
    child = response.json()
    assert child["id"] != parent_id and child["parent_run_id"] == parent_id
    assert child["project_id"] == parent["project_id"]
    assert child["acceptance_results"] == [] and child["accepted_at"] is None
    # 父代码以后被编辑也不改变已经创建的子版本输入快照。
    original_path.write_text(original_code + "# edited after snapshot\n")
    child = reach_acceptance(client, get_run(client, child["id"]))
    for stage in ("prd", "code"):
        source = captured[stage][-1]
        assert source["files"]["app.py"] == original_code
        assert source["acceptance_results"] == bad_result
        assert source["acceptance_scenarios"] == parent["acceptance_scenarios"]
        assert source["prd"]
    assert original_path.read_text() == original_code + "# edited after snapshot\n"
    assert get_run(client, parent_id)["acceptance_results"] == bad_result
    assert get_run(client, parent_id)["current_stage"] == "awaiting_acceptance"
    assert "PARENT_SOURCE_SENTINEL" in (local_pipeline / "code" / child["id"] / "app.py").read_text()


def test_revision_request_is_idempotent_under_concurrent_submissions(local_pipeline, client):
    parent = reach_acceptance(client, create_run(client, mode="basic"))
    body = {"change_request": "增加一句话摘要", "request_id": "double-click"}
    url = f"/api/v1/runs/{parent['id']}/revise"
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post(url, json=body), range(2)))
    assert all(response.status_code == 201 for response in responses), [response.text for response in responses]
    assert len({response.json()["id"] for response in responses}) == 1
    assert responses[0].json()["acceptance_mode"] == "scenario"
    with SessionLocal() as session:
        assert session.query(FactoryRun).filter(FactoryRun.parent_run_id == parent["id"]).count() == 1
    conflict = client.post(url, json={**body, "change_request": "完全不同要求"})
    assert conflict.status_code == 409


def test_new_mutations_are_owner_scoped(local_pipeline, client):
    parent = reach_acceptance(client, create_run(client))
    code = client.post("/api/v1/auth/request-code", json={"phone": "13900139000"}).json()["mock_code"]
    token = client.post("/api/v1/auth/login", json={"phone": "13900139000", "code": code}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    run_id = parent["id"]
    assert client.post(f"/api/v1/runs/{run_id}/requirements", json={"feedback": "越权修改"}, headers=headers).status_code == 404
    assert client.put(f"/api/v1/runs/{run_id}/acceptance-scenarios", json={"scenarios": parent["acceptance_scenarios"]}, headers=headers).status_code == 404
    assert client.put(f"/api/v1/runs/{run_id}/acceptance-results", json={"scenario_results": []}, headers=headers).status_code == 404
    assert client.post(f"/api/v1/runs/{run_id}/revise", json={"change_request": "越权版本"}, headers=headers).status_code == 404


@pytest.mark.parametrize("idea,feedback,expected_type", [
    ("做一个短视频生成器", "不要视频，改成纯文案摘要工具", "text"),
    ("做一个文案摘要工具", "现在改成生成可播放的短视频", "video"),
    ("整理产品访谈记录为需求清单，保留原文依据，标出待确认问题", "纠正：仅处理粘贴的文字，不上传音视频；每条需求必须引用原文，缺少依据时标为待确认。", "text"),
])
def test_confirmed_prd_output_type_controls_testing(local_pipeline, client, monkeypatch, idea, feedback, expected_type):
    run = reach_prd(client, create_run(client, idea=idea))
    response = client.post(f"/api/v1/runs/{run['id']}/requirements", json={"feedback": feedback})
    assert response.status_code == 200, response.text
    seen = []
    monkeypatch.setattr(engine.testing, "run_tests", lambda run_id, idea="", output_type=None: (seen.append(idea) or True, "测试替身通过"))
    with SessionLocal() as session:
        current = session.get(FactoryRun, run["id"])
        assert json.loads(current.prd_snapshot)["output_type"] == expected_type
        assert engine._run_tests(session, current)
    assert looks_like_video_idea(seen[-1]) is (expected_type == "video")


def test_real_model_prompts_receive_parent_sources_and_failed_observations(monkeypatch):
    # 绕过 SDK 初始化，仅检查发给真实模型协议的消息，不发网络请求。
    model = object.__new__(llm.RealLLM)
    prompts = []
    source = {"prd": {"goal_users": "产品经理"}, "files": {"app.py": "PARENT_REAL_SOURCE"}, "acceptance_results": [{"passed": False, "observation": "遗漏负责人"}]}
    def chat(prompt, max_tokens=2000):
        prompts.append(prompt)
        if "===APP===" in prompt:
            return "===APP===\nprint('ok')\n===REQUIREMENTS===\nfastapi\n===README===\n说明"
        return json.dumps(mock_llm.generate_prd("修复遗漏负责人", [], source_context=source), ensure_ascii=False)
    monkeypatch.setattr(model, "_chat", chat)
    model.generate_prd("修复遗漏负责人", [], source_context=source)
    model.generate_code("修复遗漏负责人", {"output_type": "text"}, source_context=source)
    assert all("PARENT_REAL_SOURCE" in prompt and "遗漏负责人" in prompt for prompt in prompts)
    assert all("失败" in prompt or "passed=false" in prompt for prompt in prompts)


def test_failed_flush_rolls_back_before_recording_failure(local_pipeline, client, monkeypatch):
    run = create_run(client)

    def fail_during_flush(session, current):
        # 必填 code 为 NULL 触发真实数据库 flush 失败，Session 进入待回滚状态。
        session.add(Decision(run_id=current.id, code=None, question="invalid row"))
        session.flush()

    monkeypatch.setattr(engine, "advance", fail_during_flush)
    engine.advance_run(run["id"])
    restored = get_run(client, run["id"])
    assert restored["current_stage"] == "failed"
    assert restored["failure_code"] == "internal_error"
    with SessionLocal() as session:
        assert session.query(StageEvent).filter(StageEvent.run_id == run["id"], StageEvent.event_type == "error").count() == 1


def test_revision_keeps_parent_confirmed_type_when_old_idea_was_corrected():
    prd = mock_llm.generate_prd(
        "做一个短视频生成器\n\n本次基于父版本的修改要求：\n把按钮改成蓝色",
        [], source_context={"prd": {"output_type": "text"}},
    )
    assert prd["output_type"] == "text"
