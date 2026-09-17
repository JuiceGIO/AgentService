"""电商售后模拟数据：订单、物流、退款规则、知识库。后续可替换为真实服务。"""

import logging
from datetime import date

# 静默 MCP SDK 的 INFO 请求日志，避免验证输出被刷屏
for _name in ("mcp", "mcp.server", "mcp.server.lowlevel", "mcp.server.fastmcp", "mcp.shared"):
    logging.getLogger(_name).setLevel(logging.WARNING)

# 固定“今天”，保证判定结果可复现
TODAY = date(2026, 9, 1)

ORDERS = [
    {
        "order_id": "ORD-20260828001",
        "phone": "13800001234",
        "owner_user_id": "u-1001",
        "status": "运输中",
        "status_code": "shipping",
        "created_at": "2026-08-28 10:12:00",
        "amount": 4999.00,
        "items": [{"name": "小米15 手机 256G", "qty": 1, "price": 4999.00}],
        "address": "广东省深圳市南山区xx路1号（已脱敏）",
    },
    {
        "order_id": "ORD-20260829002",
        "phone": "13800001234",
        "owner_user_id": "u-1001",
        "status": "已签收",
        "status_code": "delivered",
        "created_at": "2026-08-29 15:30:00",
        "amount": 128.00,
        "items": [{"name": "陶瓷马克杯 350ml", "qty": 2, "price": 64.00}],
        "address": "广东省深圳市南山区xx路1号（已脱敏）",
    },
    {
        "order_id": "ORD-20260831003",
        "phone": "13800005678",
        "owner_user_id": "u-2002",
        "status": "待发货",
        "status_code": "pending_shipment",
        "created_at": "2026-08-31 09:05:00",
        "amount": 89.90,
        "items": [{"name": "无线蓝牙耳机", "qty": 1, "price": 89.90}],
        "address": "北京市朝阳区xx街2号（已脱敏）",
    },
]

# 演示用默认身份：ORD-20260828001 / ORD-20260829002 归属 u-1001，ORD-20260831003 归属 u-2002。
# 行级权限校验放在 MCP server 内部（工具它自己持有数据），身份由客户端在调用时注入且覆盖模型传入值。
DEFAULT_USER_ID = "u-1001"


def order_owner(order_id: str) -> str:
    """返回订单归属人；订单不存在时返回空串。"""
    target = (order_id or "").strip().upper()
    return next((o.get("owner_user_id", "") for o in ORDERS if o["order_id"].upper() == target), "")

LOGISTICS = {
    "ORD-20260828001": {
        "carrier": "顺丰速运",
        "tracking_no": "SF1234567890",
        "status": "运输中",
        "events": [
            {"time": "2026-08-28 18:02", "node": "深圳转运中心", "desc": "快件已发出"},
            {"time": "2026-08-29 07:35", "node": "广州转运中心", "desc": "到达中转站"},
            {"time": "2026-08-29 20:11", "node": "武汉转运中心", "desc": "运输中"},
        ],
        "eta": "预计 2026-09-01 18:00 前送达",
    },
    "ORD-20260829002": {
        "carrier": "中通快递",
        "tracking_no": "ZT9876543210",
        "status": "已签收",
        "events": [
            {"time": "2026-08-29 17:00", "node": "深圳福田营业点", "desc": "已签收，签收人：本人"}
        ],
        "eta": "已签收",
    },
    "ORD-20260831003": {
        "carrier": "圆通速递",
        "tracking_no": "YT5556667778",
        "status": "待发货",
        "events": [
            {"time": "2026-08-31 10:00", "node": "仓库", "desc": "订单已确认，等待出库"}
        ],
        "eta": "预计 2026-09-02 发货",
    },
}

REFUND_RULES = {
    "七天无理由": "商品签收后 7 天内，未拆封、不影响二次销售，可申请七天无理由退货；运费由买家承担（含运费险时可赔付）。",
    "质量问题": "商品存在质量问题（破损/功能故障），签收后 15 天内可退换，运费由卖家承担。",
    "运费规则": "七天无理由退货：买家承担运费（有运费险按保险赔付）；质量问题或发错货：卖家承担运费。",
    "退款到账": "退款原路返回，一般 1-3 个工作日到账；花呗/信用卡支付退回原账户。",
    "投诉流程": "投诉工单自动创建后，客服 24 小时内响应，48 小时内给出处理结果；超时自动升级。",
}

KNOWLEDGE_BASE = [
    {"id": "R-001", "title": "七天无理由退货规则", "tags": ["退货", "无理由", "七天"], "content": REFUND_RULES["七天无理由"]},
    {"id": "R-002", "title": "质量问题退换货", "tags": ["质量问题", "破损", "换货", "故障"], "content": REFUND_RULES["质量问题"]},
    {"id": "R-003", "title": "运费承担规则", "tags": ["运费", "退货", "包邮"], "content": REFUND_RULES["运费规则"]},
    {"id": "R-004", "title": "退款到账时间", "tags": ["退款", "到账", "几天"], "content": REFUND_RULES["退款到账"]},
    {"id": "R-005", "title": "投诉处理流程", "tags": ["投诉", "工单", "升级"], "content": REFUND_RULES["投诉流程"]},
    {"id": "R-006", "title": "修改收货地址", "tags": ["改地址", "收货", "地址"], "content": "订单未发货前可联系客服修改收货地址；已发货订单需联系物流拦截或转寄（可能产生费用）。"},
    {"id": "R-007", "title": "发票开具", "tags": ["发票", "开票", "报销"], "content": "订单完成后可在订单详情申请电子发票，一般 24 小时内开具到邮箱。"},
]
