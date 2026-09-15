"""SLA 超时升级验收：建单 → 等 @Scheduled 自动升级 → 校验留痕 → 人工收口。

前置：先启动 java-ticket-service（默认 new SLA=30s、扫描 10s），
运行：.\backend\.venv\Scripts\python.exe scripts\test_sla_escalation.py
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.ticket_client import (  # noqa: E402
    TicketServiceError,
    create_ticket,
    is_available,
    list_tickets,
    transition_ticket,
)

WAIT_SECONDS = 80  # new SLA=30 + 扫描 10，给足余量


def main():
    fails = []
    if not is_available():
        print("Java 工单服务不可用：请先启动 java-ticket-service（java -jar target/ticket-service-0.1.0.jar）")
        sys.exit(1)

    t = create_ticket("day13-sla", "超时升级验收", "complaint", "high")
    tid = t["id"]
    print(f"[1] 建单 OK -> id={tid} status={t['status']}（等 SLA 超时自动升级）")

    seen = None
    deadline = time.time() + WAIT_SECONDS
    while time.time() < deadline:
        cur = next((x for x in list_tickets() if x["id"] == tid), None)
        if cur:
            status = cur["status"]
            actions = cur.get("actions", [])
            print(f"    当前状态: {status} | 留痕: {actions[-1] if actions else '-'}")
            if status == "ESCALATED":
                seen = cur
                break
        time.sleep(5)

    if not seen:
        fails.append(f"工单 {tid} 在 {WAIT_SECONDS}s 内未自动升级")
    else:
        if not any("ESCALATE_TIMEOUT" in a for a in seen.get("actions", [])):
            fails.append("升级缺少 ESCALATE_TIMEOUT 留痕")
        else:
            print("[2] 超时自动升级 OK（ESCALATED + 留痕）")

        try:
            resolved = transition_ticket(tid, "RESOLVED")
            if resolved["status"] != "RESOLVED":
                fails.append("人工收口 ESCALATED -> RESOLVED 失败")
            else:
                print("[3] 人工收口 OK -> RESOLVED（留痕:", resolved.get("actions", [])[-1], "）")
        except TicketServiceError as exc:
            fails.append(f"人工收口失败: {exc}")

    if fails:
        print("\n失败项：")
        for f in fails:
            print(" -", f)
        sys.exit(1)
    print("\n超时升级验收通过。")


if __name__ == "__main__":
    main()
