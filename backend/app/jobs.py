"""可演示的异步任务：与 Java 工单服务联动的批量建单任务。"""

import time


def _noop(progress, steps: int = 5, interval: float = 0.2):
    """自测用短任务：演示 queued/running/progress/succeeded 全生命周期。"""
    if steps < 1 or steps > 100:
        raise ValueError("steps 需在 1-100")
    for i in range(1, steps + 1):
        time.sleep(interval)
        progress(int(i / steps * 100), f"模拟处理中 {i}/{steps}")
    return {"steps": steps}


def batch_create_tickets(progress, count: int = 5, title: str = "售后回访", category: str = "complaint",
                         priority: str = "normal", session_prefix: str = "day15-batch"):
    """批量异步建单：逐张调 Java 工单服务，进度实时回写。"""
    from .ticket_client import create_ticket

    count = int(count)
    if count < 1 or count > 100:
        raise ValueError("count 需在 1-100")
    if not title:
        raise ValueError("title 不能为空")

    created = []
    for i in range(1, count + 1):
        ticket = create_ticket(
            f"{session_prefix}-{i}",
            f"[批量] {title} {i}/{count}",
            category=category,
            priority=priority,
        )
        created.append(ticket["id"])
        progress(int(i / count * 100), f"已创建工单 {i}/{count}（#{ticket['id']}）")
        time.sleep(0.4)  # 放慢一点，让进度可见
    return {"created": len(created), "ticket_ids": created}


TASK_TYPES = {
    "noop": _noop,
    "batch_tickets": batch_create_tickets,
}


# ---- 延迟任务（MQ 延迟队列）----


def _echo_delayed(payload: dict) -> dict:
    """纯逻辑延迟任务：模拟耗时处理，验收调度/兜底用。"""
    steps = int(payload.get("steps", 2))
    interval = float(payload.get("interval", 0.2))
    if steps < 1 or steps > 100:
        raise ValueError("steps 需在 1-100")
    time.sleep(interval * steps)
    return {"echo": payload.get("echo", "ok"), "steps": steps}


def follow_up_ticket(payload: dict) -> dict:
    """业务延迟任务：到点后调 Java 建一张售后回访工单（消息驱动的业务闭环）。"""
    from .ticket_client import create_ticket

    ticket = create_ticket(
        payload.get("session_id", "day16-followup"),
        payload.get("title", "延迟售后回访"),
        category=payload.get("category", "followup"),
        priority=payload.get("priority", "normal"),
    )
    return {"ticket_id": ticket["id"], "session_id": ticket["sessionId"], "status": ticket["status"]}


DELAYED_TYPES = {
    "echo_delayed": _echo_delayed,
    "follow_up_ticket": follow_up_ticket,
}
