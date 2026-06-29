# API Reference

## MemoryStore

Main interface for engram-agent-memory.

### `__init__(knowledge_dir, db_path=None)`

Initialize a memory store.

**Arguments:**
- `knowledge_dir` (str): Path to directory containing markdown knowledge files
- `db_path` (str, optional): Path to SQLite database. Defaults to `knowledge_dir/memory.db`

**Example:**
```python
store = MemoryStore("./knowledge")
store = MemoryStore("/data/agent-knowledge", db_path="/var/cache/memory.db")
```

### `build() → dict`

Parse all markdown files and build SQLite index + manifest.

Creates:
- SQLite database with indexed knowledge nodes
- Manifest JSON for fallback queries
- Triggers for maintaining FTS5 index

**Returns:**
```python
{
    "files": 148,          # Number of markdown files parsed
    "build_ms": 82.1,      # Build time in milliseconds
    "db_kb": 1312.0,       # SQLite database size in KB
    "manifest_kb": 109.6   # Manifest.json size in KB
}
```

**Example:**
```python
stats = store.build()
print(f"Built index for {stats['files']} files in {stats['build_ms']}ms")
```

---

### `query(term, type_filter=None, limit=20) → List[Dict]`

Full-text search with optional type filtering.

**Arguments:**
- `term` (str): Search term (will be sanitized)
- `type_filter` (str, optional): Filter by type (`user`, `feedback`, `project`, `reference`)
- `limit` (int): Maximum number of results (default: 20)

**Returns:**
List of dicts with keys:
- `id` — node identifier
- `type` — knowledge type
- `file_name` — markdown file name
- `file_path` — full path to file
- `line_start` — body start line number
- `line_end` — body end line number

**Example:**
```python
# Search across all types
results = store.query("budget")

# Search within a specific type
feedback = store.query("communication", type_filter="feedback")

# Limit results
top_10 = store.query("nexus", limit=10)

# If result found, read the lines
if results:
    node = results[0]
    content = store.read_lines(node["file_path"], node["line_start"], node["line_end"])
```

---

### `section_query(term, exclude_ids=None, limit=20) → List[Dict]`

Find sections whose content or heading contains a term.

Excludes index files (MEMORY, SCHEMA) by default, so results are always real content nodes.

**Arguments:**
- `term` (str): Search term
- `exclude_ids` (List[str], optional): Node IDs to exclude (default: `['MEMORY', 'SCHEMA']`)
- `limit` (int): Maximum results (default: 20)

**Returns:**
List of dicts with keys:
- `id` — node identifier
- `type` — knowledge type
- `file_path` — full path to file
- `file_name` — markdown file name
- `heading` — section heading
- `line_start` — section start line
- `line_end` — section end line

**Example:**
```python
# Find sections about renewal date
sections = store.section_query("renewal date")

# Read the section content
if sections:
    s = sections[0]
    content = store.read_lines(s["file_path"], s["line_start"], s["line_end"])
    print(f"{s['heading']}: {content}")

# Exclude additional nodes
sections = store.section_query("budget", exclude_ids=["MEMORY", "SCHEMA", "other-index"])
```

---

### `smart_recall(query, k=4) → List[Dict]`

Natural-language-robust recall. Unlike `query()` (which AND-matches every token via
FTS), this strips stopwords, OR-matches the keywords, and returns the best-matching
**section** per node with exact line pointers — so a long prompt still retrieves
something useful.

**Arguments:**
- `query` (str): A natural-language question or phrase
- `k` (int): Maximum hits (default: 4)

**Returns:**
List of dicts with keys `text`, `source` (`engram:<file>:<start>-<end>`), `score`.

**Example:**
```python
hits = store.smart_recall("how is the manifest fallback supposed to work")
for h in hits:
    print(h["source"], "→", h["text"][:80])
```

---

### `relations_from(node_id) → List[str]`

Get all nodes that a node links to — via `see_also` frontmatter **and** inline
`[[wiki-links]]` in the body.

**Arguments:**
- `node_id` (str): Node identifier

**Returns:**
List of related node IDs (may be empty if no relations)

**Example:**
```python
related = store.relations_from("fix-live-not-nexus")
# ['nexus-design-principle', 'dev-order', ...]

# Chain relations
for related_id in related:
    further = store.relations_from(related_id)
    print(f"{related_id} is also related to: {further}")
```

