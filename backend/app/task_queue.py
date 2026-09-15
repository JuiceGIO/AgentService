"""轻量异步任务队列 + 进度查询。

设计：单 worker 线程串行消费 queue.Queue，任务状态/进度/结果集中在一个带锁字典；
对调用方（HTTP 接口）完全异步——POST 立即返回 task_id，GET 查进度。
Job 模型（status/progress/message/result/error）与 的 MQ 延迟队列同构，便于替换。
"""

import threading
import time
import uuid
from queue import Queue


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class TaskQueue:
    def __init__(self):
        self._jobs = {}
        self._lock = threading.Lock()
        self._queue = Queue()
        self._started = False

    def submit(self, job_type: str, fn, **kwargs) -> dict:
        job = {
            "id": uuid.uuid4().hex[:12],
            "type": job_type,
            "status": "queued",
            "progress": 0,
            "message": "排队中",
            "result": None,
            "error": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        with self._lock:
            self._jobs[job["id"]] = job
            if not self._started:
                self._started = True
                worker = threading.Thread(target=self._run_loop, daemon=True, name="task-worker")
                worker.start()
        self._queue.put((job["id"], fn, kwargs))
        return dict(job)

    def get(self, job_id: str):
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def list(self, limit: int = 20) -> list:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j["updated_at"], reverse=True)
            return [dict(j) for j in jobs[:limit]]

    def _update(self, job_id: str, **changes):
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.update(changes)
                job["updated_at"] = _now()

    def _run_loop(self):
        while True:
            job_id, fn, kwargs = self._queue.get()
            self._update(job_id, status="running", progress=1, message="开始执行")
            try:
                result = fn(self._progress_cb(job_id), **kwargs)
                self._update(job_id, status="succeeded", progress=100, message="完成", result=result)
            except Exception as exc:
                self._update(job_id, status="failed", error=str(exc), message="执行失败")

    def _progress_cb(self, job_id: str):
        def report(percent: int, message: str):
            self._update(job_id, progress=max(0, min(100, int(percent))), message=message)

        return report


_default_queue = None


def get_task_queue() -> TaskQueue:
    global _default_queue
    if _default_queue is None:
        _default_queue = TaskQueue()
    return _default_queue
