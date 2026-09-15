"""自动建单验收：转人工/投诉 → Java 工单自动创建 + 降级路径。

运行前需先启动 java-ticket-service（http://127.0.0.1:8080），
未启动时自动验证“优雅降级”分支并以警告提示。
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.react import run_agent_sync  # noqa: E402
from app.ticket_client import TicketServiceError, create_ticket, is_available  # noqa: E402


def _ticket_msg(result: dict):
    return [m for m in result["messages"] if m.get("role") == "ticket"]


def main():
    fails = []
    java_up = is_available()
    print(f"[1] Java 工单服务可用: {java_up}")

    if java_up:
        # 桥接直连建单
        try:
            t = create_ticket("day12-direct", "[直连测试] 自动建单", "complaint", "high")
            assert t.get("status") == "NEW", t
            print(f"[2] 直连建单 OK -> id={t['id']} status={t['status']} sessionId={t.get('sessionId')}")
        except TicketServiceError as exc:
            fails.append(f"直连建单失败: {exc}")

        # 投诉对话 → 自动建单（走完整 Agent 链路）
        res = run_agent_sync("我要投诉，客服态度太差了，一直不处理", session_id="day12-e2e")
        print(f"[3] 投诉对话回复: {res['reply']}")
        msgs = _ticket_msg(res)
        if not msgs or not msgs[-1].get("ticket"):
            fails.append("投诉对话未自动建单")
        else:
            tk = msgs[-1]["ticket"]
            print(f"    工单消息 OK -> id={tk['id']} category={tk.get('category')} status={tk.get('status')}")
        if res.get("escalated") is not True:
            fails.append("投诉对话 escalated 应为 True")
        if res.get("ticket", {}).get("ok") is not True:
            fails.append("返回体 ticket.ok 应为 True")

        # 可自动处理的退款不应建单
        res2 = run_agent_sync("这个能退吗", session_id="day12-e2e")
        if res2.get("escalated") is True or _ticket_msg(res2):
            fails.append("可自动处理的退款不应转人工/建单")
        else:
            print("[4] 可自动处理退款不建单 OK")

    # Java 不可用降级路径（指向本机未监听端口）
    os.environ["TICKET_SERVICE_URL"] = "http://127.0.0.1:59999"
    try:
        res3 = run_agent_sync("我要投诉", session_id="day12-degrade")
        msgs3 = _ticket_msg(res3)
        ok_degrade = (
            res3.get("escalated") is True
            and msgs3
            and msgs3[-1].get("error")
            and res3.get("ticket", {}).get("ok") is False
            and "工单" in res3["reply"]
        )
        print(f"[5] Java 不可用降级 OK: {ok_degrade}")
        print(f"    回复: {res3['reply']}")
        if not ok_degrade:
            fails.append("Java 不可用时降级分支不符合预期")
    finally:
        os.environ.pop("TICKET_SERVICE_URL", None)

    if not java_up:
        print("警告：Java 服务未启动，仅验证了降级路径；请先启动 Java 再复测建单主链路。")

    if fails:
        print("\n失败项：")
        for f in fails:
            print(" -", f)
        sys.exit(1)
    print("\n自动建单验收通过。")


if __name__ == "__main__":
    main()
