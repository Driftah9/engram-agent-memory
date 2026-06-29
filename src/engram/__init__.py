"""
engram-agent-memory: Persistent, queryable knowledge storage for AI agents.

Markdown source + SQLite + manifest fallback. Survives database failures.
"""

from .memory_store import MemoryStore
from .query import fts_query, section_query
from .sanitizer import sanitize_fts
from .recall import smart_recall, keywords

__version__ = "0.2.0"
__all__ = [
    "MemoryStore", "fts_query", "section_query", "sanitize_fts",
    "smart_recall", "keywords",
]
