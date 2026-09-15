import time
import unittest

import _path  # noqa: F401

from app.delayed_queue import DelayedScheduler


def echo(payload):
    return {"echo": payload.get("v")}


def boom(payload):
    raise RuntimeError("delayed boom")


HANDLERS = {"echo": echo, "boom": boom}


def wait_terminal(sched, job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = sched.get(job_id)
        if job and job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"delayed job {job_id} timeout")


class DelayedSchedulerTests(unittest.TestCase):
    def test_negative_delay_rejected(self):
        sched = DelayedScheduler(HANDLERS)
        with self.assertRaises(ValueError):
            sched.submit("echo", {"v": 1}, delay_seconds=-1)

    def test_unknown_type_rejected(self):
        sched = DelayedScheduler(HANDLERS)
        with self.assertRaises(KeyError):
            sched.submit("nope", {})

    def test_realtime_dispatch(self):
        sched = DelayedScheduler(HANDLERS)
        sched.start()
        job = sched.submit("echo", {"v": "rt"}, delay_seconds=0.1)
        done = wait_terminal(sched, job["id"])
        self.assertEqual(done["status"], "succeeded")
        self.assertEqual(done["result"], {"echo": "rt"})

    def test_sweep_fallback_without_dispatcher(self):
        sched = DelayedScheduler(HANDLERS)
        # 故意不 start()，只靠 sweep_due_once 兜底
        job = sched.submit("echo", {"v": "sweep"}, delay_seconds=0.05)
        time.sleep(0.2)
        self.assertEqual(sched.get(job["id"])["status"], "scheduled")
        swept = sched.sweep_due_once()
        done = sched.get(job["id"])
        self.assertEqual(swept, 1)
        self.assertEqual(done["status"], "succeeded")
        self.assertEqual(done["result"], {"echo": "sweep"})

    def test_failure_isolation(self):
        sched = DelayedScheduler(HANDLERS)
        sched.start()
        bad = sched.submit("boom", {}, delay_seconds=0.05)
        done_bad = wait_terminal(sched, bad["id"])
        self.assertEqual(done_bad["status"], "failed")
        good = sched.submit("echo", {"v": "after"}, delay_seconds=0.05)
        done_good = wait_terminal(sched, good["id"])
        self.assertEqual(done_good["status"], "succeeded")


if __name__ == "__main__":
    unittest.main()
