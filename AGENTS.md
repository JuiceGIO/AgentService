# AGENTS.md · AgentService

本文件是本仓库对 AI 编程助手（Codex / Cursor / Claude Code 等）的约束说明，同时也给人类协作者提供快速上下文。
**改代码前先读这里；与本文冲突的做法一律以本文为准。**

## 1. 技术栈与分层约定

| 层 | 目录 | 职责 | 禁止 |
|---|---|---|---|
| Agent 层 | `backend/app/` | Router / Planner / Worker / Critic 编排、会话、任务队列 | 不直接读写工单表；不内嵌业务工具的复制实现 |
| 工具层 | `mcp_servers/` | 订单 / 物流 / 退款 / 知识库工具，按 MCP stdio 暴露 | Agent 层不得绕过 MCP 直接调用工具函数 |
| 工单服务 | `java-ticket-service/` | 表驱动状态机、非法跳转 409、SLA 扫描、append-only 留痕 | 不在 Python 侧复制状态机规则 |
| 跨语言契约 | `backend/app/ticket_client.py` | Python → Java 的唯一通道（REST + 超时 + 降级） | 不新增第二套调用方式 |
| 队列 | `backend/app/task_queue.py`、`backend/app/delayed_queue.py` | 异步任务与延迟任务（含定时兜底扫描） | 不另起线程池、不写裸 `sleep` 轮询 |

会话状态统一走 `backend/app/session_store.py`（内存 → 本地文件 → Redis 三级降级），业务代码不要自建全局字典保存状态。

## 2. 禁止事项（硬约束）

- **不动评测口径**：`docs/golden_set.json`、`docs/independent_golden.json` 的样本与标签只能整卷变更，且必须在同一次提交里更新基线数字与说明。
- **不删、不跳过测试**：`tests/` 与 `scripts/test_*.py` 的用例只能新增或修 bug；删除用例必须单独说明理由。
- **不绕过工具 schema**：新增工具必须在 `mcp_servers/` 定义 schema，参数校验（类型/范围/枚举）在入口统一做。
- **不提交敏感文件与产物**：`.env`、`*.db`、`*.bak`、`backend/data/`、`target/`、日志。
- **不写没有实测过的数字**；不伪造提交时间。
- 任何外部依赖（Redis、Java 工单服务）都必须有不可用时的降级路径，否则不允许合并。

## 3. 常用命令

```powershell
# 起服务（Python Agent 层 :8000）
cd backend; .\.venv\Scripts\python -m uvicorn app.main:app --port 8000

# 单元测试（54 例，零依赖、不联网、不需要 Key）
backend\.venv\Scripts\python.exe -m unittest discover -s tests

# 评测基线（golden 200 条，规则引擎口径）
backend\.venv\Scripts\python.exe scripts\run_eval.py

# 一键门禁：单测 + 评测 + 安全审计（Java 在跑时追加回归）
backend\.venv\Scripts\python.exe scripts\test_all.py

# Java 工单服务（需 JDK 21 + Maven）
cd java-ticket-service; mvn -q package; java -jar target\ticket-service-0.1.0.jar

# 容器一键起（PostgreSQL + Redis + Java + Python）
docker compose -p agentservice up -d --build
```

CI（`.github/workflows/ci.yml`）会跑同样的「单测 + 评测 + 安全审计」，另有 Java 构建与镜像构建两个 job：本地先跑通 `scripts/test_all.py` 再提交。

## 4. 上下文丢失后必须重读的文件

1. `docs/golden_set.json`、`docs/independent_golden.json` —— 评测口径（语义口径 200 条 / 独立语义集 40 条）。数字对不上时先看这里。
2. `backend/app/agent/router.py` —— 意图标签与判定分支的唯一来源。
3. `java-ticket-service/src/main/java/com/agentservice/ticket/TicketStateMachine.java` —— 合法跳转表。
4. `docs/llm-vs-rule-conclusion.md` —— 混合路由结论与口径（别把 99.0% / 97.5% 讲反）。
5. `README.md` —— 对外口径：评测、压测、验收数字。
