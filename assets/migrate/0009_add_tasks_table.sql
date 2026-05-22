CREATE TABLE IF NOT EXISTS tasks (
    id           INTEGER  PRIMARY KEY AUTOINCREMENT,
    team_id      INTEGER  NOT NULL,
    title        TEXT     NOT NULL,
    description  TEXT     NOT NULL DEFAULT '',
    assignee_id  INTEGER  NOT NULL,
    creator_id   INTEGER  NOT NULL,
    manager_id   INTEGER,
    status       TEXT     NOT NULL DEFAULT 'TODO',
    priority     TEXT     NOT NULL DEFAULT 'NORMAL',
    parent_id    INTEGER,
    depends_on   TEXT     NOT NULL DEFAULT '[]',
    room_id      INTEGER,
    result       TEXT     NOT NULL DEFAULT '',
    block_reason TEXT     NOT NULL DEFAULT '',
    created_at   DATETIME NOT NULL DEFAULT (datetime('now')),
    updated_at   DATETIME NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tasks_team_status     ON tasks (team_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_team_assignee   ON tasks (team_id, assignee_id);
