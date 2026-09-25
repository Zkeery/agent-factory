# 第十一刀验收证据｜成品生成护栏

## 自测命令

```bash
cd backend
.venv/bin/pytest tests/test_codegen_guard.py tests/test_mock_llm_code.py -q
# 或全量
.venv/bin/pytest -q
```

## 预期

- 破损嵌入 JS 用例失败原因含「换行」或护栏中文说明
- mock 生成物通过护栏
- 人工：新 Run 预览页发送有响应；无 Key 时不整页按钮假死（新生成物）

## 自测（开发）

- 日期：2026-09-24
- 命令：`.venv/bin/pytest tests/test_codegen_guard.py -q`（及相关回归）
- 结果：见父 agent 提交说明；人工复验仍待

## 人工复验记录

- 日期：
- 结果：待复验
