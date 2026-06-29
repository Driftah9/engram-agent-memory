# Changelog

All notable changes to engram-memory will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
