package com.agentservice.ticket;

import java.time.Instant;
import java.util.List;
import java.util.Optional;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** 工单业务：创建、流转（表驱动状态机校验）、动作留痕、SLA 超时自动升级（@Scheduled）。 */
@Service
public class TicketService {
    private final TicketRepository repository;
    private final TicketSlaScanner slaScanner;

    public TicketService(
            TicketRepository repository,
            @Value("${ticket.sla.new-seconds:30}") long newSlaSeconds,
            @Value("${ticket.sla.processing-seconds:60}") long processingSlaSeconds) {
        this.repository = repository;
        this.slaScanner = new TicketSlaScanner(repository, newSlaSeconds, processingSlaSeconds);
    }

    @Transactional
    public Ticket create(String sessionId, String title, String category, String priority) {
        Ticket ticket = new Ticket(repository.nextId(), sessionId, title, category, priority);
        return repository.save(ticket);
    }

    public List<Ticket> list() {
        return list(null);
    }

    /** 按会话过滤（工作台/页面查询“我这个对话的工单”）；sessionId 为空返回全部。 */
    public List<Ticket> list(String sessionId) {
        if (sessionId == null || sessionId.isBlank()) {
            return repository.findAll();
        }
        return repository.findAll().stream()
                .filter(t -> sessionId.equals(t.getSessionId()))
                .toList();
    }

    public Optional<Ticket> get(long id) {
        return repository.findById(id);
    }

    @Transactional
    public Ticket transition(long id, TicketStatus to) {
        Ticket ticket = repository.findById(id)
                .orElseThrow(() -> new IllegalArgumentException("工单不存在: " + id));
        TicketStateMachine.requireTransition(ticket.getStatus(), to);
        ticket.recordAction(ticket.getStatus() + " -> " + to);
        ticket.setStatus(to);
        repository.save(ticket);
        return ticket;
    }

    /** 当前违约/待人工工单（委托纯逻辑扫描器）。 */
    public List<Ticket> overdue() {
        return slaScanner.overdueAt(Instant.now());
    }

    /** 定时扫描（可配置周期）：把 SLA 违约工单升级为 ESCALATED 并留痕，返回本次升级数。 */
    @Transactional
    public int escalateOverdue() {
        return escalateOverdue(Instant.now());
    }

    /** 纯逻辑入口（now 可注入，便于单测）：超过 SLA 的 NEW/PROCESSING 升为 ESCALATED。 */
    public int escalateOverdue(Instant now) {
        return slaScanner.escalateOverdue(now);
    }

    @Scheduled(fixedDelayString = "${ticket.sla.scan-ms:10000}")
    public void scheduledEscalateOverdue() {
        escalateOverdue();
    }
}
