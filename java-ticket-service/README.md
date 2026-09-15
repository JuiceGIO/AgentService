# Java 工单服务（Spring Boot 4 + Java 21）

Spring Boot 4（4.0.8）+ Java 21 工单服务，负责客服闭环里确定性最强的一段：

- 表驱动状态机：新建 NEW → 处理中 PROCESSING → 已解决 RESOLVED / 已退款 REFUNDED / 已关闭 CLOSED
- 非法跳转返回 HTTP 409（`{"detail": ...}`），不存在返回 404
- SLA 超时升级：NEW / PROCESSING 超过阈值由定时扫描自动升级为 ESCALATED（留痕 `ESCALATE_TIMEOUT`），人工可 RESOLVED / REFUNDED / CLOSED 收口
- 动作留痕：创建/流转/升级全部记录在 `ticket_actions`（审计用）
- 审计增强（V2）：`ticket_actions` 为 append-only 流水（只追加不删除），新增 actor 操作人字段；流转/升级/建单均在同一事务内提交
- 双模式仓库：默认内存（单机演示免运维）；`--spring.profiles.active=postgres` 切 PostgreSQL + Flyway（`tickets` / `ticket_actions` 两表，重启数据不丢）
- REST API：`GET /tickets?sessionId=`、`POST /tickets`、`GET /tickets/{id}`、`POST /tickets/{id}/transition`、`GET /tickets/overdue`

## SLA 参数（演示默认值，生产按业务调大）

```properties
ticket.sla.new-seconds=30        # 新建工单 30s 未处理 -> 升级
ticket.sla.processing-seconds=60 # 处理中工单 60s 未更新 -> 升级
ticket.sla.scan-ms=10000         # 定时扫描周期 10s
```

## 构建与运行（需要 JDK 21 + Maven）

前置：JDK 21（本机若默认 Java 不是 21，构建前先设置 `JAVA_HOME`）；Maven 可用 `winget install Apache.Maven`，
或到 https://maven.apache.org 下载后把 `bin` 加进 PATH。

```powershell
$env:JAVA_HOME = "<你的 JDK 21 路径>"          # 例：C:\Program Files\Eclipse Adoptium\jdk-21.x.x
$env:Path = "$env:JAVA_HOME\bin;$env:Path"
cd java-ticket-service
mvn -q package
java -jar target\ticket-service-0.1.0.jar
```

服务监听 <http://127.0.0.1:8080>（与 Python 层的 8000 端口错开）。

## 超时升级验证

```powershell
# 建单后约 40s 内应看到状态自动变为 ESCALATED
curl.exe -s -X POST http://127.0.0.1:8080/tickets -H "Content-Type: application/json" -d "{\"sessionId\":\"sla1\",\"title\":\"超时升级演示\",\"category\":\"complaint\",\"priority\":\"high\"}"
# 等 40s 后查询（应含 actions: ESCALATE_TIMEOUT）
curl.exe -s "http://127.0.0.1:8080/tickets/1"
# 人工收口
curl.exe -s -X POST http://127.0.0.1:8080/tickets/1/transition -H "Content-Type: application/json" -d "{\"to\":\"RESOLVED\"}"
```

## PostgreSQL 模式（可选，默认仍是内存）

需要 Docker Desktop（或本机 PostgreSQL 16）。先启动数据库：

```powershell
docker run -d --name agentservice-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=agentservice -p 5432:5432 postgres:16
```

重新构建并带 postgres profile 启动（Flyway 自动执行 V1/V2 迁移）：

```powershell
$env:JAVA_HOME = "<你的 JDK 21 路径>"
mvn -q package
java -jar target\ticket-service-0.1.0.jar --spring.profiles.active=postgres
```

验证持久化：建一张工单 → Ctrl+C 停服务 → 重新启动 → `GET /tickets` 工单仍在、留痕完整。
默认内存模式不受影响：不带 profile 直接 `java -jar` 即可，适合无数据库演示。

## 快速验证

```powershell
# 建单
curl.exe -s -X POST http://127.0.0.1:8080/tickets -H "Content-Type: application/json" -d "{\"sessionId\":\"s1\",\"title\":\"物流投诉\",\"category\":\"complaint\",\"priority\":\"high\"}"
# 流转 NEW -> PROCESSING（合法）
curl.exe -s -X POST http://127.0.0.1:8080/tickets/1/transition -H "Content-Type: application/json" -d "{\"to\":\"PROCESSING\"}"
# 非法跳转 NEW -> REFUNDED（应返回 409）
curl.exe -s -o NUL -w "%{http_code}" -X POST http://127.0.0.1:8080/tickets/1/transition -H "Content-Type: application/json" -d "{\"to\":\"REFUNDED\"}"
```

## 状态机转移表

| 当前 | 允许去向 |
|---|---|
| NEW | PROCESSING, CLOSED, ESCALATED |
| PROCESSING | RESOLVED, REFUNDED, CLOSED, ESCALATED |
| ESCALATED | RESOLVED, REFUNDED, CLOSED（人工收口） |
| RESOLVED | CLOSED |
| CLOSED / REFUNDED | 终态 |

## 设计说明

- 状态机核心逻辑为纯 Java（不依赖 Spring），可脱离容器单独测试；`TicketEscalationTest` 覆盖状态机合法/非法跳转。
- Spring 层把内存与 PostgreSQL 两种仓库实现统一到同一接口，切换成本只在一个 profile。
- `ticket_actions` 只追加不删除，SLA 升级、人工流转、建单都在同一事务内落库，保证审计可追溯。
