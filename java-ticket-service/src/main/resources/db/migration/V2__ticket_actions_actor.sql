-- 审计流水追加 actor 维度（操作人），并固化 append-only 语义
ALTER TABLE ticket_actions ADD COLUMN actor VARCHAR(64) NOT NULL DEFAULT 'system';

COMMENT ON TABLE ticket_actions IS
    '动作留痕为 append-only 审计流水：只允许 INSERT，禁止 DELETE/UPDATE';

CREATE INDEX idx_actions_actor ON ticket_actions (actor);
