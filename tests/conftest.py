"""Pytest configuration and fixtures for engram-agent-memory tests."""

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_knowledge_dir():
    """Create a temporary directory with sample knowledge files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Sample user node
        (tmpdir / "user_profile.md").write_text(
            """---
name: user-profile
type: user
description: User identity and constraints
---

Owner=Alice
Age=30
Location=San Francisco
"""
        )

        # Sample feedback node
        (tmpdir / "feedback_communication.md").write_text(
            """---
name: feedback-communication
type: feedback
description: Communication style preferences
---

Direct, no filler.

## How to engage
Be concise and clear.

## What works
Short confirmations are fine.
"""
        )

        # Sample project node
        (tmpdir / "project_ai.md").write_text(
            """---
name: project-ai
type: project
description: AI research project
metadata:
  relations:
    see_also:
      - feedback-communication
---

Building AI agents.

## Status
In progress.

## Blockers
None.
"""
        )

        yield tmpdir


@pytest.fixture
def memory_store(temp_knowledge_dir):
    """Create a MemoryStore with temp directory."""
    from engram import MemoryStore

    store = MemoryStore(str(temp_knowledge_dir))
    return store
