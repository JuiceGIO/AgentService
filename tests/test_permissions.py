"""行级权限：订单归属校验、服务端身份注入、越权映射为 403。"""

import sys
import unittest
from pathlib import Path

import _path  # noqa: F401  （把 backend 加进 sys.path）

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_servers"))

from app.agent.tools import MCPToolRegistry, PermissionDenied, raise_if_forbidden  # noqa: E402


class ToolOwnershipTests(unittest.TestCase):
    def test_order_owner_known_and_unknown(self):
        from mock_data import order_owner

        self.assertEqual(order_owner("ORD-20260828001"), "u-1001")
        self.assertEqual(order_owner("ord-20260829002"), "u-1001")  # 大小写不敏感
        self.assertEqual(order_owner("ORD-20260831003"), "u-2002")
        self.assertEqual(order_owner("ORD-NOT-EXIST"), "")

    def test_order_server_forbidden_logic(self):
        import order_server

        denied = order_server._forbidden("ORD-20260831003", "u-1001")
        self.assertIsNotNone(denied)
        self.assertEqual(denied["code"], 403)
        self.assertEqual(denied["error"], "forbidden")
        # 归属人自己访问、以及未绑定身份时（内部调用）不拦
        self.assertIsNone(order_server._forbidden("ORD-20260831003", "u-2002"))
        self.assertIsNone(order_server._forbidden("ORD-20260828001", ""))

    def test_registry_overrides_actor_from_model(self):
        """模型即使自己声明 actor_id，也会被服务端绑定的身份覆盖。"""
        registry = MCPToolRegistry(actor_id="u-1001")
        payload = registry.build_payload({"order_id": "ORD-20260828001", "actor_id": "u-2002"})
        self.assertEqual(payload["actor_id"], "u-1001")
        # 未绑定身份的注册表不注入 actor_id（保持内部调用兼容）
        self.assertNotIn("actor_id", MCPToolRegistry().build_payload({"order_id": "x"}))

    def test_forbidden_result_maps_to_permission_denied(self):
        with self.assertRaises(PermissionDenied):
            raise_if_forbidden({"error": "forbidden", "code": 403, "detail": "该订单不属于当前用户"})
        # 正常结果原样返回
        self.assertEqual(raise_if_forbidden({"found": True})["found"], True)

    def test_chat_returns_403_on_permission_denied(self):
        """API 层：越权时 /api/chat 返回 403（不暴露资源是否存在）。"""
        from fastapi.testclient import TestClient

        from app import main as main_mod

        client = TestClient(main_mod.app)
        original = main_mod.run_agent_sync

        def boom(*args, **kwargs):
            raise PermissionDenied("该订单不属于当前用户，已拒绝访问（行级权限）")

        main_mod.run_agent_sync = boom
        try:
            resp = client.post(
                "/api/chat",
                json={"message": "我的订单到哪了", "session_id": "t-403", "user_id": "u-2002"},
            )
            self.assertEqual(resp.status_code, 403)
            self.assertIn("不属于当前用户", resp.json()["detail"])
        finally:
            main_mod.run_agent_sync = original


if __name__ == "__main__":
    unittest.main()
