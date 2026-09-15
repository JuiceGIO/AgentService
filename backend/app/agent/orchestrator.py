"""多 Agent 编排器：Planner 拆解任务 DAG → Worker 串/并行执行 → 统一消息协议日志（role/task/result，可回放）。"""

import asyncio
import logging

from .llm import DEFAULT_ORDER, _compose_answer
from .react import AgentResult
from .router import Router

logger = logging.getLogger("app.agent.orchestrator")

TOOL_TIMEOUT = 15.0


class Task:
    def __init__(self, task_id: str, tool: str, args: dict, depends_on: list = None, description: str = ""):
        self.task_id = task_id
        self.tool = tool
        self.args = args
        self.depends_on = depends_on or []
        self.description = description


class Planner:
    """规则版 Planner：按意图拆解任务 DAG。复合问题（退款）演示串/并行。"""

    def plan(self, intent: str, text: str):
        if intent == "refund":
            return [
                Task("T1", "query_order", {"order_id": DEFAULT_ORDER}, [], "查订单状态"),
                Task("T2", "query_logistics", {"order_id": DEFAULT_ORDER}, [], "查物流轨迹"),
                Task("T3", "check_refund_eligibility", {"order_id": DEFAULT_ORDER}, ["T1", "T2"], "判断退款资格"),
                Task("T4", "search_knowledge", {"query": "退货运费规则", "top_k": 2}, [], "检索运费规则"),
            ]
        if intent == "logistics":
            return [Task("T1", "query_logistics", {"order_id": DEFAULT_ORDER}, [], "查物流")]
        if intent == "order":
            return [Task("T1", "query_order", {"order_id": DEFAULT_ORDER}, [], "查订单")]
        if intent == "knowledge":
            return [Task("T1", "search_knowledge", {"query": text, "top_k": 2}, [], "检索知识库")]
        return []


class MultiAgentOrchestrator:
    """编排入口：路由 → 拆解 → 分层执行（并行/串行）→ 汇总回答。"""

    def __init__(self, registry, router: Router = None, planner: Planner = None):
        self.registry = registry
        self.router = router or Router()
        self.planner = planner or Planner()

    async def run(self, user_text: str, history: list = None):
        intent, confidence, needs_escalation = await self.router.route(user_text)
        if needs_escalation:
            reply = (
                "好的，已为您转接人工客服，投诉工单会同步创建，24 小时内响应。"
                if intent == "escalate"
                else "抱歉，我还没完全理解您的问题，已为您转接人工客服。"
            )
            return AgentResult(
                reply=reply,
                steps=[],
                escalated=True,
                mode="orchestrator",
                intent=intent,
                confidence=confidence,
                messages=[],
            )

        tasks = self.planner.plan(intent, user_text)
        if not tasks:
            return AgentResult(
                reply="抱歉，我还没完全理解您的问题，已为您转接人工客服。",
                steps=[],
                escalated=True,
                mode="orchestrator",
                intent=intent,
                confidence=confidence,
                messages=[],
            )

        messages = [
            {
                "role": "planner",
                "task_id": t.task_id,
                "task": {
                    "tool": t.tool,
                    "args": t.args,
                    "depends_on": t.depends_on,
                    "description": t.description,
                },
            }
            for t in tasks
        ]
        results = await self._execute(tasks, messages)
        steps = [{"tool": t.tool, "args": t.args, "result": results.get(t.task_id)} for t in tasks]
        reply = self._compose(intent, tasks, results)
        return AgentResult(
            reply=reply,
            steps=steps,
            escalated=False,
            mode="orchestrator",
            intent=intent,
            confidence=confidence,
            messages=messages,
        )

    async def _execute(self, tasks: list, messages: list) -> dict:
        """按依赖分层执行：无依赖的任务并行（asyncio.gather），有依赖的等前置完成。"""
        results = {}
        pending = {t.task_id: t for t in tasks}
        while pending:
            ready = [t for t in pending.values() if all(d in results for d in t.depends_on)]
            if not ready:
                logger.warning("任务依赖环或无法满足，剩余: %s", sorted(pending))
                break

            async def run_task(t):
                try:
                    result = await asyncio.wait_for(self.registry.call(t.tool, t.args), timeout=TOOL_TIMEOUT)
                except asyncio.TimeoutError:
                    result = {"error": f"工具 {t.tool} 调用超时"}
                    logger.warning("任务超时: %s", t.task_id)
                except Exception as exc:
                    result = {"error": str(exc)}
                    logger.warning("任务失败: %s -> %s", t.task_id, exc)
                messages.append({"role": "worker", "task_id": t.task_id, "result": result})
                return t.task_id, result

            done = await asyncio.gather(*(run_task(t) for t in ready))
            for task_id, result in done:
                results[task_id] = result
                pending.pop(task_id, None)
        return results

    def _compose(self, intent: str, tasks: list, results: dict) -> str:
        if intent == "refund":
            order = results.get("T1", {})
            logi = results.get("T2", {})
            elig = results.get("T3", {})
            parts = []
            if order.get("found"):
                item = order.get("items", [{}])[0].get("name", "")
                parts.append(f"您的订单 {order['order_id']} 当前状态：{order['status']}（金额 ¥{order['amount']}，{item}）")
            if logi.get("found"):
                last = logi["events"][-1]
                parts.append(f"物流：{logi['status']}，最新 {last['time']} {last['desc']}")
            if elig.get("found") or "eligible" in elig:
                parts.append(
                    f"退款判定：{elig.get('reason', '')} 类型：{elig.get('refund_type', '')}；"
                    f"运费：{elig.get('shipping_fee', '')}"
                )
            rules = results.get("T4", {})
            if rules.get("found"):
                ref = rules["results"][0]
                parts.append(f"规则参考：{ref['title']}（出处 {ref['id']}）")
            return "；".join(parts) + "。" if parts else "已为您查询到退款相关信息。"

        task = tasks[0]
        result = results.get(task.task_id, {})
        return _compose_answer(intent, result)
