# 第十五刀验收证据｜§5.3 第一切片：多模型工位

## 自测命令

```bash
cd backend
.venv/bin/pytest tests/test_llm_profiles.py tests/test_run_llm_provider.py tests/test_compare_prd.py -q
```

手工：

1. `GET /api/v1/llm/profiles`：含 mock；deepseek 的 available 与是否配置 Key 一致；响应体无 Key。
2. 开发者新建 Run 选 Mock → 质量区显示 mock。
3. 「对比 PRD 草稿」：同一 idea 至少看到 mock 一列；有 Key 时看到 deepseek 列或明确 error。

## 预期

- Run 级 `llm_provider` 持久化；空值跟随全局
- compare-prd 不创建 Run、不写工作区
- 仅造物坊路径提交

## 自测（开发）

- 日期：2026-09-24
- 结果：实现后回填

## 人工复验记录

- 日期：
- 结果：待复验

## 自测记录（开发侧）

- 后端：`pytest tests/test_llm_profiles.py tests/test_run_llm_provider.py tests/test_compare_prd.py` 及相关回归通过。
- 前端：`npx tsc --noEmit` 通过。
- 请用户在 UI 复验：创建任务时选模型 → 质量页看本 Run 模型 → 「用当前想法对比」出多草稿（mock 必有；deepseek 视密钥）。
