# 第十二刀验收证据｜工作台可读 + 产物对题

## 自测命令

```bash
cd backend
.venv/bin/pytest tests/test_prd_normalize.py tests/test_video_mock.py tests/test_codegen_guard.py -q

cd ../frontend
npx vitest run lib/factory.test.ts
```

## 预期

- PRD 规范化后不再出现「交付阶段与优先级：交付阶段与优先级待定」类标题复读
- PM/Dev 会话气泡：code/deploy 短摘要，无整文件源码糊屏；验收气泡有说明文案
- 右栏页签「运行｜决策｜产物｜质量(仅 dev)」可切换；默认有产物时进「产物」
- mock「生视频」源码含 `<video` 与 `video/mp4`；新 Run 预览可播本地演示片（历史 Run 需重新生成）

## 自测（开发）

- 日期：2026-09-24
- 命令：见上
- 结果：见父 agent 报告；人工复验仍待
- 未 commit（按任务要求）

## 人工复验记录

- 日期：
- 结果：待复验
