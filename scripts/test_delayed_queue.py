"""MQ 延迟队列验收：
1) 消息驱动：echo_delayed 延迟 1s，到点自动执行 succeeded
2) 定时兜底：不启动调度线程，到期任务仍可被 sweep_due_once 投递执行（幂等）
3) 业务闭环：follow_up_ticket 延迟 4s 后自动调 Java 建回访工单
4) 失败隔离：handler 抛错任务标记 failed，后续任务不受影响
运行：.\backend\.venv\Scripts\python.exe scripts\test_delayed_queue.py
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.delayed_queue import DelayedScheduler  # noqa: E402
from app.jobs import DELAYED_TYPES  # noqa: E402
from app.ticket_client import is_available, list_tickets  # noqa: E402


def wait_job(scheduler: DelayedScheduler, job_id: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = scheduler.get(job_id)
        if job and job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.2)
    raise TimeoutError(f"延迟任务 {job_id} 超时未结束")


def main():
    fails = []

    # 1) 消息驱动：调度线程到点自动投递
    q1 = DelayedScheduler(DELAYED_TYPES, sweep_interval=30)
    q1.start()
    j1 = q1.submit("echo_delayed", {"echo": "day16-rt", "steps": 2}, delay_seconds=1)
    early = q1.get(j1["id"])
    if early["status"] != "scheduled":
        fails.append("延迟任务提交后应立即为 scheduled")
    r1 = wait_job(q1, j1["id"], timeout=10)
    if r1["status"] != "succeeded" or r1["result"].get("echo") != "day16-rt":
        fails.append(f"到点投递异常: {r1}")
    else:
        print(f"[1] 消息驱动 OK（延迟 1s → {r1['status']}，result={r1['result']}）")

    # 2) 定时兜底：调度线程没跑，到期任务靠 sweep 投递
    q2 = DelayedScheduler(DELAYED_TYPES, sweep_interval=30)
    # 故意不 start()
    j2 = q2.submit("echo_delayed", {"echo": "day16-sweep", "steps": 1}, delay_seconds=0.3)
    time.sleep(0.6)
    before = q2.get(j2["id"])
    if before["status"] != "scheduled":
        fails.append("兜底前任务不应已被执行")
    swept = q2.sweep_due_once()
    r2 = q2.get(j2["id"])
    if swept != 1 or r2["status"] != "succeeded" or r2["result"].get("echo") != "day16-sweep":
        fails.append(f"兜底投递异常: swept={swept} job={r2}")
    else:
        print("[2] 定时兜底 OK（调度线程未启动，sweep_due_once 仍能投递执行）")

    # 3) 业务闭环：延迟自动建 Java 回访工单
    if is_available():
        session = "day16-followup"
        j3 = q1.submit("follow_up_ticket", {"session_id": session, "title": "延迟售后回访"}, delay_seconds=4)
        before_count = len(list_tickets(session_id=session))
        r3 = wait_job(q1, j3["id"], timeout=20)
        after3 = list_tickets(session_id=session)
        new_id = (r3.get("result") or {}).get("ticket_id")
        created_ok = new_id and any(t["id"] == new_id for t in after3)
        if r3["status"] != "succeeded" or not created_ok:
            fails.append(f"延迟建单异常: before={before_count} after={len(after3)} new_id={new_id} job={r3}")
        else:
            print(f"[3] 业务延迟建单 OK（4s 后自动建工单 #{new_id}，Java 可查）")
    else:
        print("[3] Java 未启动，跳过延迟建单闭环")

    # 4) 失败隔离
    j4 = q1.submit("echo_delayed", {"steps": 200}, delay_seconds=0.1)  # steps>100 -> 抛错
    r4 = wait_job(q1, j4["id"], timeout=10)
    j5 = q1.submit("echo_delayed", {"echo": "after-fail", "steps": 1}, delay_seconds=0.1)
    r5 = wait_job(q1, j5["id"], timeout=10)
    if r4["status"] != "failed" or not r4.get("error") or r5["status"] != "succeeded":
        fails.append(f"失败隔离异常: fail={r4['status']} next={r5['status']}")
    else:
        print("[4] 失败隔离 OK（坏任务 failed，后续任务正常）")

    if fails:
        print("\n失败项：")
        for f in fails:
            print(" -", f)
        sys.exit(1)
    print("\nMQ 延迟队列验收通过。")


if __name__ == "__main__":
    main()
