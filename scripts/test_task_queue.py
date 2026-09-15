"""异步任务队列验收：
1) noop 任务全生命周期（queued→running→succeeded，进度 100）
2) batch_tickets 批量异步建单（需要 Java 8080 运行）并回查 Java 工单
3) 失败路径（count=0）任务标记 failed 且带 error，不影响后续任务
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.jobs import _noop, batch_create_tickets  # noqa: E402
from app.task_queue import TaskQueue  # noqa: E402
from app.ticket_client import is_available, list_tickets  # noqa: E402


def wait_job(queue: TaskQueue, job_id: str, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = queue.get(job_id)
        if job and job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.2)
    raise TimeoutError(f"任务 {job_id} 超时未结束")


def main():
    queue = TaskQueue()
    fails = []

    # 1) 生命周期 + 进度
    j1 = queue.submit("noop", _noop, steps=5, interval=0.1)
    r1 = wait_job(queue, j1["id"])
    if r1["status"] != "succeeded" or r1["progress"] != 100 or r1["result"].get("steps") != 5:
        fails.append(f"noop 任务异常: {r1}")
    else:
        print(f"[1] noop 生命周期 OK（{r1['status']} / {r1['progress']}% / result={r1['result']}）")

    # 2) 批量异步建单（Java 在跑时验证真实闭环）
    if is_available():
        prefix = "day15-batch"
        j2 = queue.submit("batch_tickets", batch_create_tickets, count=3,
                          title="售后回访", session_prefix=prefix)
        r2 = wait_job(queue, j2["id"], timeout=90)
        if r2["status"] != "succeeded":
            fails.append(f"批量建单任务失败: {r2.get('error')}")
        else:
            ids = r2["result"]["ticket_ids"]
            ok = len(ids) == 3
            for tid in ids:
                found = list_tickets(session_id=f"{prefix}-{ids.index(tid) + 1}")
                if not any(t["id"] == tid for t in found):
                    ok = False
            if not ok:
                fails.append(f"批量建单结果与 Java 不一致: {r2}")
            else:
                print(f"[2] 批量异步建单 OK（3 张工单 #{','.join(str(i) for i in ids)}，Java 可回查）")
    else:
        print("[2] Java 未启动，跳过批量建单闭环（任务队列本身已在 [1] 验证）")

    # 3) 失败路径
    j3 = queue.submit("batch_tickets", batch_create_tickets, count=0)
    r3 = wait_job(queue, j3["id"], timeout=30)
    if r3["status"] != "failed" or not r3.get("error"):
        fails.append(f"失败路径未按预期标记: {r3}")
    else:
        print(f"[3] 失败路径 OK（failed + error={r3['error'][:60]}）")

    # 4) 失败不影响后续任务
    j4 = queue.submit("noop", _noop, steps=2, interval=0.1)
    r4 = wait_job(queue, j4["id"])
    if r4["status"] != "succeeded":
        fails.append("失败任务后队列未恢复")
    else:
        print("[4] 失败隔离 OK（后续任务正常执行）")

    if fails:
        print("\n失败项：")
        for f in fails:
            print(" -", f)
        sys.exit(1)
    print("\n异步任务队列验收通过。")


if __name__ == "__main__":
    main()
