import time
import unittest

import _path  # noqa: F401

from app.task_queue import TaskQueue


def ok_job(progress, value=1):
    progress(50, "half")
    return value * 2


def bad_job(progress):
    raise ValueError("bad job")


def wait_terminal(queue, job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = queue.get(job_id)
        if job and job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"task {job_id} timeout")


class TaskQueueTests(unittest.TestCase):
    def test_lifecycle_success(self):
        q = TaskQueue()
        job = q.submit("test", ok_job, value=3)
        self.assertEqual(job["status"], "queued")
        done = wait_terminal(q, job["id"])
        self.assertEqual(done["status"], "succeeded")
        self.assertEqual(done["result"], 6)
        self.assertEqual(done["progress"], 100)

    def test_failure_and_isolation(self):
        q = TaskQueue()
        bad = q.submit("bad", bad_job)
        done_bad = wait_terminal(q, bad["id"])
        self.assertEqual(done_bad["status"], "failed")
        self.assertIn("bad job", done_bad["error"])

        good = q.submit("good", ok_job, value=1)
        done_good = wait_terminal(q, good["id"])
        self.assertEqual(done_good["status"], "succeeded")
        self.assertEqual(done_good["result"], 2)

    def test_get_and_list(self):
        q = TaskQueue()
        job = q.submit("test", ok_job, value=1)
        self.assertIsNotNone(q.get(job["id"]))
        wait_terminal(q, job["id"])
        self.assertEqual(len(q.list(limit=10)), 1)
        self.assertIsNone(q.get("not-exist"))


if __name__ == "__main__":
    unittest.main()
