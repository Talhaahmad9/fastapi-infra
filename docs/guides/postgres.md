# PostgreSQL and Supabase Guide

This guide describes how to configure, connect, and use PostgreSQL and Supabase with `fastapi-infra`.

## Installation

Install `fastapi-infra` with the `postgres` extra:

```bash
uv add "fastapi-infra[postgres]"
# or
pip install "fastapi-infra[postgres]"
```

## Architecture and Connection Modes

PostgreSQL deployments, especially managed platforms like Supabase, support multiple connection architectures. `fastapi-infra` represents these via `PostgresConnectionMode`:

### 1. Direct Connection (`PostgresConnectionMode.DIRECT`)
- **Use case**: Standard standalone PostgreSQL instances or Supabase direct connection (port 5432).
- **Behavior**: Uses standard client-side pooling via SQLAlchemy `AsyncAdaptedQueuePool`. Prepared statements are enabled by default for optimal performance.
- **Supabase Note**: Direct connections to Supabase resolve to IPv6 addresses. If your host environment does not support IPv6, use Supabase's session or transaction pooler (which support IPv4).

### 2. Supabase Session Pooler (`PostgresConnectionMode.SESSION_POOLER`)
- **Use case**: Connecting to Supabase through the Supavisor / PgBouncer session pooler (port 5432).
- **Behavior**: Client maintains a session across multiple transactions. Prepared statements remain enabled. Provides IPv4 compatibility.

### 3. Supabase Transaction Pooler (`PostgresConnectionMode.TRANSACTION_POOLER`)
- **Use case**: Connecting to Supabase transaction pooler (port 6543) or any PgBouncer running in transaction pooling mode.
- **Behavior**: Server connections are returned to the pool after each transaction. To prevent errors (`prepared statement does not exist`), `fastapi-infra` automatically disables prepared statements by setting `prepare_threshold=None` in Psycopg 3.
- **Pooling Recommendation**: If the server-side pooler already limits and recycles connections, you may set `pool=None` on `PostgresConfig` to use SQLAlchemy's `NullPool`.

## Password Percent-Encoding

If your database password contains special characters (such as spaces, `+`, `@`, `/`, `:`, `%`, `?`, `#`, `[`, or `]`), percent-encode them in your DSN using `urllib.parse.quote` with `safe=""`:

```python
from urllib.parse import quote

# Do NOT use quote_plus() for URL userinfo: in standard URL userinfo,
# '+' represents a literal plus sign rather than a space.
# Using quote(..., safe="") correctly encodes spaces, '+', '@', '/', ':', and '%':
raw_password = "pass word+with@symbols/and:colons%100"
safe_password = quote(raw_password, safe="")
dsn = f"postgresql://user:{safe_password}@db.example.com:5432/dbname"
```

## SSL Configuration

By default, `PostgresSSLMode.REQUIRE` is enforced. Available modes:
- `PostgresSSLMode.REQUIRE`: Default. Encrypts traffic; standard for cloud databases including Supabase.
- `PostgresSSLMode.VERIFY_CA`: Verifies that the server certificate was signed by a trusted CA.
- `PostgresSSLMode.VERIFY_FULL`: Verifies CA signature and matches the host name.
- `PostgresSSLMode.DISABLE`: Plaintext connection; only for trusted local/CI disposable test containers without TLS configured. Production and remote databases must NEVER use this.

## Example: FastAPI Application Setup

```python
from contextlib import asynccontextmanager
from typing import Annotated
from collections.abc import AsyncIterator

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

# 1. Application explicitly loads and supplies configuration (no ambient .env reading)
config = PostgresConfig(
    dsn="postgresql://app_user:app_password@db.example.com:5432/app_db",
    connection_mode=PostgresConnectionMode.DIRECT,
    ssl_mode=PostgresSSLMode.REQUIRE,
    connection_timeout=10,  # Decimal integer seconds (minimum 2)
    pool=PostgresPoolConfig(
        size=5, max_overflow=10
    ),  # size must be strictly positive (> 0)
    check_health_on_startup=True,
)

# 2. Instantiate PostgresDatabase
database = PostgresDatabase(config)


# 3. Compose lifespan
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with database.lifespan():
        yield


app = FastAPI(lifespan=lifespan)

# 4. Dependency for request-scoped AsyncSession
DbSession = Annotated[AsyncSession, Depends(database.session_dependency)]


@app.get("/items")
async def list_items(session: DbSession) -> list[str]:
    # Application explicitly controls transactions
    result = await session.execute(text("SELECT name FROM items"))
    return [row[0] for row in result.fetchall()]


@app.post("/items")
async def create_item(name: str, session: DbSession) -> dict[str, str]:
    await session.execute(
        text("INSERT INTO items (name) VALUES (:name)"), {"name": name}
    )
    # Transactions are never committed automatically:
    await session.commit()
    return {"status": "created", "name": name}
```

## Session and Transaction Boundaries

- **No Auto-Commit**: Sessions created with `database.session()` or injected via `database.session_dependency` will **never** commit automatically.
- **Rollback Guarantee**: If an exception occurs, or if the request handler completes without calling `commit()`, any active transaction is rolled back before the session is closed.
- **Concurrency**: An `AsyncSession` is not thread-safe or task-safe. Never share a single session between concurrent background tasks (`asyncio.gather`); each task should acquire its own session via `async with database.session() as session:`.

## Schema and Migrations

`fastapi-infra` strictly does not own database models, table creation (`metadata.create_all`), or migration frameworks. Applications should manage schemas using [Alembic](https://alembic.sqlalchemy.org/) or raw SQL migration tools.

## Testing Against Live or Hosted Databases

Integration tests require the `FASTAPI_INFRA_TEST_POSTGRES_DSN` environment variable:

```bash
# Run local integration tests against a test database
export FASTAPI_INFRA_TEST_POSTGRES_DSN="postgresql+psycopg://postgres:secret@localhost:5432/testdb"
uv run pytest -m integration

# Run non-destructive smoke test against hosted Supabase
export FASTAPI_INFRA_TEST_POSTGRES_DSN="postgresql+psycopg://postgres:[YOUR-PASSWORD]@aws-0-[REGION].pooler.supabase.com:5432/postgres"
uv run pytest -m hosted
```

Integration and smoke tests will cleanly skip when `FASTAPI_INFRA_TEST_POSTGRES_DSN` is not defined. Credentials are never logged or stored.
