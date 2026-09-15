# MCP 工具（完成）

电商售后四个模拟业务工具，统一按 MCP 协议暴露（stdio 传输），供 Agent 编排层调用：

| server | 文件 | 工具 |
|---|---|---|
| order-server | order_server.py | query_order / list_orders_by_phone |
| logistics-server | logistics_server.py | query_logistics |
| refund-server | refund_server.py | check_refund_eligibility / get_refund_flow |
| knowledge-server | knowledge_server.py | search_knowledge |

## 运行与验证

```powershell
# 启动单个 server（每个独立进程）
python mcp_servers/order_server.py

# 一键验证：客户端连接 4 个 server 并调用全部工具
python mcp_servers/test_client.py
```

完成标志：MCP client 能成功调用四个工具（test_client.py 全过）。
