"""MCP 客户端验证：连接四个业务工具 server，列出工具并调用样例，全部通过才算 完成。"""

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

MCP_DIR = Path(__file__).resolve().parent

SERVERS = [
    ("order-server", MCP_DIR / "order_server.py", [
        ("query_order", {"order_id": "ORD-20260828001"}),
        ("list_orders_by_phone", {"phone": "13800001234"}),
    ]),
    ("logistics-server", MCP_DIR / "logistics_server.py", [
        ("query_logistics", {"order_id": "ORD-20260828001"}),
    ]),
    ("refund-server", MCP_DIR / "refund_server.py", [
        ("check_refund_eligibility", {"order_id": "ORD-20260829002"}),
        ("get_refund_flow", {"refund_type": "退货退款"}),
    ]),
    ("knowledge-server", MCP_DIR / "knowledge_server.py", [
        ("search_knowledge", {"query": "退货运费谁出", "top_k": 2}),
    ]),
]


async def run_server(name: str, server_path: Path, cases: list):
    params = StdioServerParameters(command=sys.executable, args=[str(server_path)])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool_names = [t.name for t in tools.tools]
            print(f"[{name}] 工具: {', '.join(tool_names)}")
            for tool, args in cases:
                if tool not in tool_names:
                    raise RuntimeError(f"{name}: 缺少工具 {tool}")
                result = await session.call_tool(tool, args)
                text = "".join(c.text for c in result.content if getattr(c, "type", "") == "text")
                try:
                    obj = json.loads(text)
                    print(f"  -> {tool}: " + json.dumps(obj, ensure_ascii=False)[:240])
                except Exception:
                    print(f"  -> {tool}: " + text[:240])


async def main():
    for name, path, cases in SERVERS:
        await run_server(name, path, cases)
    print("\nMCP 验证通过：4 个 server，全部工具可调用。")


if __name__ == "__main__":
    asyncio.run(main())
