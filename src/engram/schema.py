"""SQLite schema for engram-agent-memory."""

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS memory_index (
    id           TEXT PRIMARY KEY,
    type         TEXT NOT NULL DEFAULT 'unknown',
    description  TEXT,
    file_path    TEXT NOT NULL,
    file_name    TEXT NOT NULL,
    line_start   INTEGER,
    line_end     INTEGER,
    session_date TEXT,
    body         TEXT,
    -- NEXUS:PORTABLE — multi-user columns (owner-only when empty/NULL; filled on create/edit)
    user_id      TEXT,                          -- person_id who owns/authored this node
    workspace_id TEXT,                          -- project scope (NULL = global)
    access_tier  TEXT DEFAULT 'global',         -- global|workspace|private
    created_by   TEXT,                          -- person_id who first created
    created_at   REAL,                          -- unix timestamp
    updated_by   TEXT,                          -- person_id who last edited
    updated_at   REAL                           -- unix timestamp
);

CREATE TABLE IF NOT EXISTS memory_sections (
    rowid      INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id    TEXT NOT NULL REFERENCES memory_index(id) ON DELETE CASCADE,
    heading    TEXT,
    line_start INTEGER,
    line_end   INTEGER,
    content    TEXT,
    -- inherit scope from node_id, cached for query efficiency (denormalized)
    access_tier TEXT DEFAULT 'global',
    workspace_id TEXT
);

CREATE TABLE IF NOT EXISTS memory_relations (
    from_id TEXT NOT NULL,
    to_id   TEXT NOT NULL,
    PRIMARY KEY (from_id, to_id)
);

CREATE INDEX IF NOT EXISTS idx_mi_type ON memory_index(type);
CREATE INDEX IF NOT EXISTS idx_ms_node ON memory_sections(node_id);
CREATE INDEX IF NOT EXISTS idx_mr_from ON memory_relations(from_id);
CREATE INDEX IF NOT EXISTS idx_mr_to   ON memory_relations(to_id);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    id, description, body,
    content='memory_index',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS fts_ai AFTER INSERT ON memory_index BEGIN
    INSERT INTO memory_fts(rowid, id, description, body)
    VALUES (new.rowid, new.id, new.description, new.body);
END;
CREATE TRIGGER IF NOT EXISTS fts_ad AFTER DELETE ON memory_index BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, id, description, body)
    VALUES ('delete', old.rowid, old.id, old.description, old.body);
END;
CREATE TRIGGER IF NOT EXISTS fts_au AFTER UPDATE ON memory_index BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, id, description, body)
    VALUES ('delete', old.rowid, old.id, old.description, old.body);
    INSERT INTO memory_fts(rowid, id, description, body)
    VALUES (new.rowid, new.id, new.description, new.body);
END;

CREATE INDEX IF NOT EXISTS idx_mi_user ON memory_index(user_id);
CREATE INDEX IF NOT EXISTS idx_mi_access ON memory_index(access_tier);
CREATE INDEX IF NOT EXISTS idx_mi_workspace ON memory_index(workspace_id);
CREATE INDEX IF NOT EXISTS idx_ms_access ON memory_sections(access_tier);
"""
