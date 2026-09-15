package com.agentservice.ticket;

/** 非法状态流转（如 NEW -> REFUNDED）。Controller 层映射为 HTTP 409。 */
public class IllegalTransitionException extends RuntimeException {
    private final TicketStatus from;
    private final TicketStatus to;

    public IllegalTransitionException(TicketStatus from, TicketStatus to) {
        super("非法工单流转: " + from + " -> " + to);
        this.from = from;
        this.to = to;
    }

    public TicketStatus getFrom() {
        return from;
    }

    public TicketStatus getTo() {
        return to;
    }
}
