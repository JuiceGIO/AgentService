"""物流查询 MCP server（模拟）。"""

from mcp.server.fastmcp import FastMCP

from mock_data import LOGISTICS

mcp = FastMCP("logistics-server")


@mcp.tool()
def query_logistics(order_id: str) -> dict:
    """按订单号查询物流：承运商、运单号、轨迹节点、预计送达。"""
    order_id = order_id.strip().upper()
    info = LOGISTICS.get(order_id)
    if not info:
        return {"found": False, "message": f"未找到订单 {order_id} 的物流信息。"}
    return {"found": True, "order_id": order_id, **info}


if __name__ == "__main__":
    mcp.run()
