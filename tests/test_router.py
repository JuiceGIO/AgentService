import asyncio
import unittest

import _path  # noqa: F401

from app.agent.router import (
    Router,
    decide_hybrid,
    detect_intent_rule,
    needs_llm_second_opinion,
)


class RouterRuleTests(unittest.TestCase):
    def test_order_intent(self):
        intent, _ = detect_intent_rule("订单多少钱")
        self.assertEqual(intent, "order")

    def test_logistics_intent(self):
        intent, _ = detect_intent_rule("快递到哪了")
        self.assertEqual(intent, "logistics")

    def test_refund_intent(self):
        intent, _ = detect_intent_rule("这个能退吗")
        self.assertEqual(intent, "refund")

    def test_escalate_intent(self):
        intent, _ = detect_intent_rule("我要投诉")
        self.assertEqual(intent, "escalate")

    def test_knowledge_intent(self):
        intent, _ = detect_intent_rule("发票怎么开")
        self.assertEqual(intent, "knowledge")

    def test_fallback_intent(self):
        intent, conf = detect_intent_rule("你好")
        self.assertEqual(intent, "fallback")
        self.assertLess(conf, 0.55)

    def test_priority_escalate_over_refund(self):
        intent, _ = detect_intent_rule("我要投诉退货问题")
        self.assertEqual(intent, "escalate")

    def test_priority_refund_over_knowledge(self):
        intent, _ = detect_intent_rule("退货地址怎么填")
        self.assertEqual(intent, "refund")

    def test_router_escalate_complaint(self):
        intent, _conf, escalated = asyncio.run(Router(use_llm=False).route("客服态度太差了"))
        self.assertEqual(intent, "escalate")
        self.assertTrue(escalated)

    def test_router_low_confidence_escalates(self):
        intent, _conf, escalated = asyncio.run(Router(use_llm=False).route("你好"))
        self.assertEqual(intent, "fallback")
        self.assertTrue(escalated)

    def test_llm_trigger_on_fallback(self):
        self.assertTrue(needs_llm_second_opinion("随便聊聊", "fallback", 0.5))

    def test_llm_trigger_on_difficult_pattern(self):
        self.assertTrue(needs_llm_second_opinion("订单怎么还没到", "order", 0.8))
        self.assertTrue(needs_llm_second_opinion("退货规则是什么", "refund", 0.8))

    def test_no_trigger_on_confident_normal(self):
        self.assertFalse(needs_llm_second_opinion("订单多少钱", "order", 0.8))

    def test_no_trigger_when_rule_escalate(self):
        self.assertFalse(needs_llm_second_opinion("投诉配送员", "escalate", 0.8))

    def test_disagree_both_unsure_escalates(self):
        intent, conf, escalated = decide_hybrid("order", 0.5, "logistics", 0.4)
        self.assertTrue(escalated)
        self.assertLess(conf, 0.55)

    def test_disagree_llm_confident_uses_llm(self):
        intent, _conf, escalated = decide_hybrid("order", 0.8, "logistics", 0.9)
        self.assertEqual(intent, "logistics")
        self.assertFalse(escalated)

    def test_agree_uses_llm_confidence(self):
        intent, conf, escalated = decide_hybrid("refund", 0.8, "refund", 0.95)
        self.assertEqual(intent, "refund")
        self.assertEqual(conf, 0.95)
        self.assertFalse(escalated)

    def test_llm_none_falls_back_rule(self):
        intent, conf, escalated = decide_hybrid("order", 0.8, None, 0.0)
        self.assertEqual(intent, "order")
        self.assertEqual(conf, 0.8)
        self.assertFalse(escalated)


if __name__ == "__main__":
    unittest.main()
