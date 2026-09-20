# FastAPI Infra

Trusted infrastructure for FastAPI backends.

> Pre-alpha. No stable runtime API is promised yet; capabilities are added and verified incrementally.

FastAPI Infra is a modular Python package for reusable, security-conscious FastAPI infrastructure, with application-owned authentication and explicit optional integrations, without owning application business logic.

The project is independent and is not affiliated with or endorsed by the FastAPI project.

## Current milestone

Phase 0 establishes the typed, testable, buildable package foundation: Python 3.12+, uv, `uv_build`, Ruff, Pyright, pytest, packaging metadata, and CI. It does not implement application infrastructure features yet.

Long-term, the project plans to add carefully scoped authentication, opaque server-side sessions, database integrations, email, rate limiting, observability, and related infrastructure. These are planned capabilities, not current claims.

## Explicit non-goals

- Not a complete framework.
- Not an AI, RAG, or agent package.
- Not a universal SQL/Mongo CRUD abstraction.
- Not a generator yet.
- Does not use Supabase Auth.

## Python support

Python 3.12 is the minimum supported version. CI tests Python 3.12, 3.13, and 3.14; local development targets Python 3.14.

## Development

```powershell
uv sync
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
uv build
```

Runtime code never reads environment variables or `.env` files. Consuming applications own environment loading and pass validated, typed configuration into runtime components.

See the [Phase 0 decision record](docs/decisions/0001-phase-0.md) for the locked foundation decisions.

## License

MIT. See [LICENSE](LICENSE).
