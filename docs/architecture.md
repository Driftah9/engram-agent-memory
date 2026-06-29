# Architecture

## Design overview

engram-agent-memory implements a **dual-layer knowledge system**: markdown files as source of truth, SQLite as query index, with a manifest JSON enabling zero-DB recovery.

```
Markdown files (human-readable, version-controlled)
       ↓
   ┌─────────────────────────────┐
   │ MemoryStore.build()         │
   │ - Parse YAML frontmatter    │
   │ - Extract sections (H2)     │
   │ - Index relations           │
   │ - Build FTS5 index          │
   └─────────────────────────────┘
       ↙           ↙           ↘
   SQLite      Sections    Manifest.json
  (fast)       (line pts)    (fallback)
       ↓           ↓           ↓
  query()   read_lines()  manifest_query()
```

## Key concepts

### Knowledge nodes

Each markdown file is a knowledge node:

```yaml
---
name: user-profile           # unique ID
type: user                   # {user, feedback, project, reference}
description: "Identity..."   # searchable summary
metadata:
  session_date: 2026-06-26   # when added
  relations:
    see_also:                # links to other nodes
      - another-node
---

Node body text...

## Section 1
Section content...

## Section 2
More content...
```

### File structure

**id** (name)
- Unique identifier across all knowledge nodes
- Used in relations and queries
- Must be hyphenated lowercase

**type**
- `user` — identity, preferences, constraints (e.g., dietary preferences, location)
- `feedback` — learned rules and behavioral patterns (e.g., communication style)
- `project` — ongoing work, context, decisions (e.g., current initiatives)
- `reference` — external sources and patterns (e.g., research findings)

**description**
- One-line summary, searchable via FTS
- Appears in query results

**sections** (H2 headings)
- Divide knowledge into retrievable chunks
- Each section has line range for targeted reads
- Avoid section nesting (H3+ are treated as content)

**relations** (`see_also` + inline `[[wiki-links]]`)
- Links to other knowledge nodes by ID, from `see_also` frontmatter and from any
  `[[node-name]]` written in the body (the MOC/graph layer)
- Bidirectional semantically (if A links to B, B is related to A)
- Stored in memory_relations junction table

### Storage layers

**SQLite (primary query layer)**
- `memory_index` — nodes with metadata
- `memory_sections` — sections with line ranges
- `memory_relations` — graph of node connections
- `memory_fts` — FTS5 virtual table for keyword search

**Manifest JSON (fallback index)**
- Machine-readable snapshot of all nodes
- Includes section metadata (headings, line ranges)
- Survives DB corruption
- Enables queries without any database

**Markdown files (source of truth)**
- Single source of truth
- Version-controlled
- Human-readable
- Used to rebuild the DB

### Query patterns

**Keyword search (FTS5)**
```python
results = store.query("budget", type_filter="user")
# Returns nodes with FTS5 ranking
```

**Section search**
```python
sections = store.section_query("renewal date")
# Returns sections whose content matches
```

**Line-range retrieval**
```python
content = store.read_lines(file_path, start=14, end=32)
# Read exact lines from disk
```

**Follow relations**
```python
related = store.relations_from("fix-live-not-nexus")
# Get all nodes this one links to
```

**Manifest fallback**
```python
# If DB is unavailable:
results = store.manifest_query("budget")
# Query works via JSON index
```

## Performance characteristics

| Operation | Time | Notes |
|---|---|---|
| Build (150 files) | ~100ms | Parse + FTS index |
| FTS query | ~1ms | SQLite FTS5 |
| Section query | ~2ms | Excludes index files |
| Manifest query | <1ms | JSON, no DB |
| Read lines | ~1ms | Direct file I/O |

Memory footprint:
- SQLite DB: ~1.3 MB (150 files, 8.6K lines)
- Manifest JSON: ~110 KB
- Markdown files: ~2.5 MB (on disk)

## Design decisions

### Why SQLite?

- Zero setup (single file database)
- Full-text search (FTS5) built-in
- ACID transactions
- Can be committed to version control
- No external dependencies

### Why manifest fallback?

- DB corruption shouldn't mean data loss
- Manifest enables queries even if SQLite fails
- Demonstrates separation of index from source
- Fits AI agent use case (resilience matters)

### Why markdown source?

- Human-readable and editable
- Version-controllable (git-friendly)
- Portable (no vendor lock-in)
- Pairs well with YAML frontmatter

### Why section-level pointers?

- Agents load only what they need
- Reduces context window pressure
- More precise than file-level retrieval
- Works well with LLM input length limits

### Why type categorization?

- Different knowledge serves different purposes
- User profile != feedback rules != project context
- Type filtering speeds up queries
- Reflects how agents actually think about knowledge

## Extending engram-agent-memory

### Custom knowledge types

Edit `src/engram/memory_store.py`, line ~80:

```python
# Add to the type check
if meta.get("type", "unknown") in ["user", "feedback", "project", "reference", "custom"]
```

### Custom frontmatter fields

Add to your markdown files and they'll be preserved in the manifest:

```yaml
---
name: my-node
type: reference
custom_field: custom_value
---
```

The `build()` process will include them in the manifest.

### Vector search integration

engram-agent-memory intentionally doesn't include embeddings. To add vector search:

1. Extend `MemoryStore` with an optional `embeddings_model`
2. In `build()`, compute embeddings for each section
3. Store in a separate table or file
4. Add a `semantic_query()` method using your embedding library

This keeps the core lightweight while allowing opt-in extensions.

## Limitations

- **Single-node**: No built-in replication
- **ACID, not distributed**: No multi-process writes
- **SQLite-bound**: No horizontal scaling
- **No native vector search**: Use external library if needed
- **Type system is simple**: 4 fixed types, not extensible in code

These are intentional — engram-agent-memory targets single-agent systems or small teams. For larger scales, consider adding a separate service layer.

## Future directions

- Async query API (async/await)
- Optional vector similarity (sqlite-vec)
- Replication/sync for multi-agent systems
- Web UI for knowledge browsing
- Automated consolidation and cleanup
- Per-agent knowledge isolation
