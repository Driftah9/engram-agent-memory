# Changelog

All notable changes to engram-agent-memory will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] — 2026-07-23

### Added

- **Incremental indexing**: `build(full=False)` now detects changed/new/deleted files and
  only re-parses what changed (vs. full rebuild on every call). Tracked via `.engram_state.json`
  (file mtimes). Full rebuild available as `build(full=True)` for repair/restart.
  **Performance gain at scale:** 228 files, 710ms full → 36ms incremental (no changes).
- **Manifest scope filtering**: `manifest_query()` now accepts optional `scope` parameter
  for multi-user visibility control (same as `query()` and `section_query()`), and manifest
  now carries `access_tier`, `workspace_id`, `user_id` fields for ACL enforcement.
- **Semantic search (hybrid)**: `hybrid_query(term)` combines FTS5 keyword search with
  vector similarity (768-dim embeddings via local Ollama, model-agnostic Ollama HTTP API).
  Embeddings stored as blobs in new `memory_vectors` table. Graceful fallback to FTS-only
  if embeddings unavailable (e.g., Ollama offline). Scoring: keyword match + semantic
  cosine similarity, sorted by combined score.
- **Vector schema**: New `memory_vectors` table (section_id, embedding blob, model, created_at).

### Changed

- `build()` now accepts `full: bool = False` parameter (backward compatible).
- `MemoryStore.__init__()` creates `.engram_state.json` for incremental tracking.
- `memory_store.py` adds new methods: `_get_embedding()`, `_vector_to_bytes()`,
  `_bytes_to_vector()`, `_cosine_similarity()`, `hybrid_query()`, `smart_recall()`
  (method wrapper over the packaged `recall.smart_recall`).
- Incremental build rebuilds the mtime-tracking state fresh from a directory scan
  each run, decoupling state keys (relative paths) from node IDs (frontmatter names).

### Fixed

- Manifest fallback now enforces data scope (was bypassing ACL in DB-down mode).
- **Incremental deletion correctness**: deleted files are now resolved to node IDs
  via the manifest (`file_path` → id) instead of assuming `id == filename stem`.
  A node whose frontmatter `name` differed from its filename was not being removed
  from the index (or re-indexed on change) under incremental builds. Verified with
  a dedicated regression test.

### Tests

- Added `tests/test_v030_features.py` — 11 tests covering incremental indexing
  (no-change / changed-file / deleted-file / full-rebuild), manifest scope fields,
  and hybrid search in its Ollama-absent (FTS-only) fallback path. Full suite: 25
  passed, 6 skipped.

## [0.2.0] — 2026-06-29

### Added

- Inline wiki-link relations: `[[node-name]]` references in a node body now become
  relation edges (merged with `see_also`, deduped, self-links dropped). Turns the
  index into a dense MOC/graph instead of relying on `see_also` frontmatter alone.
- `smart_recall(query, k=4)` (module-level `engram.smart_recall` and
  `MemoryStore.smart_recall`): natural-language-robust recall — stopword strip +
  keyword OR-match + best-matching section with exact line pointers. Use it when a
  full sentence would AND-match nothing under `query()`.

### Changed

- Packaging: PyPI distribution name is **`engram-agent-memory`** (`engram-memory` is
  taken by an unrelated project). The import name is unchanged: `from engram import ...`.
- Decoupled the library from any install location: optional multi-user scoping now
  imports a plain `data_scope` module from the host app's path if present, instead of
  hard-coding `/home/claude` and `adapters.core`. The library makes no assumption
  about where it runs.
- Documentation examples use neutral sample queries.

## [0.1.0] — 2026-06-26

### Added

- Initial release of engram-memory
- MemoryStore class for managing persistent knowledge
- SQLite backend with FTS5 full-text search
- Manifest JSON fallback for DB-down recovery
- Section-level line pointers for fine-grained retrieval
- Relation graph via `see_also` links
- FTS5 input sanitizer for safe queries
- Complete test suite (9 tests, 100% pass)
- Full API documentation
- Architecture documentation
- Contributing guidelines

### Features

- Markdown files as source of truth
- Four knowledge types: user, feedback, project, reference
- YAML frontmatter for metadata
- H2 sections for content organization
- Query by keyword, type, or section
- Follow relation chains
- Manifest-based queries when DB is unavailable

---

## Unreleased

### Planned

- Async query API
- Optional vector similarity (sqlite-vec integration)
- Multi-agent knowledge sharing
- Web UI for browsing
- Automated knowledge consolidation
- Per-agent knowledge isolation
