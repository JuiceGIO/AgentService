package com.agentservice.ticket;

import java.time.Duration;
import java.time.Instant;
import java.util.List;

/**
 * SLA 超时升级纯逻辑（无 Spring 依赖，now 可注入，便于单测与沙箱直接 javac 验证）。
 * 职责：找出违约工单（NEW/PROCESSING 超过各自 SLA）并把它们升级为 ESCALATED + 留痕。
 */
public class TicketSlaScanner {

    private final TicketRepository repository;
    private final long newSlaSeconds;
    private final long processingSlaSeconds;

    public TicketSlaScanner(TicketRepository repository, long newSlaSeconds, long processingSlaSeconds) {
        this.repository = repository;
        this.newSlaSeconds = newSlaSeconds;
        this.processingSlaSeconds = processingSlaSeconds;
    }

    /** 当前违约/待人工工单：NEW/PROCESSING 超 SLA，或已升级 ESCALATED（等人工收口）。 */
    public List<Ticket> overdueAt(Instant now) {
        return repository.findAll().stream()
                .filter(t -> isOverdueAt(t, now))
                .toList();
    }

    /** 把 SLA 违约工单升级为 ESCALATED 并留痕，返回本次升级数。 */
    public int escalateOverdue(Instant now) {
        int count = 0;
        for (Ticket ticket : repository.findAll()) {
            TicketStatus status = ticket.getStatus();
            if (status != TicketStatus.NEW && status != TicketStatus.PROCESSING) {
                continue;
            }
            long sla = slaFor(status);
            long idle = Duration.between(ticket.getUpdatedAt(), now).getSeconds();
            if (idle >= sla) {
                ticket.recordAction("ESCALATE_TIMEOUT: " + status + " 超过 " + sla + "s 未处理，自动升级");
                ticket.setStatus(TicketStatus.ESCALATED);
                repository.save(ticket);
                count++;
            }
        }
        return count;
    }

    private long slaFor(TicketStatus status) {
        return status == TicketStatus.NEW ? newSlaSeconds : processingSlaSeconds;
    }

    private boolean isOverdueAt(Ticket ticket, Instant now) {
        TicketStatus status = ticket.getStatus();
        if (status == TicketStatus.ESCALATED) {
            return true;
        }
        if (status != TicketStatus.NEW && status != TicketStatus.PROCESSING) {
            return false;
        }
        return Duration.between(ticket.getUpdatedAt(), now).getSeconds() >= slaFor(status);
    }
}
