# 演示脚本（30 秒 / 2 分钟 / 5 分钟，）

> 配套：周复盘里的讲稿（week1/2/3-review.md）、面试 10 问（interview-qa.md）。

## 0. 演示前检查（5 分钟准备）

- [ ] 服务就绪：docker compose -p agentservice ps 四个容器 healthy（或本地 Python 8000 + Java 8080）
- [ ] 浏览器 Ctrl+F5 打开 http://127.0.0.1:8000，工作台三栏可见
- [ ] 预置数据：先用「我要投诉」建 1-2 张工单，右栏能看见
- [ ] 如演示“超时升级”：可把 Java SLA 调小（ticket.sla.new-seconds=10 再启动），或直接展示已 ESCALATED 的工单
- [ ] 备好两个脚本窗口：acceptance_12.py、run_eval.py（快进展示用）

## 1. 30 秒版本（一句话主线）

1. 打开工作台 → 输入「这个能退吗」→ 展开下方“消息协议回放”：Planner 拆 4 个任务、Worker 并行查订单/物流/规则。
2. 点「转人工」→ 回复带“工单 #N 已创建”，右栏工单面板立刻出现新工单。
3. 点开工单看 actions 留痕，收尾：
   「200 条评测 99%，12 项全流程验收全过，docker 一条命令能起整套。」

## 2. 2 分钟版本（面试/评审）

1. 开场一句话：「电商售后智能客服，多 Agent 协作 + Java 工单闭环，全链路可评测可复现。」
2. 演示「这个能退吗」→ 展开协议回放，讲 Planner/Worker/Critic 与消息协议可回放。
3. 演示「我要投诉」→ 自动建单 → 右栏工单面板出现（状态/详情/actions）。
4. 讲 SLA：Java 定时扫描，超时自动升级 ESCALATED 并留痕；页面 6 秒轮询变色。
5. 讲持久化/工程：PostgreSQL+Flyway 重启不丢；任务队列 + 延迟队列带兜底；docker-compose 一键起。
6. 收尾给数字：golden 200 条 99.0%；单/多 Agent 覆盖 100%；12/12 验收；50 并发 p50 48ms。

## 3. 5 分钟版本（完整技术讲解）

在 2 分钟版基础上补：
- 难点 1：Spring Boot 4 Flyway 模块化两连坑（starter + flyway-database-postgresql）
- 难点 2：加 JDBC 后内存模式回归 → profile 隔离自动配置
- 难点 3：MCP 单会话生命周期规避 anyio 清理 bug（Week1）
- 难点 4：Docker 中文目录名 / 构建上下文 / Maven Central 超时三个容器坑
- 数据说话：压测 50 并发 vs 500 并发对照（单进程边界 → 多 worker 方向）
- 收尾：简历/面试题/交接文档都在 docs，安全审计 0 密钥。

## 4. 常被追问的演示点

- “为什么手写编排器？”→ 原理透明 + 协议可回放；LangGraph 是生产等价物（README 有对标）。
- “转人工怎么判定？”→ Router 低置信度 / Critic 质检 / 用户显式，三路汇合。
- “评测怎么防自嗨？”→ 分意图指标 + 刻意难例 + 单/多对比 + JSON 落档可复现。
- “500 并发延迟高怎么办？”→ 单进程排队是边界；生产多 worker + 扩容，CI 加阈值回归。
