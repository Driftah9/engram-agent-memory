# Contributing to engram-agent-memory

Thanks for your interest in contributing! This document covers how to submit quality work.

## Before you start

- **One problem per PR** — Pick ONE issue or feature, understand it deeply, implement it well
- **Human review required** — Every PR must be reviewed before submission. Do this yourself: read the complete diff and verify it makes sense
- **Check prior art** — Search existing issues and closed PRs; if similar work exists, explain why your approach is different
- **No speculative fixes** — Only fix problems you can demonstrate and test

## Workflow

### 1. Research
- Read the code you're about to change
- Understand *why* it exists, not just what it does
- Check the issue description for context
- Look at related code and tests

### 2. Implement
- Make the smallest change that solves the problem
- Don't add features beyond the scope
- Keep the code style consistent with the rest of the codebase
- Follow the "no comments unless surprising" rule

### 3. Test
- Write tests that verify your fix
- Run the full test suite: `pytest tests/`
- Test on at least one real knowledge base

### 4. Review yourself
- Read your own diff end-to-end
- Would this confuse someone else?
- Did you introduce any new bugs?
- Are there edge cases you missed?

### 5. Submit
- Push to your fork
- Open a PR with a clear description
- Reference any related issues (`Fixes #123`)
- Include test results in the PR description

## Code style

- Python 3.9+
- Follow PEP 8 (enforced by `ruff`)
- Format with `black` (100-char line length)
- Type hints for public APIs

```bash
# Format your code
black src/

# Check for style issues
ruff check src/

# Run tests
pytest tests/
```

## Submitting a PR

**Good PR title:**
- "Fix FTS5 query crash on apostrophes" ✓
- "Add async support to MemoryStore" ✓
- "Update dependencies" ✗ (too vague)

**Good PR description:**
```markdown
## Problem
Users with apostrophes in search terms (can't, don't) hit FTS5 syntax errors.

## Solution
Add sanitize_fts() to strip operator characters before MATCH queries.

## Test results
- 100/100 tests pass
- Tested with: user knowledge base (148 files, 8,606 lines)
- Edge cases covered: apostrophes, hyphens, wildcards, quotes

Fixes #42
```

**What will get your PR rejected:**
- No human review of the diff
- "Fixes X" but doesn't reference an issue
- Speculative changes beyond the scope
- Silent failures or broken tests
- No explanation of *why* the change is correct

## Questions?

Open an issue to discuss before implementing. Big changes should be discussed first.

---

**TL;DR:** Understand the problem → implement once → test properly → review yourself → submit with confidence.
