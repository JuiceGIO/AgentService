import asyncio
import unittest

import _path  # noqa: F401

from app.agent.critic import review, rule_review


class CriticRuleTests(unittest.TestCase):
    def test_tool_error_escalates(self):
        verdict = rule_review("查订单", [{"tool": "x", "args": {}, "result": {"error": "超时"}}], "抱歉")
        self.assertTrue(verdict["escalate"])

    def test_empty_reply_escalates(self):
        verdict = rule_review("查订单", [], "")
        self.assertTrue(verdict["escalate"])

    def test_answer_without_business_data_escalates(self):
        steps = [{"tool": "query_order", "args": {}, "result": {"found": True}}]
        verdict = rule_review("查订单", steps, "今天天气不错")
        self.assertTrue(verdict["escalate"])

    def test_normal_answer_passes(self):
        steps = [{"tool": "query_order", "args": {}, "result": {"found": True}}]
        verdict = rule_review("查订单", steps, "您的订单已发货")
        self.assertFalse(verdict["escalate"])

    async def _review_rule_mode(self, text, steps, reply):
        return await review(text, steps, reply, use_llm=False)

    def test_review_async_uses_rule_mode(self):
        verdict = asyncio.run(self._review_rule_mode("查订单", [], ""))
        self.assertTrue(verdict["escalate"])
        self.assertEqual(verdict.get("mode"), "rule")


if __name__ == "__main__":
    unittest.main()
