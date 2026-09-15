package com.agentservice.ticket;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/**
 * 工单仓库（起双模式）：
 * - ticket.storage=memory（默认）：内存 ConcurrentHashMap，单机演示无需数据库；
 * - ticket.storage=postgres：PostgreSQL + Flyway，JDBC 读写 + ticket_actions 留痕表。
 * 切换：java -jar ... --spring.profiles.active=postgres（见 application-postgres.properties）。
 */
@Repository
public class TicketRepository {
    private final Map<Long, Ticket> memoryStore = new ConcurrentHashMap<>();
    private final AtomicLong idSeq = new AtomicLong(1);
    private final JdbcTemplate jdbc;
    private final boolean postgres;

    /** Spring 注入：storage=postgres 且 DataSource 可用时走 JDBC，否则自动回退内存。 */
    @Autowired
    public TicketRepository(ObjectProvider<JdbcTemplate> jdbcProvider,
                            @Value("${ticket.storage:memory}") String storage) {
        boolean wantPostgres = "postgres".equalsIgnoreCase(storage);
        JdbcTemplate candidate = jdbcProvider.getIfAvailable();
        this.postgres = wantPostgres && candidate != null;
        this.jdbc = this.postgres ? candidate : null;
    }

    /** 测试/单机直连用：默认内存模式。 */
    public TicketRepository() {
        this.postgres = false;
        this.jdbc = null;
    }

    public Ticket save(Ticket ticket) {
        if (postgres) {
            jdbcSave(ticket);
        } else {
            memoryStore.put(ticket.getId(), ticket);
        }
        return ticket;
    }

    public Optional<Ticket> findById(long id) {
        if (postgres) {
            List<Ticket> rows = jdbc.query(
                    "SELECT id, session_id, title, category, priority, status, created_at, updated_at"
                            + " FROM tickets WHERE id = ?",
                    (rs, rowNum) -> mapTicket(rs),
                    id);
            if (rows.isEmpty()) {
                return Optional.empty();
            }
            Ticket ticket = rows.get(0);
            attachActions(ticket);
            return Optional.of(ticket);
        }
        return Optional.ofNullable(memoryStore.get(id));
    }

    public List<Ticket> findAll() {
        if (postgres) {
            List<Ticket> tickets = jdbc.query(
                    "SELECT id, session_id, title, category, priority, status, created_at, updated_at"
                            + " FROM tickets ORDER BY id",
                    (rs, rowNum) -> mapTicket(rs));
            for (Ticket ticket : tickets) {
                attachActions(ticket);
            }
            return tickets;
        }
        return memoryStore.values().stream()
                .sorted(Comparator.comparingLong(Ticket::getId))
                .toList();
    }

    public long nextId() {
        if (postgres) {
            Long next = jdbc.queryForObject("SELECT nextval('tickets_id_seq')", Long.class);
            return next == null ? 1L : next;
        }
        return idSeq.getAndIncrement();
    }

    private Ticket mapTicket(ResultSet rs) throws SQLException {
        Instant createdAt = rs.getTimestamp("created_at").toInstant();
        Instant updatedAt = rs.getTimestamp("updated_at").toInstant();
        return new Ticket(
                rs.getLong("id"),
                rs.getString("session_id"),
                rs.getString("title"),
                rs.getString("category"),
                rs.getString("priority"),
                createdAt,
                TicketStatus.valueOf(rs.getString("status")),
                updatedAt,
                List.of());
    }

    private void attachActions(Ticket ticket) {
        List<String> actions = jdbc.query(
                "SELECT action FROM ticket_actions WHERE ticket_id = ? ORDER BY id",
                (rs, rowNum) -> rs.getString("action"),
                ticket.getId());
        ticket.replaceActions(actions);
    }

    private void jdbcSave(Ticket ticket) {
        jdbc.update(
                "INSERT INTO tickets"
                        + " (id, session_id, title, category, priority, status, created_at, updated_at)"
                        + " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                        + " ON CONFLICT (id) DO UPDATE SET"
                        + " session_id = EXCLUDED.session_id,"
                        + " title = EXCLUDED.title,"
                        + " category = EXCLUDED.category,"
                        + " priority = EXCLUDED.priority,"
                        + " status = EXCLUDED.status,"
                        + " updated_at = EXCLUDED.updated_at",
                ticket.getId(),
                ticket.getSessionId(),
                ticket.getTitle(),
                ticket.getCategory(),
                ticket.getPriority(),
                ticket.getStatus().name(),
                Timestamp.from(ticket.getCreatedAt()),
                Timestamp.from(ticket.getUpdatedAt()));
        // append-only：只追加尚未落库的新动作，绝不删除历史（审计不可篡改）
        List<String> actions = ticket.getActions();
        int start = ticket.persistedActions();
        for (int i = start; i < actions.size(); i++) {
            jdbc.update(
                    "INSERT INTO ticket_actions (ticket_id, action, actor) VALUES (?, ?, ?)",
                    ticket.getId(),
                    actions.get(i),
                    "system");
        }
        ticket.markActionsPersisted(actions.size());
    }
}
