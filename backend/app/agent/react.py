"""单 Agent ReAct 循环：思考 → 调用 MCP 工具 → 观察 → 回答。稳定性：步数上限、工具超时兜底、错误回喂、LLM 失败降级规则引擎。"""

import asyncio
import json
import logging

from .llm import OpenAIChatLLM, RuleLLM, SYSTEM_PROMPT, parse_action
from .errors import PermissionDenied
from .router import Router

logger = logging.getLogger("app.agent.react")

TOOL_TIMEOUT = 15.0  # 单次工具调用超时（秒），超时按错误回喂，不阻塞整轮


class AgentResult:
    def __init__(
        self,
        reply: str,
        steps: list = None,
        escalated: bool = False,
        mode: str = "rule",
        intent: str = None,
        confidence: float = None,
        messages: list = None,
    ):
        self.reply = reply
        self.steps = steps or []
        self.escalated = escalated
        self.mode = mode
        self.intent = intent
        self.confidence = confidence
        self.messages = messages or []


class ReActAgent:
    def __init__(self, registry, max_steps: int = 5, use_llm: bool = True, context_note: str = ""):
        self.registry = registry
        self.max_steps = max_steps
        # 三层记忆的注入点：会话摘要 + 用户长期偏好（由 SessionStore 组装）
        self.context_note = context_note or ""
        self.rule_llm = RuleLLM()
        # use_llm=False 供评测对比：强制规则引擎，保证结果可复现（不依赖 Key/网络）
        self.llm = OpenAIChatLLM() if (use_llm and OpenAIChatLLM.available()) else self.rule_llm
        self.mode = "llm" if self.llm is not self.rule_llm else "rule"
        self.router = Router(use_llm=use_llm)

    async def run(self, user_text: str, history: list = None) -> AgentResult:
        intent, confidence, needs_escalation = await self.router.route(user_text)
        self.rule_llm.set_intent(intent)
        if needs_escalation:
            if intent == "escalate":
                reply = "好的，已为您转接人工客服，投诉工单会同步创建，24 小时内响应。"
            else:
                reply = "抱歉，我还没完全理解您的问题，已为您转接人工客服。"
            return AgentResult(
                reply=reply,
                steps=[],
                escalated=True,
                mode=self.mode,
                intent=intent,
                confidence=confidence,
            )

        system_content = SYSTEM_PROMPT
        if self.context_note:
            system_content = f"{SYSTEM_PROMPT}\n\n{self.context_note}"
        messages = [{"role": "system", "content": system_content}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_text})
        observations = []
        for _ in range(self.max_steps):
            try:
                raw = await self.llm.complete(messages)
            except Exception as exc:
                logger.warning("LLM 调用失败，降级规则引擎: %s", exc)
                self.llm = self.rule_llm
                self.mode = "rule"
                raw = await self.llm.complete(messages)

            action = parse_action(raw) if self.mode == "llm" else json.loads(raw)
            # LLM 虽输出合法 JSON，但属于“没理解/无法回答”的空手回答且尚未调用任何工具：
            # 说明模型没按流程走，降级规则引擎按意图生成工具计划，保证业务链路不空转
            if (
                self.mode == "llm"
                and isinstance(action, dict)
                and "answer" in action
                and any(k in action["answer"] for k in ("没有理解", "无法回答", "不能回答", "不明白", "无法为您"))
            ):
                logger.warning("LLM 空手回答，降级规则引擎重试: %s", str(action)[:120])
                try:
                    raw = await self.rule_llm.complete(messages)
                    action = json.loads(raw)
                except Exception:
                    action = {"answer": "抱歉，我没有理解您的问题，已为您转人工处理。"}
            if not action:
                # LLM 输出无法解析成动作 JSON：降级规则引擎按已识别意图重试，
                # 保证至少会调用工具（否则步骤为 0，业务链路断）
                logger.warning("LLM 动作解析失败，降级规则引擎重试: %s", str(raw)[:160])
                try:
                    raw = await self.rule_llm.complete(messages)
                    action = json.loads(raw)
                except Exception:
                    action = {"answer": "抱歉，我没有理解您的问题，已为您转人工处理。"}
            if "answer" in action:
                return AgentResult(
                    reply=action["answer"],
                    steps=observations,
                    escalated=any(
                        k in action["answer"]
                        for k in ("已为您转人工", "已转人工", "转接人工", "人工处理")
                    ),
                    mode=self.mode,
                    intent=intent,
                    confidence=confidence,
                )

            tool = action.get("tool")
            args = action.get("args") or {}
            try:
                result = await asyncio.wait_for(self.registry.call(tool, args), timeout=TOOL_TIMEOUT)
            except asyncio.TimeoutError:
                result = {"error": f"工具 {tool} 调用超时（>{TOOL_TIMEOUT}s）"}
                logger.warning("工具超时: %s", tool)
            except PermissionDenied:
                # 越权必须向上冒泡成 403，不能被当成普通工具错误回喂给模型
                raise
            except Exception as exc:
                result = {"error": str(exc)}
                logger.warning("工具调用错误: %s -> %s", tool, exc)
            observations.append({"tool": tool, "args": args, "result": result})
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": "工具结果:" + json.dumps(result, ensure_ascii=False)})

        return AgentResult(
            reply="多次尝试仍未解决，已为您转人工并同步工单。",
            steps=observations,
            escalated=True,
            mode=self.mode,
            intent=intent,
            confidence=confidence,
        )


