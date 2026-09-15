"""LLM 调用封装：联网走 OpenAI 兼容接口（DeepSeek）；无 Key 或调用失败时降级为内置规则引擎。"""

import json
import logging
import re

import httpx

from ..config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
from .router import detect_intent_rule

logger = logging.getLogger("app.agent.llm")

SYSTEM_PROMPT = """你是电商售后智能客服「小助」。必须基于工具返回的事实回答，禁止编造。
每一步只输出一个 JSON（不要多余文字）：
- 需要调用工具时：{"tool": "工具名", "args": {...}}
- 信息足够时：{"answer": "给客户的最终回答"}
可用工具：query_order(order_id)、list_orders_by_phone(phone)、query_logistics(order_id)、check_refund_eligibility(order_id)、get_refund_flow(refund_type)、search_knowledge(query, top_k)。
客户没给订单号时可用示例订单 ORD-20260828001，手机号可用 13800001234。"""

DEFAULT_ORDER = "ORD-20260828001"
DEFAULT_PHONE = "13800001234"


def parse_action(raw: str):
    """解析模型输出的动作 JSON（容错：去代码围栏、截取首个 {...}）。"""
    if not raw:
        return None
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
        return None


class OpenAIChatLLM:
    """OpenAI 兼容接口（DeepSeek /chat/completions）。"""

    @staticmethod
    def available() -> bool:
        return bool(OPENAI_API_KEY and OPENAI_BASE_URL)

    async def complete(self, messages) -> str:
        url = OPENAI_BASE_URL.rstrip("/") + "/chat/completions"
        payload = {
            "model": OPENAI_MODEL,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 1024,
        }
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        return (data["choices"][0]["message"]["content"] or "").strip()


def _build_plan(intent: str, text: str):
    if intent == "escalate":
        return [{"answer": "好的，已为您转接人工客服，投诉工单会同步创建，24 小时内响应。"}]
    if intent == "refund":
        return [
            {"tool": "check_refund_eligibility", "args": {"order_id": DEFAULT_ORDER}},
            {"answer": None},
        ]
    if intent == "logistics":
        return [
            {"tool": "query_logistics", "args": {"order_id": DEFAULT_ORDER}},
            {"answer": None},
        ]
    if intent == "order":
        return [
            {"tool": "query_order", "args": {"order_id": DEFAULT_ORDER}},
            {"answer": None},
        ]
    if intent == "knowledge":
        return [
            {"tool": "search_knowledge", "args": {"query": text, "top_k": 2}},
            {"answer": None},
        ]
    return [{"answer": "抱歉，我还没完全理解您的问题。可以试试：查订单 / 查物流 / 退货退款 / 运费规则 / 投诉转人工。"}]


def _compose_answer(intent: str, result: dict) -> str:
    if intent == "order":
        if not result.get("found"):
            return result.get("message", "未查到订单。")
        items = "、".join(i["name"] for i in result["items"])
        return (
            f"您的订单 {result['order_id']} 当前状态：{result['status']}；"
            f"金额 ¥{result['amount']}；商品：{items}。下单时间 {result['created_at']}。"
        )
    if intent == "logistics":
        if not result.get("found"):
            return result.get("message", "未查到物流信息。")
        last = result["events"][-1]
        return (
            f"订单 {result['order_id']} 的物流：{result['carrier']}（运单号 {result['tracking_no']}），"
            f"当前 {result['status']}。最新轨迹：{last['time']} {last['node']} {last['desc']}。{result['eta']}。"
        )
    if intent == "refund":
        if not result.get("found"):
            return result.get("message", "未查到退款信息。")
        return (
            f"订单 {result['order_id']}：{result['reason']}"
            f"退款类型：{result['refund_type']}；运费：{result['shipping_fee']}；{result['refund_time']}。"
        )
    if intent == "knowledge":
        if not result.get("found"):
            return result.get("message", "知识库暂无匹配条目。")
        parts = [f"【{r['title']}】{r['content']}（出处：{r['id']}）" for r in result["results"]]
        return "根据售后知识库：\n" + "\n".join(parts)
    return "已为您查询到相关信息，详见上方数据。"


class RuleLLM:
    """内置规则引擎：无网络/无 Key 时的兜底，输出与 LLM 相同的动作 JSON。"""

    def __init__(self):
        self._plan = None
        self._idx = 0
        self._user_text = ""
        self._intent = None

    def set_intent(self, intent: str) -> None:
        self._intent = intent

    def _ensure_plan(self, messages):
        if self._plan is None:
            user_msgs = [
                m["content"] for m in messages
                if m["role"] == "user" and not str(m["content"]).startswith("工具结果")
            ]
            user_text = user_msgs[-1] if user_msgs else ""
            self._user_text = user_text
            intent = self._intent or detect_intent_rule(user_text)[0]
            self._plan = _build_plan(intent, user_text)

    async def complete(self, messages) -> str:
        self._ensure_plan(messages)
        action = self._plan[self._idx] if self._idx < len(self._plan) else {"answer": "抱歉，处理超时，已为您转人工。"}
        self._idx += 1
        if action.get("answer") is None:
            obs = [
                m for m in messages
                if m["role"] == "user" and str(m["content"]).startswith("工具结果")
            ]
            if obs:
                try:
                    result = json.loads(str(obs[-1]["content"]).replace("工具结果:", "", 1))
                    intent = self._intent or detect_intent_rule(self._user_text)[0]
                    action["answer"] = _compose_answer(intent, result)
                except Exception:
                    action["answer"] = "已为您查询到相关信息，详见上方数据。"
        return json.dumps(action, ensure_ascii=False)
