package com.agentservice.ticket;

import java.util.EnumMap;
import java.util.Map;
import java.util.Set;

/**
 * 表驱动状态机（复用 ExpenseAI 经验，面试考点：为什么表驱动而不是 if-else）。
 * 转移表：
 *   NEW        -> PROCESSING, CLOSED, ESCALATED（超时升级）
 *   PROCESSING -> RESOLVED, REFUNDED, CLOSED, ESCALATED（超时升级）
 *   ESCALATED  -> RESOLVED, REFUNDED, CLOSED（人工介入后收口）
 *   RESOLVED   -> CLOSED
 *   CLOSED / REFUNDED -> （终态）
 */
public final class TicketStateMachine {

    private static final Map<TicketStatus, Set<TicketStatus>> TRANSITIONS = new EnumMap<>(TicketStatus.class);

    static {
        TRANSITIONS.put(TicketStatus.NEW, Set.of(TicketStatus.PROCESSING, TicketStatus.CLOSED, TicketStatus.ESCALATED));
        TRANSITIONS.put(TicketStatus.PROCESSING,
                Set.of(TicketStatus.RESOLVED, TicketStatus.REFUNDED, TicketStatus.CLOSED, TicketStatus.ESCALATED));
        TRANSITIONS.put(TicketStatus.ESCALATED,
                Set.of(TicketStatus.RESOLVED, TicketStatus.REFUNDED, TicketStatus.CLOSED));
        TRANSITIONS.put(TicketStatus.RESOLVED, Set.of(TicketStatus.CLOSED));
        TRANSITIONS.put(TicketStatus.CLOSED, Set.of());
        TRANSITIONS.put(TicketStatus.REFUNDED, Set.of());
    }

    private TicketStateMachine() {
    }

    public static boolean canTransition(TicketStatus from, TicketStatus to) {
        return TRANSITIONS.getOrDefault(from, Set.of()).contains(to);
    }

    /** 合法则返回目标状态；非法则抛出 IllegalTransitionException（Controller 映射 409）。 */
    public static TicketStatus requireTransition(TicketStatus from, TicketStatus to) {
        if (!canTransition(from, to)) {
            throw new IllegalTransitionException(from, to);
        }
        return to;
    }
}
