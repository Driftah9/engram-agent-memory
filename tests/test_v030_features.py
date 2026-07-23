"""Tests for v0.3.0 features: incremental indexing, manifest scope, hybrid search.

These tests are dependency-free — hybrid_query is exercised in its Ollama-absent
fallback path (FTS-only), which is the guaranteed-available behavior. Embedding
generation itself is not asserted here because it requires a live Ollama endpoint.
"""

import time

import pytest


# ---------------------------------------------------------------------------
# Incremental indexing
# ---------------------------------------------------------------------------

def test_incremental_no_changes_parses_nothing(memory_store):
    """After a full build, an incremental build with no file changes re-parses 0 files."""
    memory_store.build(full=True)
    stats = memory_store.build()  # incremental
    assert stats["parsed"] == 0
    assert stats["files"] == 3  # user + feedback + project fixtures


def test_incremental_state_file_written(memory_store):
    """A full build writes the .engram_state.json mtime-tracking file."""
    memory_store.build(full=True)
    assert memory_store.state_path.exists()
    state = memory_store._read_state()
    assert len(state) == 3


def test_incremental_reparses_only_changed_file(memory_store, temp_knowledge_dir):
    """Modifying one file causes exactly one file to be re-parsed."""
    memory_store.build(full=True)

    # Modify a single file (bump mtime deterministically)
    target = temp_knowledge_dir / "user_profile.md"
    target.write_text(target.read_text() + "\nExtra=line\n")
    # Ensure mtime differs even on coarse filesystems
    future = time.time() + 10
    import os
    os.utime(target, (future, future))

    stats = memory_store.build()  # incremental
    assert stats["parsed"] == 1
    assert stats["files"] == 3  # count unchanged


def test_incremental_handles_deleted_file(memory_store, temp_knowledge_dir):
    """Deleting a file removes its node from the index on the next incremental build."""
    memory_store.build(full=True)
    assert memory_store.query("research")  # project_ai matches before deletion

    (temp_knowledge_dir / "project_ai.md").unlink()
    memory_store.build()  # incremental

    conn = memory_store.connect()
    row = conn.execute("SELECT COUNT(*) FROM memory_index WHERE id='project-ai'").fetchone()
    conn.close()
    assert row[0] == 0


def test_full_rebuild_flag_recreates_db(memory_store):
    """build(full=True) works from a clean slate and indexes every file."""
    stats = memory_store.build(full=True)
    assert stats["parsed"] == 3
    assert stats["files"] == 3


# ---------------------------------------------------------------------------
# Manifest scope filtering
# ---------------------------------------------------------------------------

def test_manifest_query_returns_scope_fields(memory_store):
    """Manifest entries carry the multi-user scope fields for ACL enforcement."""
    memory_store.build(full=True)
    hits = memory_store.manifest_query("communication")
    assert hits
    h = hits[0]
    assert h.get("access_tier") == "global"
    assert "workspace_id" in h
    assert "user_id" in h


def test_manifest_query_owner_view_unfiltered(memory_store):
    """scope=None (owner view) returns all matching entries — no filtering."""
    memory_store.build(full=True)
    hits = memory_store.manifest_query("AI")
    assert any(h["id"] == "project-ai" for h in hits)


# ---------------------------------------------------------------------------
# Hybrid search (FTS + vector), Ollama-absent fallback
# ---------------------------------------------------------------------------

def test_hybrid_query_falls_back_to_fts(memory_store):
    """With embeddings unavailable, hybrid_query still returns keyword matches."""
    memory_store.build(full=True)
    results = memory_store.hybrid_query("status")
    # 'status' appears as a heading/content in project_ai — keyword path must find it
    assert any(r["id"] == "project-ai" for r in results)


def test_hybrid_query_respects_limit(memory_store):
    """hybrid_query honors the limit parameter."""
    memory_store.build(full=True)
    results = memory_store.hybrid_query("concise", limit=1)
    assert len(results) <= 1


def test_hybrid_query_excludes_default_ids(memory_store):
    """hybrid_query excludes MEMORY/SCHEMA sentinels by default (no crash if absent)."""
    memory_store.build(full=True)
    results = memory_store.hybrid_query("clear")
    assert all(r["id"] not in ("MEMORY", "SCHEMA") for r in results)
