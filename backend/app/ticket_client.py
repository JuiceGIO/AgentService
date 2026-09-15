"""Java 工单服务 REST 桥接：转人工/投诉时自动建单，打通 对话→工单 闭环。

设计：Python Agent 层不直接持有工单状态机，只通过 REST 调用 Java 服务；
Java 不可达时抛 TicketServiceError，由上层优雅降级（仍转人工并提示稍后补建）。
"""

import logging
import os

import httpx

from .config import TICKET_SERVICE_URL

logger = logging.getLogger("app.ticket_client")

TIMEOUT_SECONDS = 3.0

# 意图 -> 工单分类（category 仅用于工作台筛选/统计，状态流转完全由 Java 状态机负责）
CATEGORY_BY_INTENT = {
    "order": "order",
    "logistics": "logistics",
    "refund": "refund",
    "escalate": "complaint",
    "knowledge": "knowledge",
    "fallback": "general",
}

PRIORITY_BY_INTENT = {
    "escalate": "high",
    "refund": "normal",
    "order": "normal",
    "logistics": "normal",
    "knowledge": "normal",
    "fallback": "normal",
}

INTENT_LABELS = {
    "order": "订单咨询",
    "logistics": "物流咨询",
    "refund": "退换货/退款",
    "escalate": "投诉/转人工",
    "knowledge": "规则咨询",
    "fallback": "人工协助",
}

STATUS_LABELS = {
    "NEW": "新建/待处理",
    "PROCESSING": "处理中",
    "ESCALATED": "已升级（超时待人工）",
    "RESOLVED": "已解决",
    "REFUNDED": "已退款",
    "CLOSED": "已关闭",
}


def service_url() -> str:
    """每次调用实时读环境变量，便于测试覆盖/临时切换（默认取 config 值）。"""
    return (os.getenv("TICKET_SERVICE_URL") or TICKET_SERVICE_URL).rstrip("/")


class TicketServiceError(RuntimeError):
    """Java 工单服务不可达或返回非 2xx。"""


def is_available() -> bool:
    """健康探测：GET /tickets 返回 200 即认为可用。"""
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            resp = client.get(f"{service_url()}/tickets")
            return resp.status_code == 200
    except Exception as exc:
        logger.warning("工单服务不可达: %s", exc)
        return False


def create_ticket(
    session_id: str,
    title: str,
    category: str = "general",
    priority: str = "normal",
) -> dict:
    """POST /tickets 创建工单；成功返回 Java 返回的 ticket JSON（id/status/...）。"""
    url = f"{service_url()}/tickets"
    payload = {
        "sessionId": (session_id or "").strip(),
        "title": (title or "未命名工单").strip()[:80],
        "category": (category or "general").strip(),
        "priority": (priority or "normal").strip(),
    }
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            resp = client.post(url, json=payload)
    except Exception as exc:
        logger.warning("工单服务调用失败: %s", exc)
        raise TicketServiceError(f"工单服务不可达：{exc}") from exc
    if resp.status_code not in (200, 201):
        detail = resp.text[:200]
        logger.warning("建单失败 HTTP %s: %s", resp.status_code, detail)
        raise TicketServiceError(f"建单失败 HTTP {resp.status_code}: {detail}")
    return resp.json()


def list_tickets(session_id: str = None) -> list:
    """GET /tickets（可按 session_id 过滤；供页面/工单状态轮询）。"""
    url = f"{service_url()}/tickets"
    params = {"sessionId": session_id} if session_id else None
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.warning("查询工单失败: %s", exc)
        raise TicketServiceError(f"工单服务不可达：{exc}") from exc


def status_label(status: str) -> str:
    """Java 状态 -> 中文标签（未知状态原样返回，避免前端崩溃）。"""
    return STATUS_LABELS.get(status or "", status or "未知")


def transition_ticket(ticket_id: int, to_status: str) -> dict:
    """POST /tickets/{id}/transition 流转工单（非法跳转 Java 返回 409，这里抛异常）。"""
    url = f"{service_url()}/tickets/{ticket_id}/transition"
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            resp = client.post(url, json={"to": to_status})
    except Exception as exc:
        logger.warning("工单流转调用失败: %s", exc)
        raise TicketServiceError(f"工单服务不可达：{exc}") from exc
    if resp.status_code not in (200, 201):
        detail = resp.text[:200]
        logger.warning("流转失败 HTTP %s: %s", resp.status_code, detail)
        raise TicketServiceError(f"流转失败 HTTP {resp.status_code}: {detail}")
    return resp.json()
