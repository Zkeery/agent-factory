# Agent造物坊 · 项目规则

先读取 `../../AGENTS.md` 和 `../../docs/多项目开发指南.md`；本文件只补充本项目事实，不复制共享规则。

- 当前项目固定为本目录（`projects/Agent造物坊`），共享仓库根目录为 `../..`。
- 文档导航为 `docs/README.md`。技术文档与验收证据按 PRD 版本集中归档：`docs/PRD/版本/Vx.y/技术文档/`、`docs/PRD/版本/Vx.y/验收证据/`；当前版本见 `docs/PRD/版本记录.md`。共享规则和手册中的 `docs/阶段文档/`、`docs/evidence/` 在本项目映射到上述位置，不再创建平行目录。版本目录统一包含 `技术文档/`、`验收证据/`、`PRD.md`、`README.md`；后端技术文档直接平铺（`技术适配声明.md`、`第N阶段技术开发文档.md`），验收证据按阶段分目录。
- 首先读本项目 `project.json`、`docs/项目状态.md` 和 `docs/PRD/`，不要读取其他项目的进度、PRD 或密钥作为本项目输入。
- 本项目需求、代码、测试、配置、数据、日志、架构方案和验收证据全部写在本目录内。跨项目改动须有明确任务范围。
- 后端开发端口 `8010`，前端开发端口 `3010`；启动前检查是否被外部程序占用，端口调整只修改本项目配置与启动说明。
- 业务配置用本项目 `.env`；蓝图模型配置用本项目 `.env.blueprint`。Python 环境、node_modules、数据库和云资源按项目独立配置。
- 使用共享蓝图时走 `../../scripts/blueprint.py --project "Agent造物坊" ...`；方法与冲突处理见共享指南。不把参考组件当作本项目已实现功能。
- 本地起后端必须用 `scripts/ensure-backend.sh`（或 `scripts/dev-up.sh` / 前端 `npm run dev` 的 predev）。禁止只在前台跑 uvicorn 不挂住：终端一关后端就挂，登录页会 Failed to fetch。调试杀进程后要用 ensure 再拉起。
