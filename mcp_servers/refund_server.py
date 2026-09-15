"""退款/退换货资格与流程 MCP server（模拟）。"""

from datetime import date

from mcp.server.fastmcp import FastMCP

from mock_data import ORDERS, REFUND_RULES, TODAY

mcp = FastMCP("refund-server")

# 订单号 -> (签收日期, 是否质量问题)
SIGNED_INFO = {
    "ORD-20260829002": (date(2026, 8, 29), False),
}

REFUND_FLOWS = {
    "退货退款": ["填写退货申请（原因/凭证）", "商家审核（24 小时内）", "寄回商品（7 天内）", "仓库验收", "退款原路返回（1-3 个工作日）"],
    "换货": ["填写换货申请", "商家审核（24 小时内）", "寄回商品", "仓库验收", "发出新商品"],
    "仅退款": ["填写仅退款申请", "商家审核（24 小时内）", "退款原路返回（1-3 个工作日）"],
    "取消订单": ["确认取消订单", "系统自动退款", "退款原路返回（1-3 个工作日）"],
}


def _find_order(order_id: str):
    order_id = order_id.strip().upper()
    return next((o for o in ORDERS if o["order_id"].upper() == order_id), None)


@mcp.tool()
def check_refund_eligibility(order_id: str) -> dict:
    """判断订单是否支持退款/退货/换货：根据订单状态、签收天数和是否质量问题，给出结论与运费承担规则。"""
    order = _find_order(order_id)
    if not order:
        return {"found": False, "message": f"未找到订单 {order_id}，请核对订单号。"}

    status = order["status_code"]
    if status == "pending_shipment":
        return {
            "found": True, "order_id": order_id, "eligible": True, "refund_type": "仅退款/取消订单",
            "reason": "订单未发货，可取消订单并全额退款。",
            "shipping_fee": "无运费", "refund_time": REFUND_RULES["退款到账"],
        }
    if status == "shipping":
        return {
            "found": True, "order_id": order_id, "eligible": "需拦截", "refund_type": "物流拦截后退款",
            "reason": "订单运输中，不支持直接退货；可申请物流拦截，拦截成功后退款。",
            "shipping_fee": "拦截不产生费用", "refund_time": REFUND_RULES["退款到账"],
        }

    signed_date, quality_issue = SIGNED_INFO.get(order_id, (TODAY, False))
    days = (TODAY - signed_date).days
    if quality_issue and days <= 15:
        return {
            "found": True, "order_id": order_id, "eligible": True, "refund_type": "质量问题退换货",
            "reason": f"签收 {days} 天，属质量问题，可退货或换货。",
            "shipping_fee": "卖家承担", "refund_time": REFUND_RULES["退款到账"],
        }
    if days <= 7:
        return {
            "found": True, "order_id": order_id, "eligible": True, "refund_type": "七天无理由退货",
            "reason": f"签收 {days} 天，未拆封、不影响二次销售可申请七天无理由退货。",
            "shipping_fee": "买家承担（有运费险按保险赔付）", "refund_time": REFUND_RULES["退款到账"],
        }
    return {
        "found": True, "order_id": order_id, "eligible": False, "refund_type": "不支持退换",
        "reason": f"已签收 {days} 天，超出 7 天无理由期限且无质量问题记录。",
        "shipping_fee": "-", "refund_time": "-",
    }


@mcp.tool()
def get_refund_flow(refund_type: str) -> dict:
    """获取退款/退换货流程步骤：退货退款 / 换货 / 仅退款 / 取消订单。"""
    key = refund_type.strip()
    if key not in REFUND_FLOWS:
        return {"found": False, "available": list(REFUND_FLOWS), "message": f"不支持的退款类型：{key}"}
    return {"found": True, "refund_type": key, "steps": REFUND_FLOWS[key]}


if __name__ == "__main__":
    mcp.run()
