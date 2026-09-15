package com.agentservice.ticket;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.Test;

/** SLA 超时升级：定时扫描逻辑（可注入 now）与动作留痕。 */
class TicketEscalationTest {

    private Ticket createOld(String sessionId, Instant createdAt) {
        return new Ticket(1L, sessionId, "物流投诉", "complaint", "high", createdAt);
    }

    @Test
    void newTicketOverSlaEscalatesWithActionTrace() {
        TicketRepository repo = new TicketRepository();
        Instant base = Instant.parse("2026-09-02T00:00:00Z");
        Ticket ticket = createOld("s-over", base);
        repo.save(ticket);
        TicketService service = new TicketService(repo, 10, 20);

        int count = service.escalateOverdue(base.plusSeconds(11));

        assertEquals(1, count);
        assertEquals(TicketStatus.ESCALATED, ticket.getStatus());
        assertTrue(ticket.getActions().stream().anyMatch(a -> a.contains("ESCALATE_TIMEOUT")),
                "超时升级应有留痕，实际: " + ticket.getActions());
    }

    @Test
    void freshTicketInsideSlaNotEscalated() {
        TicketRepository repo = new TicketRepository();
        Instant base = Instant.parse("2026-09-02T00:00:00Z");
        Ticket ticket = createOld("s-fresh", base);
        repo.save(ticket);
        TicketService service = new TicketService(repo, 10, 20);

        int count = service.escalateOverdue(base.plusSeconds(9));

        assertEquals(0, count);
        assertEquals(TicketStatus.NEW, ticket.getStatus());
    }

    @Test
    void processingTicketUsesProcessingSla() {
        TicketRepository repo = new TicketRepository();
        Instant base = Instant.parse("2026-09-02T00:00:00Z");
        Ticket ticket = createOld("s-processing", base);
        repo.save(ticket);
        TicketService service = new TicketService(repo, 10, 20);
        service.transition(ticket.getId(), TicketStatus.PROCESSING); // updatedAt -> now(真实时钟)

        int count = service.escalateOverdue(Instant.now().plusSeconds(21));

        assertEquals(1, count);
        assertEquals(TicketStatus.ESCALATED, ticket.getStatus());
    }

    @Test
    void terminalTicketsNeverEscalate() {
        TicketRepository repo = new TicketRepository();
        Instant base = Instant.parse("2026-09-02T00:00:00Z");
        Ticket closed = createOld("s-closed", base);
        repo.save(closed);
        TicketService service = new TicketService(repo, 10, 20);
        service.transition(closed.getId(), TicketStatus.CLOSED);

        int count = service.escalateOverdue(Instant.now().plusSeconds(3600));

        assertEquals(0, count);
        assertEquals(TicketStatus.CLOSED, closed.getStatus());
    }

    @Test
    void escalatedAppearsInOverdueAndCanBeResolved() {
        TicketRepository repo = new TicketRepository();
        Instant base = Instant.parse("2026-09-02T00:00:00Z");
        Ticket ticket = createOld("s-overdue-list", base);
        repo.save(ticket);
        TicketService service = new TicketService(repo, 10, 20);
        service.escalateOverdue(base.plusSeconds(11));

        List<Ticket> overdue = service.overdue();
        assertTrue(overdue.stream().anyMatch(t -> t.getId() == ticket.getId()), "升级工单应在 overdue 列表");
        assertFalse(service.overdue().isEmpty());

        Ticket resolved = service.transition(ticket.getId(), TicketStatus.RESOLVED);
        assertEquals(TicketStatus.RESOLVED, resolved.getStatus());
        assertTrue(resolved.getActions().stream().anyMatch(a -> a.equals("ESCALATED -> RESOLVED")));
    }
}
