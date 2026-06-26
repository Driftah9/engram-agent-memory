"""MemoryStore — the main interface for engram-memory."""

import sqlite3
import json
import re
import time
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

        if not self.knowledge_dir.exists():
            self.knowledge_dir.mkdir(parents=True, exist_ok=True)

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

    def build(self) -> Dict:
        """Parse all markdown files and build SQLite index + manifest.

        Returns:
            Stats dict with keys: files, build_ms, db_kb, manifest_kb
        """
        self.db_path.unlink(missing_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.executescript(SCHEMA)

        files = sorted(
            f for f in self.knowledge_dir.rglob("*.md")
            if not any(
                part.startswith(".")
                for part in f.relative_to(self.knowledge_dir).parts[:-1]
            )
        )
        t0 = time.perf_counter()
        parsed = [self._parse_file(f) for f in files]
        manifest = {}

        now = time.time()
        for p in parsed:
            # New multi-user columns: existing markdown nodes default to owner/global
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
                conn.execute(
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
                "sections": [
                    {
                        "heading": s["heading"],
                        "line_start": s["line_start"],
                        "line_end": s["line_end"],
                    }
                    for s in p["sections"]
                ],
            }

        conn.commit()
        elapsed = time.perf_counter() - t0
        conn.close()

        self.manifest_path.write_text(json.dumps(manifest, indent=2))

        return {
            "files": len(parsed),
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

    def manifest_query(self, term: str) -> List[Dict]:
        """Query the manifest (works without DB).

        Args:
            term: Search term (substring match)

        Returns:
            List of matching nodes from manifest
        """
        if not self.manifest_path.exists():
            return []

        manifest = json.loads(self.manifest_path.read_text())
        term_lower = term.lower()

        return [
            {**v, "id": k}
            for k, v in manifest.items()
            if term_lower in v.get("description", "").lower()
            or term_lower in k.lower()
        ]
