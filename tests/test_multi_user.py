"""Tests for engram multi-user scope filtering. NEXUS:PORTABLE."""
import sys
from pathlib import Path

# Make data_scope importable
sys.path.insert(0, "/home/claude")

import pytest
from engram import MemoryStore
from adapters.core import data_scope


@pytest.fixture
def temp_mem(tmp_path):
    """Create a minimal test memory pool."""
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()

    # Create a few test nodes with frontmatter
    (mem_dir / "test_global.md").write_text("""---
name: test-global
description: A global knowledge node
type: reference
---
This is visible to everyone.
""")

    (mem_dir / "test_workspace.md").write_text("""---
name: test-workspace
description: A workspace-scoped node
type: project
---
This is scoped to website-design workspace.
""")

    (mem_dir / "test_private.md").write_text("""---
name: test-private
description: A private node
type: user
---
This is private to the owner.
""")

    return mem_dir


def test_build_with_multi_user_columns(temp_mem, tmp_path):
    """Verify build creates multi-user columns."""
    db = tmp_path / "test.db"
    store = MemoryStore(str(temp_mem), db_path=str(db))
    stats = store.build()

    assert stats["files"] == 3

    conn = store.connect()
    rows = conn.execute(
        "SELECT id, user_id, access_tier, workspace_id FROM memory_index"
    ).fetchall()
    assert len(rows) == 3
    # All should default to owner/global
    for r in rows:
        assert dict(r)["user_id"] == "owner"
        assert dict(r)["access_tier"] == "global"
    conn.close()


def test_owner_sees_all(temp_mem, tmp_path):
    """Owner (see_all=True) sees all nodes."""
    db = tmp_path / "test.db"
    store = MemoryStore(str(temp_mem), db_path=str(db))
    store.build()

    # Owner has no scope restrictions
    scope = data_scope.visible_scope("owner", "owner", {})

    results = store.query("test", scope=scope, limit=10)
    assert len(results) == 3  # owner sees everything

    for r in results:
        assert r["access_tier"] == "global"


def test_guest_scope_filtering(temp_mem, tmp_path):
    """Guest with limited grants sees only global + granted workspaces."""
    db = tmp_path / "test.db"
    store = MemoryStore(str(temp_mem), db_path=str(db))
    store.build()

    # Manually update rows to simulate runtime data
    conn = store.connect()
    conn.execute(
        "UPDATE memory_index SET access_tier=?, workspace_id=? WHERE id=?",
        (data_scope.TIER_WORKSPACE, "website-design", "test-workspace")
    )
    conn.execute(
        "UPDATE memory_index SET access_tier=?, user_id=? WHERE id=?",
        (data_scope.TIER_PRIVATE, "owner", "test-private")
    )
    conn.commit()
    conn.close()

    # Guest with access to website-design but not others
    scope = data_scope.visible_scope("wizz", "guest", {"website-design": "read"})

    results = store.query("test", scope=scope, limit=10)
    # Should see: test_global (access_tier=global) + test_workspace (in granted ws)
    # Should NOT see: test_private (access_tier=private, owner only)
    assert len(results) == 2
    visible_ids = {r["id"] for r in results}
    assert "test-global" in visible_ids
    assert "test-workspace" in visible_ids
    assert "test-private" not in visible_ids


def test_private_node_visibility(temp_mem, tmp_path):
    """Private nodes only visible to owner/author."""
    db = tmp_path / "test.db"
    store = MemoryStore(str(temp_mem), db_path=str(db))
    store.build()

    conn = store.connect()
    conn.execute(
        "UPDATE memory_index SET access_tier=?, user_id=? WHERE id=?",
        (data_scope.TIER_PRIVATE, "owner", "test-private")
    )
    conn.commit()
    conn.close()

    # Wizz (guest) sees nothing private
    scope_wizz = data_scope.visible_scope("wizz", "guest", {})
    results_wizz = store.query("private", scope=scope_wizz, limit=10)
    assert len(results_wizz) == 0

    # Owner sees it
    scope_owner = data_scope.visible_scope("owner", "owner", {})
    results_owner = store.query("private", scope=scope_owner, limit=10)
    assert len(results_owner) == 1


def test_section_query_with_scope(temp_mem, tmp_path):
    """section_query accepts scope parameter without error."""
    db = tmp_path / "test.db"
    store = MemoryStore(str(temp_mem), db_path=str(db))
    store.build()

    # Wizz queries sections — should accept scope without error
    # (test nodes don't have H2 sections, so results might be empty)
    scope = data_scope.visible_scope("wizz", "guest", {})
    results = store.section_query("is", scope=scope, limit=10)
    # Just verify it doesn't crash and returns a list
    assert isinstance(results, list)
    # No sections created in test (no ## headers), so empty is expected
    assert len(results) == 0


def test_scope_sql_predicate():
    """Verify scope_sql builds correct WHERE clause."""
    scope = data_scope.visible_scope("wizz", "guest", {"esp32": "read", "website": "read"})
    frag, params = data_scope.scope_sql(scope, table_alias="mi")

    assert "mi.access_tier = ?" in frag
    assert data_scope.TIER_GLOBAL in params
    assert data_scope.TIER_PRIVATE in params
    assert "wizz" in params
    assert "esp32" in params
    assert "website" in params
