# Agent 协作与项目复盘

## 实现结构

保留外层 `Stage` 状态机与人工需求确认/验收闸门。`FactoryRun.execution_mode` 区分 `workflow` 和 `agent_team`；协作循环运行在 `building` 内，`testing` 阶段再次执行确定性检查。开发、验证分别维护上下文与任务，通过受限工具调用及交接推进。

`agent_harness.py` 管理工具集合、角色权限、轮次预算和持久检查点。`execution_state` 保存私有状态，公开 API 与 ZIP 统一使用 `execution_view(run)` 的字段白名单，只返回任务、步骤、检查和交接摘要。启动恢复扫描把未完成协作执行标记为中断；恢复接口复用原检查点和预算。

## 接口

| 接口 | 用途 |
| --- | --- |
| `POST /api/v1/runs` | 可指定 `execution_mode`；省略时仍为 `workflow`。前端新建默认明确提交 `agent_team`。 |
| `POST /api/v1/runs/{id}/revise` | 未指定模式则继承父版本；幂等冲突比较包含模式。 |
| `GET /api/v1/runs/{id}/execution` | 返回脱敏执行视图。 |
| `POST /api/v1/runs/{id}/execution/resume` | 恢复当前用户拥有的可恢复中断任务。 |
| `GET /api/v1/metrics/review` | `source=real|mock|unknown|all`、`days=7|30|90|all`，可带 `project_id`。 |

执行视图包括 `status`、`active_role`、`limits`、`repair_rounds`、`resumable`、`stop_reason` 和 `tasks/steps/handoffs/checks`。SSE 在暂停状态结束当前流，恢复后由客户端重新连接，避免旧 ORM 状态导致一直等候。

## 度量与复盘

`record_metric` 在一次推进结束时写入本段增量 token、持续时间、模型来源、币种与单价快照。失败与取消仍记录已发生用量。只累加新段，不按当前配置重算整个历史 Run。服务返回每项指标的 `value/numerator/denominator/samples/excluded/definition`；旧数据或缺失覆盖时保留明确排除信息。

场景比较使用父子版本中的输入与预期指纹，区分已修复、仍失败、待复验、内容改变导致不可比及新增失败。交付时间包括用户等待；执行时间来自可信分段。价格估算由本项目配置决定，币种与样本覆盖必须随指标展示。

异常中断持久设置 `execution_state.accounting_incomplete=true`，恢复后保留。由于进程退出前的用量与计时可能尚未落账，这类 Run 的成本和执行耗时返回空值并从汇总排除，说明原因；创建至人工验收的经过时间仍可按有效时间戳计算。

前端 `ExecutionPanel` 展示任务和工具摘要并提供恢复按钮，`ProjectReview` 提供筛选、指标说明、样本与版本明细及 CSV。交付包增加 `docs/execution.json`，仍经过统一脱敏与大小限制。

## 兼容与限制

数据库采用幂等增量列迁移。旧 API 与旧 Run 使用原流程。角色分工不要求使用不同供应商；实际是否调用模型工具取决于所选执行模式与提供商。Mock 用于确定性验证编排，不能证明真实模型的任务完成率。自动检查不覆盖全部业务正确性，人工场景验收仍是最终交付条件。
