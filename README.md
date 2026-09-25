# Agent造物坊

本目录集中保存本项目的需求、文档、代码、测试和运行数据。用编码工具单独打开本目录，读取 `AGENTS.md` 即可继续开发。

## 当前状态

**V1.1 核心 MVP 已完成**：三栏对话式工作台（PM/开发者双视图）+ 工厂流水线（想法→决策→PRD→确认→构建→测试→验收→交付）+ 报错对人话 + 多模型工位（Run 级 mock/DeepSeek）+ 样例打分验收标准 + 图像/视频护栏 + 深色工作台视觉。公网部署后置（先不上线）。进度与决策见 [项目状态](docs/项目状态.md)，文档导航见 [docs/README.md](docs/README.md)。

## 启动与验证

**推荐（保活，防登录页 Failed to fetch）**：裸跑前台 `uvicorn` 容易随终端/会话断开而挂掉；请用幂等保活脚本，或直接 `npm run dev`（会经 `predev` 自动 ensure 后端）。

```sh
# 只保活后端 8010（已在跑则秒过；否则 nohup 后台拉起）
bash scripts/ensure-backend.sh

# 一键：ensure 后端 + 若 3010 未起则后台启动前端
bash scripts/dev-up.sh
```

日常开前端（会先跑 `predev` → ensure-backend，失败则阻止 dev）：

```sh
cd frontend
npm install   # 首次
npm run dev   # 端口 3010；自动保活 8010
```

桌面端（Electron 壳，一键拉起后端 + 前端并打开桌面窗口；窗口位置/大小会自动记住）：

```sh
cd frontend
npm run desktop
```

打包 .app（需先 `npm install` 拉取 electron-builder；产物在 frontend/dist/，后端仍依赖本机 Python/venv）：

```sh
cd frontend
npm run dist
```

### 备选：手动命令（易掉线，仅排障用）

后端（8010）——首次建环境后，日常请改用 `ensure-backend.sh`：

```sh
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
# 不推荐长期前台跑；会话断即挂 → 登录 Failed to fetch
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8010
```

前端（3010）：

```sh
cd frontend
npm run dev -- --port 3010
```

- 正式前端：http://127.0.0.1:3010/ （手机号验证码登录 → 底部输入框说想法 → 决策卡快捷按钮 → 确认 PRD → 对话流出现完成消息）
- 临时验收界面：http://127.0.0.1:8010/
- 接口文档：http://127.0.0.1:8010/docs
- 度量接口：`GET /api/v1/metrics`（稳定出货率/平均耗时/平均成本/质量合格率）
- 打分接口：`POST /api/v1/runs/{id}/score`（决策卡/PRD/代码各 1-3 分）
- 后端测试：`cd backend && .venv/bin/python -m pytest -q`
- 前端检查：`cd frontend && npm test && npm run e2e && npm run lint && npm run build`（e2e 需前后端均已启动）
- 配置：`backend/.env.example`（复制为 `.env`，默认 mock，零真实 Key）

## 文件位置

| 内容 | 位置 |
| --- | --- |
| 项目身份、开发端口 | `project.json` |
| 需求和附件 | `docs/PRD/` |
| 技术适配、架构与开发阶段文档 | `docs/PRD/版本/V1.0/技术文档/` |
| 正式蓝图运行结果 | `docs/blueprint-runs/<plan或audit>/<任务>/` |
| 验收证据 | `docs/PRD/版本/V1.0/验收证据/` |
| 后端、测试及其依赖 | `backend/`（按需创建） |
| 前端及其依赖 | `frontend/`（按需创建） |
| 业务配置、蓝图配置 | `.env`、`.env.blueprint`（本地创建） |
| 数据库、上传、运行日志 | `data/`、`logs/`（按需创建） |

后端预留端口 `8010`，前端预留端口 `3010`。它们是约定值，不代表服务已实现或端口已被系统保留。

## 共享开发工具

需求访谈、架构设计、开发验收的衔接见 [多项目开发指南](../../docs/多项目开发指南.md)。共享手册和蓝图留在仓库公共区，本项目的运行产物不写入公共区。

业务启动和测试命令由 AI 在实际实现后补充；不要套用其他项目的模型、端口或数据库配置。

## 发布说明（V1.1）

- 版本：V1.1（本地 MVP，核心闭环）
- 后端：FastAPI + SQLite，流水线（提交→澄清→PRD→确认→构建→测试→部署→证据→闸门）+ 度量 + 看门狗 + 登录/账号隔离 + Run 级模型 + 失败可解释（failure_code → PM 人话）+ 视频/试衣成品护栏 + 定时无人值守（每天定时自动生成草稿）+ 生成稳定性（剥杂质 + 语法错误重试）
- 前端：Next.js 三栏对话式工作台（PM/开发者双视图 / 决策卡 A+B / 验收清单 / 失败人话 / 暖色浅色工作台 / 多 Agent 分工看板）+ Electron 桌面壳（`npm run desktop`）
- 模型：DeepSeek deepseek-chat（mock 可离线跑，真实 Key 填 .env）；Run 级可选 mock / deepseek
- 启动：后端 8010 + 前端 3010；推荐 `bash scripts/ensure-backend.sh` / `bash scripts/dev-up.sh` 或 `cd frontend && npm run dev`（见上方「启动与验证」）

## 已知问题（未完成项）

1. 真实短信服务：未接（当前 mock 短信，验证码直接显示；上线再接真实短信）
2. 公网部署：后置（先不上线，企业实名认证未办；蓝图审稿其余 [medium]/[low] 项已记录在案，留作后续迭代）
3. 预览非沙箱运行：点「预览成品」时生成的代码会以真实进程在本机跑，并带上你的 DEEPSEEK_API_KEY 与联网权限（测试阶段有沙箱静态检查，预览阶段没有）。本地 MVP 自用可接受；对外开放前必须先加 Docker / 网络隔离。
4. 试穿/试衣预览图为本地 Pillow 固定位置覆盖的演示图，不是真试穿（无法贴合人像）；真试穿需云端图像模型（后置）。
