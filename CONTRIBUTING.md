# Contributing

Thanks for your interest in ism-mcp.

## Development

```bash
uv sync
./scripts/ci.sh        # fmt, lint, type, test: the single source of truth for a passing build
./scripts/ci.sh slow   # also exercise the real embedding model (downloads it once)
```

## Conventions

- TDD by default: write the failing test first, prove it fails, then implement.
- Conventional-commit subjects (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`, `ci:`, `build:`, `perf:`). Lowercase after the colon, no trailing period.
- No semicolons and no em-dash in commit messages, comments, or docstrings.
- Standard library where it suffices; type-annotate public APIs.
- See `CLAUDE.md` for the full house style.

## Pull requests

Open a pull request against `main`. CI must pass, and changes should stay focused. New behaviour needs a test.
