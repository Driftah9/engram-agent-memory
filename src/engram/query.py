"""Query helpers for engram-memory. NEXUS:PORTABLE."""

import sqlite3
from typing import List, Dict, Optional

from .sanitizer import sanitize_fts


# Import scope filtering (optional; if data_scope not available, queries ignore scope).
# Tries absolute path first (/home/claude), then falls back to None (no scope).
data_scope = None
try:
    import sys
    if "/home/claude" not in sys.path:
        sys.path.insert(0, "/home/claude")
    from adapters.core import data_scope as _data_scope
    data_scope = _data_scope
except (ImportError, ModuleNotFoundError):
    pass


def fts_query(
    conn: sqlite3.Connection,
    term: str,
    type_filter: Optional[str] = None,
    limit: int = 20,
    scope: Optional[object] = None,
) -> List[Dict]:
    """Safe full-text search with optional type + scope filtering.

    Args:
        conn: SQLite connection with memory_index and memory_fts tables
        term: Raw search term (will be sanitized)
        type_filter: Optional type to filter by ('user', 'feedback', 'project', 'reference')
        limit: Maximum number of results to return
        scope: Optional data_scope.ScopeFilter from the caller. None = no scope (owner view).

    Returns:
        List of dicts with keys: id, type, file_name, line_start, line_end, access_tier, workspace_id

    Examples:
        >>> results = fts_query(conn, "SSDI")
        >>> results = fts_query(conn, "Mattermost", type_filter="feedback", limit=10)
        >>> from adapters.core.data_scope import visible_scope
        >>> scope = visible_scope("wizz", "guest", {"website-design": "read"})
        >>> scoped_results = fts_query(conn, "project", scope=scope)
    """
    safe = sanitize_fts(term)
    if not safe:
        return []

    scope_where, scope_params = ("", [])
    if scope and data_scope:
        scope_where, scope_params = data_scope.scope_sql(scope, table_alias="mi")
        scope_where = f" AND {scope_where}"

    if type_filter:
        rows = conn.execute(
            f"""
            SELECT mi.id, mi.type, mi.file_name, mi.line_start, mi.line_end,
                   mi.access_tier, mi.workspace_id
            FROM memory_fts f JOIN memory_index mi ON mi.id=f.id AND mi.type=?
            WHERE memory_fts MATCH ?{scope_where} ORDER BY rank LIMIT ?
            """,
            (type_filter, safe, *scope_params, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            f"""
            SELECT mi.id, mi.type, mi.file_name, mi.line_start, mi.line_end,
                   mi.access_tier, mi.workspace_id
            FROM memory_fts f JOIN memory_index mi ON mi.id=f.id
            WHERE memory_fts MATCH ?{scope_where} ORDER BY rank LIMIT ?
            """,
            (safe, *scope_params, limit),
        ).fetchall()

    return [dict(r) for r in rows]


def section_query(
    conn: sqlite3.Connection,
    term: str,
    exclude_ids: Optional[List[str]] = None,
    limit: int = 20,
    scope: Optional[object] = None,
) -> List[Dict]:
    """Find sections containing all tokens from a term, with optional scope filtering.

    Normalizes hyphens to spaces before tokenizing, so "multi-user" and
    "multi user" both find sections containing both words regardless of
    how they're joined in the source.

    Args:
        conn: SQLite connection with memory_sections and memory_index tables
        term: Search term — split on whitespace, each token must match
        exclude_ids: Node IDs to exclude (default: ['MEMORY', 'SCHEMA'])
        limit: Maximum number of results to return
        scope: Optional data_scope.ScopeFilter. None = no scope (owner view).

    Returns:
        List of dicts with keys: id, type, file_path, file_name, heading, line_start, line_end,
                                 access_tier, workspace_id

    Examples:
        >>> sections = section_query(conn, "SSDI")
        >>> sections = section_query(conn, "multi-user")        # finds "multi user" too
        >>> from adapters.core.data_scope import visible_scope
        >>> scope = visible_scope("wizz", "guest", {"website": "read"})
        >>> sections = section_query(conn, "priority partners", scope=scope)
    """
    exclude = exclude_ids or ["MEMORY", "SCHEMA"]
    placeholders = ",".join("?" * len(exclude))

    tokens = term.replace("-", " ").split()
    if not tokens:
        return []

    token_clauses = " AND ".join(
        "(ms.content LIKE ? OR ms.heading LIKE ?)" for _ in tokens
    )
    token_params = [p for tok in tokens for p in (f"%{tok}%", f"%{tok}%")]

    scope_where, scope_params = ("", [])
    if scope and data_scope:
        scope_where, scope_params = data_scope.scope_sql(scope, table_alias="mi")
        scope_where = f" AND {scope_where}"

    rows = conn.execute(
        f"""
        SELECT mi.id, mi.type, mi.file_path, mi.file_name,
               ms.heading, ms.line_start, ms.line_end,
               mi.access_tier, mi.workspace_id
        FROM memory_sections ms
        JOIN memory_index mi ON ms.node_id = mi.id
        WHERE ms.node_id NOT IN ({placeholders})
          AND {token_clauses}{scope_where}
        ORDER BY mi.type, mi.id
        LIMIT ?
        """,
        (*exclude, *token_params, *scope_params, limit),
    ).fetchall()

    return [dict(r) for r in rows]
