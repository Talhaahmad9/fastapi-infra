# FastAPI Infra

Trusted infrastructure for FastAPI backends.

> Pre-alpha. No stable runtime API is promised yet; capabilities are added and verified incrementally.

FastAPI Infra is a modular Python package for reusable, security-conscious FastAPI infrastructure, with application-owned authentication and explicit optional integrations, without owning application business logic.

The project is independent and is not affiliated with or endorsed by the FastAPI project.

## Current milestone

Phase 1 provides an experimental, typed PostgreSQL infrastructure slice (supporting standard PostgreSQL and Supabase PostgreSQL).

Base installation has zero runtime dependencies. Database features require the `postgres` optional extra:

```bash
uv add "fastapi-infra[postgres]"
# or
pip install "fastapi-infra[postgres]"
```

### PostgreSQL Quickstart

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_infra.postgres import (
    PostgresConfig,
    PostgresConnectionMode,
    PostgresDatabase,
    PostgresPoolConfig,
    PostgresSSLMode,
)

# 1. Provide typed, explicit configuration (runtime never reads .env files)
config = PostgresConfig(
    dsn="postgresql://user:password@db.example.com:5432/mydb",
    connection_mode=PostgresConnectionMode.DIRECT,
    ssl_mode=PostgresSSLMode.REQUIRE,
    connection_timeout=10,
    pool=PostgresPoolConfig(size=5, max_overflow=10),
    check_health_on_startup=True,
)

# 2. Initialize the database manager
database = PostgresDatabase(config)


# 3. Compose lifespan into your FastAPI app
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with database.lifespan():
        yield


app = FastAPI(lifespan=lifespan)

# 4. Inject a request-scoped AsyncSession
DbSession = Annotated[AsyncSession, Depends(database.session_dependency)]


@app.get("/health")
async def health(session: DbSession) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    return {"status": "healthy"}
```

> **Note on SSL**: `PostgresConfig` enforces secure TLS by default (`ssl_mode=PostgresSSLMode.REQUIRE`). If connecting to a local disposable development container (e.g. standard local Docker or CI container without certificates configured), you must explicitly set `ssl_mode=PostgresSSLMode.DISABLE`.

Consuming applications strictly own environment loading, models, transactions/commits, and Alembic migrations. Supabase is treated as standard PostgreSQL; no Supabase SDK or Supabase Auth is used.

See the [PostgreSQL Guide](docs/guides/postgres.md) and [Phase 1 ADR](docs/decisions/0002-postgres-foundation.md) for detailed configuration, connection modes, and pooling strategies.

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
uv sync --extra postgres
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pyright --verifytypes fastapi_infra --ignoreexternal
uv run pytest -m unit
uv build
```

Runtime code never reads environment variables or `.env` files. Consuming applications own environment loading and pass validated, typed configuration into runtime components.

See the [Phase 0 decision record](docs/decisions/0001-phase-0.md) and [Phase 1 decision record](docs/decisions/0002-postgres-foundation.md).

## License

MIT. See [LICENSE](LICENSE).
