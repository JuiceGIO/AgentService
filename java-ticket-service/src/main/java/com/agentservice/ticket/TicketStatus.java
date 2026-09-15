package com.agentservice.ticket;

/** 工单状态：新建 → 处理中 → 已解决/已关闭/已退款；超时 SLA 违约自动升级为 ESCALATED。 */
public enum TicketStatus {
    NEW,
    PROCESSING,
    ESCALATED,
    RESOLVED,
    CLOSED,
    REFUNDED
}
