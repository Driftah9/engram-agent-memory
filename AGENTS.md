# engram-agent-memory — Agent Instructions

Quick reference for working on this project.

## Project structure

```
engram-agent-memory/
├── src/engram/              # Main package
│   ├── __init__.py
│   ├── memory_store.py      # MemoryStore class (main interface)
│   ├── query.py             # fts_query, section_query helpers
│   ├── sanitizer.py         # FTS5 input sanitization
│   └── schema.py            # SQLite schema definition
├── tests/                   # Test suite
│   ├── conftest.py          # Pytest fixtures
│   └── test_build.py        # Core tests
├── docs/                    # Documentation
│   ├── architecture.md      # Design and concepts
│   └── api.md               # Full API reference
├── README.md                # Project overview
├── CONTRIBUTING.md          # Contribution guidelines
└── pyproject.toml           # Package configuration
```

## Quick setup

```bash
# Install in development mode
pip install -e ".[dev]"

# Run tests
pytest tests/

# Format and check style
black src/
ruff check src/
```

## Key concepts

- **Knowledge nodes** — markdown files with YAML frontmatter (name, type, description, relations)
- **Types** — user, feedback, project, reference
- **Sections** — H2 headings that divide knowledge into retrievable chunks
- **Manifest** — JSON fallback index that works without SQLite

## Common tasks

### Add a feature
1. Create a test in `tests/test_*.py` that demonstrates the feature
2. Implement in `src/engram/`
3. Run `pytest` to verify
4. Update docs if needed

### Fix a bug
1. Write a test that reproduces the bug
2. Fix the code
3. Verify the test passes
4. Check for regressions: `pytest tests/`

### Update documentation
- API changes → update `docs/api.md`
- Architecture changes → update `docs/architecture.md`
- Usage examples → update `README.md`

## Testing

All tests use temporary directories (no side effects). Run with:

```bash
pytest tests/ -v                  # Verbose
pytest tests/test_build.py        # Single file
pytest -k "test_query"            # By name
pytest --cov=engram tests/        # Coverage
```

## Dependencies

Currently: **zero runtime dependencies** (uses only stdlib + SQLite)

Keep it that way. Any additions must be justified.

Dev dependencies (optional):
- pytest
- pytest-cov
- black
- ruff

## Release checklist

- [ ] All tests pass
- [ ] Documentation updated
- [ ] CHANGELOG entry
- [ ] Version bumped in `pyproject.toml`
- [ ] Commit and tag: `git tag v0.2.0`
- [ ] Build: `python -m build`
- [ ] Upload: `twine upload dist/*`

## Questions?

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.
