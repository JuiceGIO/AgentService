# 脚本索引

| 脚本 | 用途 | 是否需要 Key / Java |
|---|---|---|
| `test_all.py` | 一键门禁：单元测试 + 评测基线 + 安全审计（Java 在跑时追加回归） | 否 |
| `run_eval.py` | golden 200 条意图识别基线（规则引擎），报告落 `docs/eval_reports/golden200_rule_baseline.json` | 否 |
| `eval_v1.py` | 单 Agent vs 多 Agent 18 场景对比，报告落 `docs/eval_reports/golden200_eval_v2.json` | 否 |
| `compare_llm_vs_rule.py` | 规则 vs LLM vs 混合路由对比（真实调用模型） | 需要 Key |
| `load_test.py` | 并发压测（`--concurrency` / `--requests`） | 否 |
| `run_regression.py` | 一键回归：评测基线 + 对比实验 + 场景验收（`--full` 追加 SLA 用例） | 部分需要 Java |
| `acceptance_12.py` | 12 项端到端验收（建单/流转/非法 409/SLA/任务队列/评测） | 需要 Java |
| `security_audit.py` | 发布前密钥与敏感文件审计，报告落 `docs/security_audit_latest.json` | 否 |
| `test_autoticket.py` | 对话 → 自动建单闭环四路径验收 | 需要 Java |
| `test_sla_escalation.py` | SLA 超时自动升级与人工收口验收 | 需要 Java |
| `test_task_queue.py` | 异步任务队列四路径验收（生命周期/批量建单/失败隔离） | 需要 Java |
| `test_delayed_queue.py` | 延迟队列三路径验收（消息驱动/定时兜底/失败隔离） | 需要 Java |
| `test_ws.py` | WebSocket 流式会话验收 | 否 |
