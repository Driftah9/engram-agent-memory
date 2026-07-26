"""Tests for inline [[wiki-link]] relations and NL-robust smart_recall."""

import tempfile
from pathlib import Path

from engram import MemoryStore, smart_recall


def test_inline_wikilinks_become_relations():
    """A [[node-name]] in the body should create a relation edge."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "a.md").write_text(
            "---\nname: node-a\ntype: reference\ndescription: A\n---\n\n"
            "Body of A that links to [[node-b]] inline.\n"
        )
        (tmp / "b.md").write_text(
            "---\nname: node-b\ntype: reference\ndescription: B\n---\n\nBody of B.\n"
        )
        store = MemoryStore(str(tmp))
        store.build()
        rels = store.relations_from("node-a")
        assert "node-b" in rels


def test_see_also_and_inline_merge_without_duplicates():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "a.md").write_text(
            "---\nname: node-a\ntype: reference\ndescription: A\n"
            "metadata:\n  relations:\n    see_also:\n      - node-b\n---\n\n"
            "Links to [[node-b]] again and to [[node-c]].\n"
        )
        store = MemoryStore(str(tmp))
        store.build()
        rels = store.relations_from("node-a")
        assert rels.count("node-b") == 1   # not duplicated
        assert "node-c" in rels


def test_no_self_links():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "a.md").write_text(
            "---\nname: node-a\ntype: reference\ndescription: A\n---\n\n"
            "A note that mentions [[node-a]] itself.\n"
        )
        store = MemoryStore(str(tmp))
        store.build()
        assert "node-a" not in store.relations_from("node-a")


def test_smart_recall_natural_language(memory_store):
    """A full sentence should still retrieve a hit (where AND-FTS might not)."""
    memory_store.build()
    hits = memory_store.smart_recall("what are the communication style preferences")
    assert hits
    assert any("feedback_communication" in h["source"] for h in hits)
    assert all({"text", "source", "score"} <= set(h) for h in hits)


def test_smart_recall_module_level(memory_store):
    memory_store.build()
    hits = smart_recall(memory_store, "AI research project status")
    assert hits
    assert hits[0]["source"].startswith("engram:")


def test_smart_recall_empty_on_stopwords_only(memory_store):
    memory_store.build()
    assert smart_recall(memory_store, "the and for with") == []


# ── v0.4.0: relevance floor (no padding to k) ───────────────────────

def test_relevance_floor_keyword_only():
    """Without embeddings, weak single-keyword matches are rejected."""
    from engram.recall import _relevant
    # 1 hit of 4 keywords, no vector available → rejected
    assert not _relevant(kw_hits=1, kw_frac=0.25, vec_z=0.0, have_vec=False)
    # 2 hits → accepted
    assert _relevant(kw_hits=2, kw_frac=0.5, vec_z=0.0, have_vec=False)
    # single keyword query fully covered → accepted
    assert _relevant(kw_hits=1, kw_frac=1.0, vec_z=0.0, have_vec=False)


def test_relevance_floor_vector_zscore():
    from engram.recall import _relevant, VEC_Z_STRONG
    # strong semantic outlier passes alone
    assert _relevant(kw_hits=0, kw_frac=0.0, vec_z=VEC_Z_STRONG, have_vec=True)
    # weak keyword + unremarkable vector is rejected
    assert not _relevant(kw_hits=1, kw_frac=0.25, vec_z=0.1, have_vec=True)
    # unembedded row (vec_z None) falls back to keyword floor
    assert _relevant(kw_hits=2, kw_frac=0.6, vec_z=None, have_vec=True)
    assert not _relevant(kw_hits=1, kw_frac=0.2, vec_z=None, have_vec=True)


def test_smart_recall_returns_fewer_than_k(memory_store):
    """Variable-k: irrelevant queries return few/no hits, never padded to k."""
    from engram.recall import smart_recall
    hits = smart_recall(memory_store, "zzqx unmatched nonsense terms", k=4)
    assert len(hits) < 4
