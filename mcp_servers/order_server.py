"""订单查询 MCP server（模拟）。"""

from mcp.server.fastmcp import FastMCP

from mock_data import ORDERS, order_owner

mcp = FastMCP("order-server")


def _find_order(order_id: str):
    order_id = order_id.strip().upper()
    return next((o for o in ORDERS if o["order_id"].upper() == order_id), None)


def _forbidden(order_id: str, actor_id: str) -> dict | None:
    """行级权限：订单不属于当前身份且身份非空时返回 403 结果，否则返回 None。

    actor_id 由客户端（Agent 层）在调用时注入，并覆盖模型传入的任何值——
    模型无法通过声明身份来越权访问别人的订单。
    """
    owner = order_owner(order_id)
    if not owner or not actor_id or owner == actor_id:
        return None
    return {
        "error": "forbidden",
        "code": 403,
        "order_id": order_id,
        "detail": "该订单不属于当前用户，已拒绝访问（行级权限）",
    }


@mcp.tool()
def query_order(order_id: str, actor_id: str = "") -> dict:
    """按订单号查询订单：状态、金额、商品明细、下单时间、收货地址（脱敏）。

    actor_id 由服务端注入用于行级权限校验，业务调用无需传。
    """
    denied = _forbidden(order_id, actor_id)
    if denied:
        return denied
    order = _find_order(order_id)
    if not order:
        return {"found": False, "message": f"未找到订单 {order_id}，请核对订单号。"}
    payload = {k: v for k, v in order.items() if k != "owner_user_id"}
    return {"found": True, **payload}


@mcp.tool()
def list_orders_by_phone(phone: str, actor_id: str = "") -> dict:
    """按手机号查询名下订单列表：订单号/状态/金额/下单时间（只返回当前身份名下的订单）。"""
    phone = phone.strip()
    orders = [o for o in ORDERS if o["phone"] == phone]
    if actor_id:
        orders = [o for o in orders if o.get("owner_user_id", "") == actor_id]
    if not orders:
        return {"found": False, "message": f"手机号 {phone} 下没有当前用户名下的订单。"}
    return {
        "found": True,
        "orders": [
            {"order_id": o["order_id"], "status": o["status"], "amount": o["amount"], "created_at": o["created_at"]}
            for o in orders
        ],
    }


if __name__ == "__main__":
    mcp.run()
