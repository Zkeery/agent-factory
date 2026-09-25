# 第十三刀验收证据｜闸门失败就地重测

## 自测命令

```bash
cd backend
.venv/bin/pytest tests/test_retest.py tests/test_retry.py -q

cd ../frontend
npx vitest run lib/factory.test.ts
```

## 预期

- `gate_failed` + 磁盘有 `app.py`：`POST /retest` 200、同 Run id、阶段离开 `gate_failed`（续跑 testing→…）
- 无代码：409，提示应整段重跑
- `awaiting_acceptance` 等：409
- `POST /retry` 仍返回新 id
- 前端闸门失败条：主「仅重测」、次「整段重跑」；已取消仅「整段重跑」

## 自测（开发）

- 日期：2026-09-24
- 命令：见上
- 结果：pytest `test_retest.py`+`test_retry.py` 8 passed；vitest `factory.test.ts` 21 passed
- commit：见 git log（本刀提交后）

## 人工复验记录

- 日期：
- 结果：待复验

### 建议复验步骤

1. 找一条 `gate_failed` 且 `backend/data/code/<run_id>/` 下已有 `app.py` 的 Run（或热修依赖后仍闸门失败的试衣 Run）。
2. 点「仅重测」：应同 id 进入测试中，通过后可到待验收；不要出现新 Run。
3. 点「整段重跑」：应新建 Run，再走决策/PRD。