---

### `read_lines(file_path, start, end) → str`

Read specific lines from a file.

**Arguments:**
- `file_path` (str): Path to file
- `start` (int): Starting line number (0-indexed)
- `end` (int): Ending line number (inclusive)

**Returns:**
Text from the specified lines (newline-separated)

**Example:**
```python
content = store.read_lines("/path/to/user_profile.md", 14, 32)
print(content)
```

---

### `manifest_query(term) → List[Dict]`

Query the manifest (works without SQLite).

Useful when the database is unavailable. Searches node IDs and descriptions only (not full content).

**Arguments:**
- `term` (str): Search term (substring match, case-insensitive)

**Returns:**
List of matching nodes from the manifest JSON

**Example:**
```python
# If the database is down, fall back to manifest
try:
    results = store.query("budget")
except Exception:
    results = store.manifest_query("budget")
    print("Using manifest fallback")
```

---

### `connect() → sqlite3.Connection`

Get a connection to the SQLite database.

**Returns:**
SQLite connection with `row_factory` set to `sqlite3.Row` (dict-like access)

**Example:**
```python
conn = store.connect()
try:
    # Custom SQL queries
    rows = conn.execute("SELECT * FROM memory_index WHERE type=?", ("feedback",)).fetchall()
    for row in rows:
        print(row["id"], row["description"])
finally:
    conn.close()
```

---

## Functions

### `fts_query(conn, term, type_filter=None, limit=20) → List[Dict]`

Low-level FTS5 query function (used by `MemoryStore.query()`).

Import from `engram.query`:
```python
from engram import fts_query

results = fts_query(conn, "budget", type_filter="user")
```

---

### `section_query(conn, term, exclude_ids=None, limit=20) → List[Dict]`

Low-level section search function (used by `MemoryStore.section_query()`).

Import from `engram.query`:
```python
from engram import section_query

sections = section_query(conn, "renewal date")
```

---

### `sanitize_fts(term) → str`

Strip FTS5 operator characters from user input.

Safe to use before any FTS query to prevent syntax errors.

**Arguments:**
- `term` (str): Raw user input

**Returns:**
Sanitized term safe for FTS5 MATCH

**Example:**
```python
from engram import sanitize_fts

safe = sanitize_fts("can't")  # → "cant"
safe = sanitize_fts("home-buyer")  # → "home buyer"
safe = sanitize_fts("(advanced)*")  # → "advanced"
```

---

## Examples

### Single-agent memory

```python
from engram import MemoryStore

# Initialize
store = MemoryStore("./knowledge")
store.build()

# On each agent session
def agent_query(user_input):
    # Search knowledge base
    results = store.query(user_input)
    
    if results:
        # Load relevant knowledge
        node = results[0]
        context = store.read_lines(
            node["file_path"],
            node["line_start"],
            node["line_end"]
        )
        return f"Relevant knowledge: {context}"
    
    return "No relevant knowledge found"
```

### Multi-agent shared knowledge

```python
# Shared knowledge store accessed by multiple agents
store = MemoryStore("/shared/knowledge")

# Agent 1: Add new knowledge (manually or via sync)
# ... user updates markdown files ...
store.build()  # Rebuild index

# Agent 2: Query the shared knowledge
feedback = store.query("communication style", type_filter="feedback")
projects = store.section_query("current status")
```

### Graceful DB fallback

```python
def resilient_query(store, term):
    """Query with automatic fallback if DB is unavailable."""
    try:
        # Try fast query
        return store.query(term)
    except Exception as e:
        print(f"Database unavailable ({e}), using manifest fallback")
        # Fall back to JSON-based query
        return store.manifest_query(term)
```

### Following relation chains

```python
def find_related_knowledge(store, node_id, depth=2):
    """Recursively find all related knowledge."""
    visited = set()
    
    def traverse(current_id, d):
        if current_id in visited or d == 0:
            return []
        visited.add(current_id)
        
        related = store.relations_from(current_id)
        result = [current_id]
        
        for rel_id in related:
            result.extend(traverse(rel_id, d - 1))
        
        return result
    
    return traverse(node_id, depth)

# Usage
related = find_related_knowledge(store, "fix-live-not-nexus", depth=3)
print(f"Found {len(related)} related nodes")
```
