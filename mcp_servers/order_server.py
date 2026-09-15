"""订单查询 MCP server（模拟）。"""

from mcp.server.fastmcp import FastMCP

from mock_data import ORDERS

mcp = FastMCP("order-server")


def _find_order(order_id: str):
    order_id = order_id.strip().upper()
    return next((o for o in ORDERS if o["order_id"].upper() == order_id), None)


@mcp.tool()
def query_order(order_id: str) -> dict:
    """按订单号查询订单：状态、金额、商品明细、下单时间、收货地址（脱敏）。"""
    order = _find_order(order_id)
    if not order:
        return {"found": False, "message": f"未找到订单 {order_id}，请核对订单号。"}
    return {"found": True, **order}


@mcp.tool()
def list_orders_by_phone(phone: str) -> dict:
    """按手机号查询名下订单列表：订单号/状态/金额/下单时间。"""
    phone = phone.strip()
    orders = [o for o in ORDERS if o["phone"] == phone]
    if not orders:
        return {"found": False, "message": f"手机号 {phone} 下没有订单。"}
    return {
        "found": True,
        "orders": [
            {"order_id": o["order_id"], "status": o["status"], "amount": o["amount"], "created_at": o["created_at"]}
            for o in orders
        ],
    }


if __name__ == "__main__":
    mcp.run()
