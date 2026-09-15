import asyncio
import unittest

import _path  # noqa: F401

from app.agent.orchestrator import MultiAgentOrchestrator, Planner
from app.agent.router import Router


class FakeRegistry:
    def __init__(self, raise_tool=None):
        self.raise_tool = raise_tool

    async def call(self, tool, args):
        if tool == self.raise_tool:
            raise RuntimeError("tool boom")
        if tool == "query_order":
            return {"found": True, "order_id": "O1", "status": "已发货",
                    "amount": 99, "items": [{"name": "耳机"}]}
        if tool == "query_logistics":
            return {"found": True, "status": "运输中",
                    "events": [{"time": "10:00", "desc": "已到中转站"}]}
        if tool == "check_refund_eligibility":
            return {"found": True, "reason": "七天无理由",
                    "refund_type": "退货", "shipping_fee": "包邮"}
        if tool == "search_knowledge":
            return {"found": True, "results": [{"title": "退货运费规则", "id": "R1"}]}
        return {"found": False}


class PlannerTests(unittest.TestCase):
    def test_refund_plan_dag(self):
        tasks = Planner().plan("refund", "这个能退吗")
        self.assertEqual(len(tasks), 4)
        by_id = {t.task_id: t for t in tasks}
        self.assertIn("T1", by_id["T3"].depends_on)
        self.assertIn("T2", by_id["T3"].depends_on)
        self.assertEqual(by_id["T4"].depends_on, [])


class OrchestratorTests(unittest.TestCase):
    def _run(self, text, registry):
        orch = MultiAgentOrchestrator(registry, router=Router(use_llm=False))
        return asyncio.run(orch.run(text))

    def test_refund_composite_reply(self):
        result = self._run("这个能退吗", FakeRegistry())
        self.assertFalse(result.escalated)
        self.assertIn("退款", result.reply)
        self.assertEqual(len(result.steps), 4)
        self.assertEqual(result.intent, "refund")

    def test_single_tool_failure_isolated(self):
        result = self._run("这个能退吗", FakeRegistry(raise_tool="query_logistics"))
        self.assertFalse(result.escalated)
        t2 = next(s for s in result.steps if s["tool"] == "query_logistics")
        self.assertIn("error", t2["result"])
        self.assertIn("退款", result.reply)

    def test_fallback_escalates_without_tasks(self):
        result = self._run("你好", FakeRegistry())
        self.assertTrue(result.escalated)
        self.assertEqual(result.steps, [])


if __name__ == "__main__":
    unittest.main()
