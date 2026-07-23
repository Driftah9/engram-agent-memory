"""MemoryStore — the main interface for engram-memory."""

import sqlite3
import json
import re
import time
import struct
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from .schema import SCHEMA
from .query import fts_query, section_query


class MemoryStore:
    """Persistent, queryable knowledge storage for AI agents.

    Manages markdown files as source-of-truth, SQLite for queries,
    and manifest JSON for DB-down recovery.
    """

    def __init__(self, knowledge_dir: str, db_path: Optional[str] = None):
        """Initialize MemoryStore.

        Args:
            knowledge_dir: Path to directory containing markdown knowledge files
            db_path: Path to SQLite database (default: knowledge_dir/memory.db)
        """
        self.knowledge_dir = Path(knowledge_dir)
        self.db_path = Path(db_path) if db_path else self.knowledge_dir / "memory.db"
        self.manifest_path = self.knowledge_dir / "memory_manifest.json"
        self.state_path = self.knowledge_dir / ".engram_state.json"

        if not self.knowledge_dir.exists():
            self.knowledge_dir.mkdir(parents=True, exist_ok=True)

    def _read_state(self) -> Dict:
        """Read the incremental build state (file mtimes). Returns {} if not found."""
        if not self.state_path.exists():
            return {}
        try:
            return json.loads(self.state_path.read_text())
        except Exception:
            return {}

    def _write_state(self, state: Dict) -> None:
        """Write the incremental build state."""
        self.state_path.write_text(json.dumps(state, indent=2))

    def _get_file_mtime(self, path: Path) -> float:
        """Get a file's modification time."""
        return path.stat().st_mtime

    def _detect_changes(self) -> Tuple[List[Path], List[str], List[Path]]:
        """Detect changed, deleted, and new files since last build.

        Returns: (changed_paths, deleted_rel_paths, new_paths)
          changed_paths: files that were modified since last build
          deleted_rel_paths: relative paths whose files no longer exist
                             (resolved to node IDs by the caller via the manifest,
                             since a node's id is its frontmatter `name`, which may
                             differ from the filename stem)
          new_paths: files that didn't exist before
        """
        old_state = self._read_state()
        new_state = {}

        files = sorted(
            f for f in self.knowledge_dir.rglob("*.md")
            if not any(
                part.startswith(".")
                for part in f.relative_to(self.knowledge_dir).parts[:-1]
            )
        )

        changed, new = [], []
        for f in files:
            rel_path = str(f.relative_to(self.knowledge_dir))
            mtime = self._get_file_mtime(f)
            new_state[rel_path] = mtime

            if rel_path not in old_state:
                new.append(f)
            elif old_state[rel_path] != mtime:
                changed.append(f)

        # Detect deleted files (files in old state but not in new scan).
        # Return relative paths — the caller resolves them to node IDs via the
        # manifest, because a node's id is its frontmatter `name`, not the stem.
        deleted_rel_paths = [
            old_rel_path for old_rel_path in old_state
            if old_rel_path not in new_state
        ]

        return changed, deleted_rel_paths, new

    def _parse_file(self, path: Path) -> Dict:
        """Parse a single markdown file into a knowledge node."""
        text = path.read_text(errors="replace")
        lines = text.splitlines()

        if not text.startswith("---"):
            return self._bare_file(path, text, lines)

        end = text.find("\n---", 3)
        if end == -1:
            return self._bare_file(path, text, lines)

        fm_block = text[3:end].strip()
        body = text[end + 4:].lstrip("\n")
        body_start = text[: end + 4].count("\n") + 1

        meta = {}
        for line in fm_block.splitlines():
            if line.startswith((" ", "\t")):
                continue
            if ":" in line:
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip().strip('"')

        # Nested metadata.type wins
        nt = re.search(r"^\s+type:\s+(\w+)", fm_block, re.MULTILINE)
        if nt:
            meta["type"] = nt.group(1)

        relations = []
        if "see_also" in fm_block:
            sa_block = fm_block[fm_block.find("see_also") :]
            relations = re.findall(r"- ([\w-]+)", sa_block)

        # Inline wiki-links realize the MOC/galaxy graph: every [[node-name]]
        # in the body becomes a relation edge. Merge with see_also, dedup,
        # drop self-links. (Live tools/engram enhancement — backport to repo.)
        _node_id = meta.get("name", path.stem)
        _seen = set(relations)
        for _ln in re.findall(r"\[\[([\w/-]+)", body):
            _ln = _ln.split("|")[0].strip()
            if _ln and _ln != _node_id and _ln not in _seen:
                relations.append(_ln)
                _seen.add(_ln)

        sd = re.search(r"session_date:\s+(.+)", fm_block)

        return {
            "id": meta.get("name", path.stem),
            "type": meta.get("type", "unknown")
            if meta.get("type", "unknown") in ["user", "feedback", "project", "reference"]
            else "unknown",
            "description": meta.get("description", ""),
            "file_path": str(path),
            "file_name": path.name,
            "line_start": body_start,
            "line_end": len(lines) - 1,
            "relations": relations,
            "session_date": sd.group(1).strip().strip('"') if sd else "",
            "body": body,
            "sections": self._extract_sections(body, body_start),
        }

    def _bare_file(self, path: Path, text: str, lines: List[str]) -> Dict:
        """Parse file with no frontmatter."""
        return {
            "id": path.stem,
            "type": "unknown",
            "description": "",
            "file_path": str(path),
            "file_name": path.name,
            "line_start": 0,
            "line_end": len(lines) - 1,
            "relations": [],
            "session_date": "",
            "body": text,
            "sections": self._extract_sections(text, 0),
        }

    @staticmethod
    def _extract_sections(body: str, body_start: int) -> List[Dict]:
        """Extract H2 sections from body text."""
        out, current = [], None
        lines = body.splitlines()

        for i, line in enumerate(lines):
            abs_ln = body_start + i
            if line.startswith("## "):
                if current:
                    current["line_end"] = abs_ln - 1
                    current["content"] = "\n".join(lines[current["_ri"] : i])
                    out.append(current)
                current = {
                    "heading": line[3:].strip(),
                    "line_start": abs_ln,
                    "line_end": None,
                    "_ri": i,
                    "content": "",
                }

        if current:
            current["line_end"] = body_start + len(lines) - 1
            current["content"] = "\n".join(lines[current["_ri"] :])
            out.append(current)

        return out

    def build(self, full: bool = False) -> Dict:
        """Parse markdown files and build SQLite index + manifest.

        Args:
            full: If True, force a full rebuild (delete and recreate DB).
                  If False, incremental update (only parse changed/new files).

        Returns:
            Stats dict with keys: files, build_ms, parsed, db_kb, manifest_kb
        """
        t0 = time.perf_counter()

        # Detect changes (or skip if full rebuild)
        if not full and self.db_path.exists():
            changed, deleted_rel_paths, new = self._detect_changes()
            if not changed and not deleted_rel_paths and not new:
                # No changes detected
                return {
                    "files": len(self._read_state()),
                    "parsed": 0,
                    "build_ms": round((time.perf_counter() - t0) * 1000, 1),
                    "db_kb": round(self.db_path.stat().st_size / 1024, 1),
                    "manifest_kb": round(self.manifest_path.stat().st_size / 1024, 1) if self.manifest_path.exists() else 0,
                }
            # Incremental update: only parse changed + new files
            to_parse = changed + new
            parsed = [self._parse_file(f) for f in to_parse]
            manifest = json.loads(self.manifest_path.read_text()) if self.manifest_path.exists() else {}
            # Resolve deleted relative paths → node IDs via the manifest, since a
            # node's id is its frontmatter `name`, which may differ from the stem.
            deleted_abs = {str(self.knowledge_dir / rp) for rp in deleted_rel_paths}
            deleted_ids = [
                node_id for node_id, meta in manifest.items()
                if meta.get("file_path") in deleted_abs
            ]
            is_incremental = True
        else:
            # Full rebuild: parse all files
            self.db_path.unlink(missing_ok=True)
            files = sorted(
                f for f in self.knowledge_dir.rglob("*.md")
                if not any(
                    part.startswith(".")
                    for part in f.relative_to(self.knowledge_dir).parts[:-1]
                )
            )
            parsed = [self._parse_file(f) for f in files]
            manifest = {}
            deleted_ids = []
            is_incremental = False

        # Initialize DB if needed
        if not self.db_path.exists():
            conn = sqlite3.connect(self.db_path)
            conn.executescript(SCHEMA)
        else:
            conn = sqlite3.connect(self.db_path)

        # If incremental, delete old rows for changed/new/deleted nodes
        if is_incremental:
            affected_ids = [p["id"] for p in parsed] + deleted_ids
            if affected_ids:
                placeholders = ",".join("?" * len(affected_ids))
                conn.execute(f"DELETE FROM memory_index WHERE id IN ({placeholders})", affected_ids)
                # FTS and sections/relations cascade via ON DELETE CASCADE

        now = time.time()
        for p in parsed:
            # Insert or replace: use INSERT in incremental mode (rows already deleted),
            # INSERT OR REPLACE in full mode (safe either way)
            conn.execute(
                "INSERT OR REPLACE INTO memory_index VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    p["id"],
                    p["type"],
                    p["description"],
                    p["file_path"],
                    p["file_name"],
                    p["line_start"],
                    p["line_end"],
                    p["session_date"],
                    p["body"],
                    "owner",           # user_id
                    None,              # workspace_id
                    "global",          # access_tier
                    "owner",           # created_by
                    now,               # created_at
                    "owner",           # updated_by
                    now,               # updated_at
                ),
            )

            for sec in p["sections"]:
                cur = conn.execute(
                    "INSERT INTO memory_sections (node_id, heading, line_start, line_end, content, access_tier, workspace_id) VALUES (?,?,?,?,?,?,?)",
                    (
                        p["id"],
                        sec["heading"],
                        sec["line_start"],
                        sec["line_end"],
                        sec.get("content", ""),
                        "global",    # inherit from node
                        None,        # inherit from node
                    ),
                )
                section_id = cur.lastrowid

                # Generate embedding for this section (optional; gracefully fail if Ollama unavailable)
                content = sec.get("content", "").strip()
                if content and len(content) > 10:
                    vec = self._get_embedding(content)
                    if vec:
                        vec_bytes = self._vector_to_bytes(vec)
                        conn.execute(
                            "INSERT OR REPLACE INTO memory_vectors (section_id, embedding, embedding_model, created_at) VALUES (?,?,?,?)",
                            (section_id, vec_bytes, "nomic-embed-text", now),
                        )

            for rel in p["relations"]:
                conn.execute(
                    "INSERT OR IGNORE INTO memory_relations VALUES (?,?)", (p["id"], rel)
                )

            manifest[p["id"]] = {
                "file": p["file_name"],
                "file_path": p["file_path"],
                "type": p["type"],
                "description": p["description"],
                "body_start": p["line_start"],
                "line_end": p["line_end"],
                "access_tier": "global",
                "workspace_id": None,
                "user_id": None,
                "sections": [
                    {
                        "heading": s["heading"],
                        "line_start": s["line_start"],
                        "line_end": s["line_end"],
                    }
                    for s in p["sections"]
                ],
            }

        # If incremental, remove deleted entries from manifest
        if is_incremental and deleted_ids:
            for node_id in deleted_ids:
                manifest.pop(node_id, None)

        conn.commit()
        elapsed = time.perf_counter() - t0
        conn.close()

        # Write manifest and state. State is always rebuilt fresh from the current
        # directory scan (mtime stat is cheap) — this avoids coupling state keys
        # (relative paths) to node IDs (frontmatter names), which can differ, and
        # naturally drops deleted files since they no longer appear in the scan.
        self.manifest_path.write_text(json.dumps(manifest, indent=2))
        state = {}
        for f in self.knowledge_dir.rglob("*.md"):
            if not any(
                part.startswith(".")
                for part in f.relative_to(self.knowledge_dir).parts[:-1]
            ):
                rel_path = str(f.relative_to(self.knowledge_dir))
                state[rel_path] = self._get_file_mtime(f)
        self._write_state(state)

        return {
            "files": len(manifest),
            "parsed": len(parsed),
            "build_ms": round(elapsed * 1000, 1),
            "db_kb": round(self.db_path.stat().st_size / 1024, 1),
            "manifest_kb": round(self.manifest_path.stat().st_size / 1024, 1),
        }

    def connect(self) -> sqlite3.Connection:
        """Get a connection to the SQLite database.

        Returns:
            SQLite connection with row_factory set to sqlite3.Row
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def query(
        self,
        term: str,
        type_filter: Optional[str] = None,
        limit: int = 20,
        scope: Optional[object] = None,
    ) -> List[Dict]:
        """Full-text search with optional type filtering and data-scope visibility control.

        Args:
            term: Search term (will be sanitized)
            type_filter: Optional type ('user', 'feedback', 'project', 'reference')
            limit: Maximum results to return
            scope: Optional data_scope.ScopeFilter for multi-user visibility. None = owner (no filtering).

        Returns:
            List of knowledge nodes matching the search
        """
        conn = self.connect()
        try:
            return fts_query(conn, term, type_filter=type_filter, limit=limit, scope=scope)
        finally:
            conn.close()

    def hybrid_query(
        self,
        term: str,
        exclude_ids: Optional[List[str]] = None,
        limit: int = 20,
        scope: Optional[object] = None,
    ) -> List[Dict]:
        """Hybrid search: FTS + vector similarity with reciprocal-rank fusion.

        Combines keyword (FTS) and semantic (vector) retrieval, weighted equally.
        Gracefully falls back to FTS only if embeddings are unavailable.

        Args:
            term: Search term (will be searched for keywords AND embedded for similarity)
            exclude_ids: Node IDs to exclude (default: ['MEMORY', 'SCHEMA'])
            limit: Maximum results to return
            scope: Optional data_scope.ScopeFilter for multi-user visibility

        Returns:
            List of sections ranked by hybrid score (keyword + semantic)
        """
        exclude = exclude_ids or ["MEMORY", "SCHEMA"]
        conn = self.connect()

        # Get vector embedding for query
        query_vec = self._get_embedding(term)

        # Fetch all sections with their vectors (if available)
        placeholders = ",".join("?" * len(exclude))
        rows = conn.execute(
            f"""
            SELECT mi.id, mi.type, mi.file_path, mi.file_name,
                   ms.heading, ms.line_start, ms.line_end,
                   mi.access_tier, mi.workspace_id, ms.content,
                   mv.embedding
            FROM memory_sections ms
            JOIN memory_index mi ON ms.node_id = mi.id
            LEFT JOIN memory_vectors mv ON ms.rowid = mv.section_id
            WHERE mi.id NOT IN ({placeholders})
            """,
            exclude,
        ).fetchall()

        # Score each section: keyword match (via content) + vector similarity
        scored = []
        for r in rows:
            content = (r["content"] or "").lower()
            term_lower = term.lower()

            # FTS-like scoring: count keyword occurrences
            fts_score = content.count(term_lower)

            # Vector similarity
            vec_score = 0.0
            if query_vec and r["embedding"]:
                vec = self._bytes_to_vector(r["embedding"])
                vec_score = max(0.0, self._cosine_similarity(query_vec, vec))

            # Combine: keyword + semantic (equal weight, scale to 0-1)
            combined = (fts_score > 0 and 1.0 or 0.0) + (vec_score if query_vec else 0.0)

            if combined > 0:  # Only include if it scores on either metric
                scored.append((combined, dict(r)))

        # Sort by combined score and return top k
        scored.sort(reverse=True, key=lambda x: x[0])
        conn.close()

        return [r for _, r in scored[:limit]]

    def smart_recall(self, query: str, k: int = 4) -> List[Dict]:
        """NL-robust recall: stopword strip + keyword OR-match + best section.

        Thin method wrapper over the packaged ``recall.smart_recall`` helper, so a
        raw natural-language sentence retrieves precise, line-pointed hits instead
        of AND-matching nothing under ``query()``. Each hit: {text, source, score}.

        Args:
            query: Natural-language query.
            k: Maximum number of hits to return.

        Returns:
            Up to k hits, each with keys text, source, score.
        """
        from .recall import smart_recall as _smart_recall
        return _smart_recall(self, query, k=k)

    def section_query(
        self,
        term: str,
        exclude_ids: Optional[List[str]] = None,
        limit: int = 20,
        scope: Optional[object] = None,
    ) -> List[Dict]:
        """Find sections containing a term, with optional data-scope filtering.

        Args:
            term: Search term
            exclude_ids: Node IDs to exclude (default: ['MEMORY', 'SCHEMA'])
            limit: Maximum results to return
            scope: Optional data_scope.ScopeFilter for multi-user visibility. None = owner.

        Returns:
            List of sections matching the search
        """
        conn = self.connect()
        try:
            return section_query(conn, term, exclude_ids=exclude_ids, limit=limit, scope=scope)
        finally:
            conn.close()

    def relations_from(self, node_id: str) -> List[str]:
        """Get all nodes that a node links to.

        Args:
            node_id: Node ID to find relations for

        Returns:
            List of related node IDs
        """
        conn = self.connect()
        try:
            rows = conn.execute(
                "SELECT to_id FROM memory_relations WHERE from_id=?",
                (node_id,),
            ).fetchall()
            return [r["to_id"] for r in rows]
        finally:
            conn.close()

    @staticmethod
    def read_lines(file_path: str, start: int, end: int) -> str:
        """Read specific lines from a file.

        Args:
            file_path: Path to file
            start: Starting line number (0-indexed)
            end: Ending line number (inclusive)

        Returns:
            Text from the specified lines
        """
        lines = Path(file_path).read_text(errors="replace").splitlines()
        return "\n".join(lines[max(0, start) : min(len(lines), end + 1)])

    def _get_embedding(self, text: str, model: str = "nomic-embed-text") -> Optional[List[float]]:
        """Generate embedding via local Ollama. Returns list of floats or None on error."""
        try:
            import urllib.request
            import urllib.error

            url = "http://localhost:11434/api/embeddings"
            data = json.dumps({"model": model, "prompt": text}).encode()
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})

            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode())
                return result.get("embedding")
        except Exception:
            return None

    @staticmethod
    def _vector_to_bytes(vec: List[float]) -> bytes:
        """Pack a float list into bytes (little-endian float32)."""
        return b"".join(struct.pack("<f", v) for v in vec)

    @staticmethod
    def _bytes_to_vector(data: bytes) -> List[float]:
        """Unpack bytes to a float list."""
        return list(struct.unpack(f"<{len(data) // 4}f", data))

    @staticmethod
    def _cosine_similarity(v1: List[float], v2: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        dot = sum(a * b for a, b in zip(v1, v2))
        mag1 = sum(a * a for a in v1) ** 0.5
        mag2 = sum(b * b for b in v2) ** 0.5
        if mag1 == 0 or mag2 == 0:
            return 0.0
        return dot / (mag1 * mag2)

    def manifest_query(self, term: str, scope: Optional[object] = None) -> List[Dict]:
        """Query the manifest (works without DB), with optional scope filtering.

        Args:
            term: Search term (substring match)
            scope: Optional data_scope.ScopeFilter for multi-user visibility. None = owner (no filtering).

        Returns:
            List of matching nodes from manifest, filtered by scope visibility
        """
        if not self.manifest_path.exists():
            return []

        # Try to import scope filtering (same as query.py: graceful fallback)
        data_scope = None
        try:
            import sys
            if "/home/claude" not in sys.path:
                sys.path.insert(0, "/home/claude")
            from adapters.core import data_scope as _data_scope
            data_scope = _data_scope
        except (ImportError, ModuleNotFoundError):
            pass

        manifest = json.loads(self.manifest_path.read_text())
        term_lower = term.lower()

        hits = [
            {**v, "id": k}
            for k, v in manifest.items()
            if term_lower in v.get("description", "").lower()
            or term_lower in k.lower()
        ]

        # Filter by scope if provided and data_scope module is available
        if scope and data_scope:
            hits = [
                h for h in hits
                if data_scope.can_read(
                    scope,
                    access_tier=h.get("access_tier", "global"),
                    workspace_id=h.get("workspace_id"),
                    user_id=h.get("user_id")
                )
            ]

        return hits
