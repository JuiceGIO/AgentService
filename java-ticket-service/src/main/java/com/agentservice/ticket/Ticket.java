package com.agentservice.ticket;

import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/** 工单实体（内存版，迁移 PostgreSQL）。actions 为动作留痕（创建/流转/超时升级）。 */
public class Ticket {
    private final long id;
    private final String sessionId;
    private final String title;
    private final String category;
    private final String priority;
    private final List<String> actions = new ArrayList<>();
    private volatile int persistedActions = 0; // 已写入 DB 的动作条数（append-only 用）
    private volatile TicketStatus status;
    private final Instant createdAt;
    private volatile Instant updatedAt;

    public Ticket(long id, String sessionId, String title, String category, String priority) {
        this(id, sessionId, title, category, priority, Instant.now());
    }

    /** 测试/回放用构造：可指定创建时间（updatedAt 随创建时间初始化）。 */
    public Ticket(long id, String sessionId, String title, String category, String priority, Instant createdAt) {
        this.id = id;
        this.sessionId = sessionId;
        this.title = title;
        this.category = category;
        this.priority = priority;
        this.status = TicketStatus.NEW;
        this.createdAt = createdAt;
        this.updatedAt = this.createdAt;
        this.actions.add("CREATE -> NEW");
    }

    /** JDBC 还原用构造：完整状态 + 既有动作留痕（不自动追加 CREATE）。 */
    public Ticket(long id, String sessionId, String title, String category, String priority,
                  Instant createdAt, TicketStatus status, Instant updatedAt, List<String> actions) {
        this.id = id;
        this.sessionId = sessionId;
        this.title = title;
        this.category = category;
        this.priority = priority;
        this.createdAt = createdAt;
        this.status = status;
        this.updatedAt = updatedAt;
        if (actions != null) {
            this.actions.addAll(actions);
            this.persistedActions = actions.size();
        }
    }

    public long getId() {
        return id;
    }

    public String getSessionId() {
        return sessionId;
    }

    public String getTitle() {
        return title;
    }

    public String getCategory() {
        return category;
    }

    public String getPriority() {
        return priority;
    }

    public TicketStatus getStatus() {
        return status;
    }

    public List<String> getActions() {
        return Collections.unmodifiableList(actions);
    }

    public int persistedActions() {
        return persistedActions;
    }

    /** 仓库层在成功追加写入后调用，标记已落库条数（仅 JDBC 模式使用）。 */
    public synchronized void markActionsPersisted(int count) {
        if (count < 0 || count > actions.size()) {
            throw new IllegalArgumentException("persisted count out of range: " + count);
        }
        this.persistedActions = count;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }

    public void setStatus(TicketStatus status) {
        this.status = status;
        this.updatedAt = Instant.now();
    }

    /** 追加动作留痕（线程安全；定时扫描与 REST 并发写）。 */
    public synchronized void recordAction(String action) {
        this.actions.add(action);
    }

    /** JDBC 还原留痕用：整表替换（仅仓库层调用，保持审计一致性）。 */
    public synchronized void replaceActions(List<String> newActions) {
        this.actions.clear();
        if (newActions != null) {
            this.actions.addAll(newActions);
        }
        this.persistedActions = this.actions.size();
    }
}
