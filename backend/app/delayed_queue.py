"""轻量 MQ 延迟队列。

三层设计：
1. 消息驱动：submit(delay_seconds) 入队，调度线程到点投递并执行 handler；
2. 定时兜底：独立 sweep 线程每 N 秒扫描“已到期但仍是 scheduled”的任务重新投递，
   即使调度线程卡死/漏发也能恢复（sweep_due_once() 可直接用于测试与运维）；
3. 降级：纯进程内实现，不依赖 Redis/外部 MQ；未来接外部 MQ 只替换 transport，
   Job 状态模型（scheduled/dispatching/succeeded/failed）保持不变。
"""

import heapq
import threading
import time
import uuid


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class DelayedScheduler:
    def __init__(self, handlers: dict = None, sweep_interval: float = 5.0):
        self.handlers = handlers or {}
        self.sweep_interval = sweep_interval
        self._jobs = {}
        self._heap = []  # (due_at, seq, job_id)
        self._seq = 0
        self._cv = threading.Condition()
        self._dispatch_thread = None
        self._sweep_thread = None
        self._started = False

    def start(self):
        """启动调度线程 + 兜底扫描线程（幂等）。"""
        with self._cv:
            if self._started:
                return
            self._started = True
            self._dispatch_thread = threading.Thread(
                target=self._dispatch_loop, daemon=True, name="delayed-dispatcher"
            )
            self._sweep_thread = threading.Thread(
                target=self._sweep_loop, daemon=True, name="delayed-sweeper"
            )
            self._dispatch_thread.start()
            self._sweep_thread.start()

    def submit(self, job_type: str, payload: dict = None, delay_seconds: float = 0.0) -> dict:
        delay_seconds = float(delay_seconds)
        if delay_seconds < 0:
            raise ValueError("delay_seconds 不能为负")
        if job_type not in self.handlers:
            raise KeyError(f"未知延迟任务类型：{job_type}")
        now = time.time()
        with self._cv:
            self._seq += 1
            job_id = uuid.uuid4().hex[:12]
            job = {
                "id": job_id,
                "type": job_type,
                "status": "scheduled",
                "delay_seconds": round(delay_seconds, 2),
                "due_at": _now(),
                "due_epoch": now + delay_seconds,
                "created_at": _now(),
                "updated_at": _now(),
                "message": f"已入队，延迟 {delay_seconds:.0f}s 投递",
                "result": None,
                "error": None,
                "payload": payload or {},
            }
            self._jobs[job_id] = job
            heapq.heappush(self._heap, (job["due_epoch"], self._seq, job_id))
            self._cv.notify_all()
        return dict(job)

    def get(self, job_id: str):
        with self._cv:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def list(self, limit: int = 20) -> list:
        with self._cv:
            jobs = sorted(self._jobs.values(), key=lambda j: j["created_at"], reverse=True)
            return [dict(j) for j in jobs[:limit]]

    def sweep_due_once(self) -> int:
        """定时兜底：投递所有已到期但仍 scheduled 的任务（幂等，可测试/运维手动调用）。"""
        with self._cv:
            now = time.time()
            due = [
                job_id
                for job_id, job in self._jobs.items()
                if job["status"] == "scheduled" and job["due_epoch"] <= now
            ]
            for job_id in due:
                self._jobs[job_id]["status"] = "dispatching"
                self._jobs[job_id]["updated_at"] = _now()
                self._jobs[job_id]["message"] = "兜底扫描投递"
        count = 0
        for job_id in due:
            self._run(job_id)
            count += 1
        return count

    def _dispatch_loop(self):
        while True:
            with self._cv:
                while True:
                    if not self._heap:
                        self._cv.wait(timeout=1.0)
                        continue
                    due, _, job_id = self._heap[0]
                    now = time.time()
                    if due > now:
                        self._cv.wait(timeout=max(0.05, due - now))
                        continue
                    heapq.heappop(self._heap)
                    job = self._jobs.get(job_id)
                    if job and job["status"] == "scheduled":
                        job["status"] = "dispatching"
                        job["updated_at"] = _now()
                        job["message"] = "到点投递，执行中"
                        break
                    # 已被 sweep 兜底执行或已删除：丢弃过期堆顶继续
            self._run(job_id)

    def _sweep_loop(self):
        while True:
            time.sleep(self.sweep_interval)
            try:
                self.sweep_due_once()
            except Exception:
                pass  # 兜底失败下一轮再试，不让扫描线程退出

    def _run(self, job_id: str):
        with self._cv:
            job = self._jobs.get(job_id)
            if not job:
                return
            handler = self.handlers.get(job["type"])
            payload = job["payload"]
        try:
            if handler is None:
                raise KeyError(f"handler 不存在：{job['type']}")
            result = handler(payload)
            with self._cv:
                job = self._jobs.get(job_id)
                if job:
                    job.update(
                        status="succeeded",
                        message="执行完成",
                        result=result,
                        updated_at=_now(),
                    )
        except Exception as exc:
            with self._cv:
                job = self._jobs.get(job_id)
                if job:
                    job.update(
                        status="failed",
                        message="执行失败",
                        error=str(exc),
                        updated_at=_now(),
                    )


_default_queue = None


def get_delayed_queue(handlers: dict = None) -> DelayedScheduler:
    global _default_queue
    if _default_queue is None:
        _default_queue = DelayedScheduler(handlers=handlers or {})
        _default_queue.start()
    return _default_queue