def _create_escalation_ticket(session_id: str, intent: str, user_text: str) -> dict:
    """转人工汇合后自动建单；返回统一 outcome，失败不抛出。"""
    from ..ticket_client import (
        CATEGORY_BY_INTENT,
        INTENT_LABELS,
        PRIORITY_BY_INTENT,
        TicketServiceError,
        create_ticket,
    )

    category = CATEGORY_BY_INTENT.get(intent, "general")
    priority = PRIORITY_BY_INTENT.get(intent, "normal")
    label = INTENT_LABELS.get(intent, "客服协助")
    brief = " ".join(user_text.strip().split())[:40]
    title = f"[{label}] {brief}" if brief else label
    try:
        ticket = create_ticket(session_id, title, category=category, priority=priority)
        return {"ok": True, "ticket": ticket, "error": None}
    except TicketServiceError as exc:
        logger.warning("自动建单失败（转人工保留，稍后补建）: %s", exc)
        return {"ok": False, "ticket": None, "error": str(exc)}


def _with_ticket_created(reply: str, ticket: dict) -> str:
    """建单成功：把“会同步创建/将转人工”的表述替换/补充为已创建事实。"""
    tid = ticket.get("id")
    status = ticket.get("status", "NEW")
    reply = reply.replace("投诉工单会同步创建", f"投诉工单已创建（#{tid}）")
    reply = reply.replace("工单会同步创建", f"工单已创建（#{tid}）")
    if f"#{tid}" not in reply:
        reply = f"{reply}（已同步创建工单 #{tid}，状态：{status}）"
    return reply


def _with_ticket_failed(reply: str) -> str:
    """建单失败（Java 未启动等）：不打断转人工，明确告知稍后补建。"""
    if "会同步创建" in reply:
        reply = reply.replace("投诉工单会同步创建", "已记录您的诉求")
        reply = reply.replace("工单会同步创建", "已记录您的诉求")
    if "补建" not in reply:
        reply = f"{reply}（工单系统暂不可用，已为您记录，将尽快补建工单。）"
    return reply


def run_agent_sync(
    user_text: str,
    history: list = None,
    session_id: str = "",
    actor_id: str = "",
    context_note: str = "",
) -> dict:
    """同步入口：在独立事件循环中跑 Agent（供 FastAPI 线程调用）。

    转人工三路汇合（Router/Critic/用户主动）后自动调 Java 工单服务建单；
    建单结果写入 messages(role=ticket) 与返回体 ticket 字段，失败优雅降级不崩溃。
    """
    import asyncio

    from .critic import review
    from .llm import OpenAIChatLLM
    from .orchestrator import MultiAgentOrchestrator
    from .tools import MCPToolRegistry

    async def _main() -> AgentResult:
        async with MCPToolRegistry(actor_id=actor_id) as registry:
            if OpenAIChatLLM.available():
                agent = ReActAgent(registry, context_note=context_note)
                return await agent.run(user_text, history=history)
            orchestrator = MultiAgentOrchestrator(registry, context_note=context_note)
            return await orchestrator.run(user_text, history=history)

    result = asyncio.run(_main())

    # Critic 复审 + 转人工三路汇合（Router 低置信度 / Critic 判定 / 用户主动要求）
    critic_verdict = asyncio.run(review(user_text, result.steps, result.reply))
    explicit_request = any(k in user_text for k in ("转人工", "人工客服", "找人工", "转接人工"))
    if critic_verdict["escalate"] or explicit_request:
        if not result.escalated:
            result.escalated = True
            result.reply = "经质检复核，这个问题需要人工处理，已为您转接人工客服。"

    # 转人工即自动建单：先记录 Critic 结论，再落 ticket 动作，保证消息流可回放
    result.messages.append({"role": "critic", "verdict": critic_verdict})
    ticket_outcome = None
    if result.escalated:
        ticket_outcome = _create_escalation_ticket(session_id, result.intent, user_text)
        if ticket_outcome["ok"]:
            result.reply = _with_ticket_created(result.reply, ticket_outcome["ticket"])
        else:
            result.reply = _with_ticket_failed(result.reply)
        result.messages.append(
            {
                "role": "ticket",
                "action": "create",
                "ticket": ticket_outcome["ticket"],
                "error": ticket_outcome["error"],
            }
        )

    return {
        "reply": result.reply,
        "steps": result.steps,
        "mode": result.mode,
        "escalated": result.escalated,
        "intent": result.intent,
        "confidence": result.confidence,
        "messages": result.messages,
        "ticket": ticket_outcome,
    }
