"""Router：意图识别（LLM 优先，规则兜底），低置信度或投诉类直接转人工。"""

import json
import logging

logger = logging.getLogger("app.agent.router")

INTENT_LABELS = {
    "order": "订单查询",
    "logistics": "物流查询",
    "refund": "退换货/退款",
    "escalate": "投诉/转人工",
    "knowledge": "知识库查询",
    "fallback": "其他",
}

LOW_CONFIDENCE = 0.55

# 语义难例白名单：规则可能“自信但判错”的口语/歧义表达，命中就交给 LLM 二次判定
DIFFICULT_PATTERNS = (
    "还没到", "怎么还没", "配送", "实付", "优惠券", "坏了", "能修", "修吗",
    "在哪个城市", "支付方式", "运费险", "退货规则", "退换货政策", "漏发", "补发",
)

ROUTER_PROMPT = """你是电商客服意图分类器。把客户问题归类到以下之一：
- order：订单查询（订单状态/金额/商品/下单时间）
- logistics：物流查询（快递/发货/签收/轨迹/到达）
- refund：退换货/退款（退货/换货/退款/运费/取消订单）
- escalate：投诉/转人工（投诉/举报/找人工/客服态度差）
- knowledge：知识库规则查询（发票/地址/保修/政策/规则）
- fallback：其他
只输出一个 JSON：{"intent": "类别", "confidence": 0.0-1.0}"""

# 规则优先级从上到下；命中返回 (intent, 0.8)
RULE_INTENTS = [
    ("escalate", ("投诉", "人工", "客服态度", "客服", "差评", "举报", "领导", "升级处理")),
    ("refund", ("退", "换货", "退款", "运费", "退货", "仅退款", "取消订单", "无理由", "能退")),
    ("logistics", ("物流", "快递", "到哪", "发货", "签收", "运输", "送到", "派送", "运单")),
    ("knowledge", ("发票", "地址", "改地址", "规则", "政策", "知识", "保修", "质保", "包邮", "怎么开", "开具")),
    ("order", ("订单", "买了", "下单", "价格", "多少钱", "商品", "订单号", "查")),
]


def detect_intent_rule(text: str):
    """规则兜底：关键词命中返回 (intent, 0.8)，未命中返回 (fallback, 0.5)。"""
    for intent, keywords in RULE_INTENTS:
        for kw in keywords:
            if kw in text:
                return intent, 0.8
    return "fallback", 0.5


def needs_llm_second_opinion(text: str, intent: str, confidence: float) -> bool:
    """混合路由触发条件：规则低置信度/fallback，或命中语义难例白名单。"""
    if intent == "escalate":
        return False  # 投诉/转人工规则已足够稳，不浪费 token
    if intent == "fallback" or confidence < LOW_CONFIDENCE:
        return True
    return any(p in text for p in DIFFICULT_PATTERNS)


def decide_hybrid(rule_intent: str, rule_conf: float, llm_intent: str, llm_conf: float):
    """混合路由终判：两套一致取结果；不一致时若双方都低置信 -> 转人工；
    否则取置信度更高的一方（LLM 拿到就优先语义，避免规则漏判口语题）。"""
    if llm_intent is None:
        return rule_intent, rule_conf, (rule_intent == "escalate" or rule_conf < LOW_CONFIDENCE)
    if llm_intent == rule_intent:
        intent, conf = llm_intent, max(llm_conf, rule_conf)
        escalated = intent == "escalate" or conf < LOW_CONFIDENCE
        return intent, conf, escalated
    if llm_conf < LOW_CONFIDENCE and rule_conf < LOW_CONFIDENCE:
        # 双方不一致且都拿不准：交给人工，避免猜错
        return rule_intent, min(rule_conf, llm_conf), True
    if llm_conf >= rule_conf:
        intent, conf = llm_intent, llm_conf
    else:
        intent, conf = rule_intent, rule_conf
    escalated = intent == "escalate" or conf < LOW_CONFIDENCE
    return intent, conf, escalated


class Router:
    def __init__(self, use_llm: bool = True):
        self.use_llm = use_llm

    async def route(self, text: str):
        """返回 (intent, confidence, needs_escalation)。"""
        if self.use_llm:
            from .llm import OpenAIChatLLM

            if OpenAIChatLLM.available():
                # 混合路由：规则先判（快、零成本），只有拿不准/难例才调 LLM
                rule_intent, rule_conf = detect_intent_rule(text)
                if needs_llm_second_opinion(text, rule_intent, rule_conf):
                    try:
                        llm = OpenAIChatLLM()
                        raw = await llm.complete(
                            [
                                {"role": "system", "content": ROUTER_PROMPT},
                                {"role": "user", "content": text},
                            ]
                        )
                        data = json.loads(raw)
                        intent = data.get("intent")
                        confidence = float(data.get("confidence", 0.8))
                        if intent in INTENT_LABELS:
                            return decide_hybrid(rule_intent, rule_conf, intent, confidence)
                    except Exception as exc:
                        logger.warning("Router LLM 失败，沿用规则判定：%s", exc)
                return rule_intent, rule_conf, (rule_intent == "escalate" or rule_conf < LOW_CONFIDENCE)

        intent, confidence = detect_intent_rule(text)
        escalated = intent == "escalate" or confidence < LOW_CONFIDENCE
        return intent, confidence, escalated
