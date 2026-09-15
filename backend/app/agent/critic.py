"""Critic 复审：幻觉/答非所问检查 + 转人工决策（LLM 优先，规则兜底）。

转人工三路汇合：
1. Router 低置信度 / 投诉意图（路由层处理）
2. Critic 判定（工具失败、关键数据缺失、回答泛化）
3. 用户主动要求（“转人工/人工客服”等关键词，路由层同时覆盖）
"""

import json
import logging

logger = logging.getLogger("app.agent.critic")

CRITIC_PROMPT = """你是电商客服回答质检员。根据【用户问题】【工具结果】【候选回答】判断：
1. 回答是否基于工具结果、有无编造（幻觉）；
2. 是否答非所问；
3. 是否需要转人工（工具失败、关键数据缺失、无法确认、用户情绪激烈等）。
只输出一个 JSON：{"pass": true/false, "escalate": true/false, "reason": "一句话原因"}"""


def rule_review(user_text: str, steps: list, reply: str) -> dict:
    """规则兜底：工具失败/超时、无回答、有工具调用但回答无业务数据 → 转人工。"""
    reasons = []
    escalate = False
    has_error = any(
        "error" in (s.get("result") or {}) or "超时" in str(s.get("result") or {})
        for s in steps
    )
    if has_error:
        escalate = True
        reasons.append("工具调用失败或超时")
    if not reply:
        escalate = True
        reasons.append("无回答内容")
    if steps and not any(
        k in reply for k in ("订单", "物流", "退款", "运费", "发票", "地址", "知识库", "规则")
    ):
        escalate = True
        reasons.append("有工具调用但回答未包含业务数据，疑似答非所问")
    if not escalate:
        reasons.append("回答基于工具结果，未发现幻觉或答非所问")
    return {"pass": not escalate, "escalate": escalate, "reason": "；".join(reasons)}


async def review(user_text: str, steps: list, reply: str, use_llm: bool = True) -> dict:
    if use_llm:
        from .llm import OpenAIChatLLM

        if OpenAIChatLLM.available():
            try:
                llm = OpenAIChatLLM()
                raw = await llm.complete(
                    [
                        {"role": "system", "content": CRITIC_PROMPT},
                        {
                            "role": "user",
                            "content": (
                                f"用户问题：{user_text}\n"
                                f"工具结果：{json.dumps(steps, ensure_ascii=False)[:1500]}\n"
                                f"候选回答：{reply}"
                            ),
                        },
                    ]
                )
                data = json.loads(raw)
                verdict = {
                    "pass": bool(data.get("pass", True)),
                    "escalate": bool(data.get("escalate", False)),
                    "reason": data.get("reason", ""),
                    "mode": "llm",
                }
                logger.info("Critic(LLM): %s", verdict)
                return verdict
            except Exception as exc:
                logger.warning("Critic LLM 失败，降级规则引擎：%s", exc)

    verdict = rule_review(user_text, steps, reply)
    verdict["mode"] = "rule"
    logger.info("Critic(rule): %s", verdict)
    return verdict
