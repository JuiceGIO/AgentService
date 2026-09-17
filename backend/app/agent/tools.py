"""MCP 工具注册表：按需连接业务工具 server，统一暴露给 Agent 调用。"""

import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .errors import PermissionDenied  # noqa: F401  （对外统一从 tools 暴露）

MCP_DIR = Path(__file__).resolve().parents[3] / "mcp_servers"


SERVERS = {
    "order-server": MCP_DIR / "order_server.py",
    "logistics-server": MCP_DIR / "logistics_server.py",
    "refund-server": MCP_DIR / "refund_server.py",
    "knowledge-server": MCP_DIR / "knowledge_server.py",
}


class MCPToolRegistry:
    """按工具名路由到对应 server；每次调用打开/关闭单个 stdio 会话。

    注意：mcp 客户端同时保持多个 stdio 会话时，anyio 清理会报
    “Attempted to exit cancel scope in a different task”，因此采用
    一次一个会话的生命周期（与 test_client.py 已验证的模式一致）。
    """

    def __init__(self, actor_id: str = ""):
        # 身份由服务端持有：调用工具时注入，并覆盖模型传入的 actor_id
        self.actor_id = actor_id or ""

    TOOL_SERVER = {
        "query_order": "order-server",
        "list_orders_by_phone": "order-server",
        "query_logistics": "logistics-server",
        "check_refund_eligibility": "refund-server",
        "get_refund_flow": "refund-server",
        "search_knowledge": "knowledge-server",
    }

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def tool_names(self) -> list:
        return sorted(self.TOOL_SERVER)

    def build_payload(self, args: dict) -> dict:
        """组装工具入参：服务端身份覆盖模型传入的 actor_id（行级权限的关键）。"""
        payload = dict(args or {})
        if self.actor_id:
            payload["actor_id"] = self.actor_id
        return payload

    async def call(self, tool_name: str, args: dict):
        server = self.TOOL_SERVER.get(tool_name)
        if not server:
            raise KeyError(f"未知工具：{tool_name}")
        payload = self.build_payload(args)
        path = SERVERS[server]
        params = StdioServerParameters(command=sys.executable, args=[str(path)])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, payload)
        text = "".join(c.text for c in result.content if getattr(c, "type", "") == "text")
        try:
            parsed = json.loads(text)
        except Exception:
            return {"raw": text}
        return raise_if_forbidden(parsed)


def raise_if_forbidden(parsed):
    """工具返回 403 时抛 PermissionDenied（由 API 层映射成 HTTP 403）。"""
    if isinstance(parsed, dict) and parsed.get("code") == 403:
        raise PermissionDenied(parsed.get("detail") or "无权访问该资源")
    return parsed
