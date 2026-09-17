"""物流查询 MCP server（模拟）。"""

from mcp.server.fastmcp import FastMCP

from mock_data import LOGISTICS, order_owner

mcp = FastMCP("logistics-server")


@mcp.tool()
def query_logistics(order_id: str, actor_id: str = "") -> dict:
    """按订单号查询物流：承运商、运单号、轨迹节点、预计送达。

    actor_id 由服务端注入用于行级权限校验，业务调用无需传。
    """
    order_id = order_id.strip().upper()
    owner = order_owner(order_id)
    if owner and actor_id and owner != actor_id:
        return {
            "error": "forbidden",
            "code": 403,
            "order_id": order_id,
            "detail": "该订单不属于当前用户，已拒绝访问（行级权限）",
        }
    info = LOGISTICS.get(order_id)
    if not info:
        return {"found": False, "message": f"未找到订单 {order_id} 的物流信息。"}
    return {"found": True, "order_id": order_id, **info}


if __name__ == "__main__":
    mcp.run()
