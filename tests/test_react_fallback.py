import asyncio
import unittest

import _path  # noqa: F401

import app.agent.react as react_mod
from app.agent.react import ReActAgent


class FakeLLM:
    """模拟 LLM：返回无法解析的文本（不是动作 JSON）。"""

    @staticmethod
    def available():
        return True

    async def complete(self, messages):
        return "抱歉，我暂时无法给出工具调用。"


class FakeAnswerLLM:
    """模拟 LLM：输出合法 JSON，但内容是空手“没理解”回答。"""

    @staticmethod
    def available():
        return True

    async def complete(self, messages):
        return '{"answer": "抱歉，我没有理解您的问题。"}'


class FakeRegistry:
    async def call(self, tool, args):
        if tool == "check_refund_eligibility":
            return {
                "found": True,
                "order_id": "ORD-1",
                "reason": "七天无理由",
                "refund_type": "退货",
                "shipping_fee": "包邮",
                "refund_time": "1-3 个工作日",
            }
        return {"found": False}


class ReActParseFallbackTests(unittest.TestCase):
    def test_llm_parse_failure_falls_back_to_rule_tool(self):
        orig = react_mod.OpenAIChatLLM
        react_mod.OpenAIChatLLM = FakeLLM
        try:
            agent = ReActAgent(FakeRegistry())
            result = asyncio.run(agent.run("这个能退吗"))
            self.assertGreaterEqual(len(result.steps), 1)
            self.assertEqual(result.steps[0]["tool"], "check_refund_eligibility")
            self.assertIn("退款", result.reply)
            self.assertFalse(result.escalated)
        finally:
            react_mod.OpenAIChatLLM = orig

    def test_llm_empty_answer_falls_back_to_rule_tool(self):
        orig = react_mod.OpenAIChatLLM
        react_mod.OpenAIChatLLM = FakeAnswerLLM
        try:
            agent = ReActAgent(FakeRegistry())
            result = asyncio.run(agent.run("这个能退吗"))
            self.assertGreaterEqual(len(result.steps), 1)
            self.assertEqual(result.steps[0]["tool"], "check_refund_eligibility")
            self.assertIn("退款", result.reply)
        finally:
            react_mod.OpenAIChatLLM = orig


if __name__ == "__main__":
    unittest.main()
