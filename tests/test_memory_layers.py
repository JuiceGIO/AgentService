"""三层记忆：工作记忆（最近消息）/ 摘要记忆（超阈值压缩）/ 长期偏好（用户级）。"""

import asyncio
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401

from app.session_store import RECENT_KEEP, SUMMARY_TRIGGER, SessionStore  # noqa: E402


class MemoryLayerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = SessionStore(
            redis_url="redis://127.0.0.1:1/0",  # 故意指向不可用端口：验证 Redis 缺失时仍可工作
            data_file=Path(self._tmp.name) / "sessions.json",
        )
        self.addCleanup(self._tmp.cleanup)

    def test_working_memory_keeps_recent_and_summarizes_old(self):
        async def flow():
            for i in range(SUMMARY_TRIGGER + 4):
                await self.store.append("s1", "user", f"第{i}个问题")
                await self.store.append("s1", "assistant", f"第{i}个回答")
            return await self.store.build_context("s1")

        ctx = asyncio.run(flow())
        self.assertTrue(ctx["summary"].startswith("早期共"))
        self.assertLessEqual(len(ctx["recent"]), RECENT_KEEP)
        # 摘要落库：下次读取不需要重新计算
        again = asyncio.run(self.store.build_context("s1"))
        self.assertEqual(again["summary"], ctx["summary"])

    def test_short_session_has_no_summary(self):
        async def flow():
            await self.store.append("s2", "user", "这个能退吗")
            await self.store.append("s2", "assistant", "可以")
            return await self.store.build_context("s2")

        ctx = asyncio.run(flow())
        self.assertEqual(ctx["summary"], "")
        self.assertEqual(len(ctx["recent"]), 2)

    def test_profile_is_per_user_and_persisted(self):
        async def flow():
            await self.store.set_profile("u-1001", "回访偏好", "不要电话回访")
            await self.store.set_profile("u-2002", "会员等级", "金卡")
            return self.store.get_profile("u-1001"), self.store.get_profile("u-2002")

        p1, p2 = asyncio.run(flow())
        self.assertEqual(p1, {"回访偏好": "不要电话回访"})
        self.assertEqual(p2, {"会员等级": "金卡"})
        # 重新加载（模拟重启）后偏好仍在，且不会串号
        reloaded = SessionStore(
            redis_url="redis://127.0.0.1:1/0",
            data_file=Path(self._tmp.name) / "sessions.json",
        )
        self.assertEqual(reloaded.get_profile("u-1001").get("回访偏好"), "不要电话回访")
        self.assertNotIn("会员等级", reloaded.get_profile("u-1001"))

    def test_context_note_carries_identity_summary_and_profile(self):
        async def flow():
            await self.store.set_user("s3", "u-1001")
            await self.store.set_profile("u-1001", "常用收货城市", "深圳")
            for i in range(SUMMARY_TRIGGER + 2):
                await self.store.append("s3", "user", f"问题{i}")
            ctx = await self.store.build_context("s3")
            return self.store.build_context_note(ctx)

        note = asyncio.run(flow())
        self.assertIn("u-1001", note)
        self.assertIn("常用收货城市=深圳", note)
        self.assertIn("会话摘要", note)

    def test_session_user_binding(self):
        async def flow():
            await self.store.set_user("s4", "u-2002")
            return self.store.get_user("s4"), self.store.get_user("s-unknown")

        bound, unknown = asyncio.run(flow())
        self.assertEqual(bound, "u-2002")
        self.assertEqual(unknown, "")


if __name__ == "__main__":
    unittest.main()
