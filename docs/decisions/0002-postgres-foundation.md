# ADR 0002: PostgreSQL and Supabase infrastructure foundation

## Status

Accepted for the pre-alpha foundation (Phase 1).

## Context

Phase 0 established package structure, toolchain, and type enforcement. Phase 1 introduces the first database capability: a reusable, typed PostgreSQL infrastructure slice designed for both standard PostgreSQL and Supabase-hosted PostgreSQL.

## Decisions

- **Published Optional Extra**: The package remains modular with no runtime database dependencies in the base install. Database functionality is published under the `postgres` extra:
  ```toml
  [project.optional-dependencies]
  postgres = [
      "psycopg[binary]>=3.3.6,<4",
      "sqlalchemy[asyncio]>=2.0.54,<3",
  ]
  ```
- **Driver and ORM Foundation**: We pair SQLAlchemy 2.0 Asyncio with Psycopg 3 (`postgresql+psycopg`). Psycopg 3 is the modern, actively maintained asynchronous PostgreSQL driver for Python.
- **Connection Pooling Ownership**: SQLAlchemy's `AsyncAdaptedQueuePool` owns client-side connection pooling. Psycopg's separate `psycopg_pool` is deliberately not layered underneath to avoid duplicate connection pooling mechanisms. `PostgresPoolConfig.size` must be strictly positive (`size > 0`), as SQLAlchemy interprets `0` as unlimited. When `pool=None` is passed in `PostgresConfig`, SQLAlchemy `NullPool` is used for consumers desiring zero application-side connection pooling.
- **Explicit Typed Configuration**: Runtime code never loads environment variables or `.env` files. Consuming applications load and validate configuration explicitly and inject `PostgresConfig`. Configuration is implemented via slotted, frozen standard dataclasses and string enums (`PostgresConnectionMode`, `PostgresSSLMode`). Pydantic is not required as a runtime dependency. `connection_timeout` is typed as an integer in seconds with an effective minimum of 2, matching libpq specification.
- **Connection Modes & Prepared Statements**:
  - `PostgresConnectionMode.DIRECT` and `PostgresConnectionMode.SESSION_POOLER`: Retain normal Psycopg 3 prepared statements.
  - `PostgresConnectionMode.TRANSACTION_POOLER` (e.g. Supabase port 6543 / PgBouncer): Configures Psycopg with `prepare_threshold=None` to disable prepared statements, preventing `prepared statement does not exist` errors in transaction pooling mode.
- **SSL Security by Default**: `ssl_mode` defaults to `PostgresSSLMode.REQUIRE` (libpq `require`), ensuring encrypted communication across public networks. Trusted disposable local/CI test containers without TLS explicitly use `PostgresSSLMode.DISABLE`.
- **Credential Protection**: Database passwords are never exposed in `repr()`, string representations, logs, validation errors, or documentation. `PostgresConfig.__repr__` explicitly renders DSNs with `hide_password=True`. Invalid DSN parsing suppresses underlying cause exceptions (`raise ... from None`) to prevent password leakage in tracebacks. URL encoding guidance recommends `quote(password, safe="")` rather than `quote_plus()`.
- **Transaction and Session Semantics**:
  - `PostgresDatabase` provides an `async def session()` context manager that yields a fresh `AsyncSession`.
  - Sessions are never cached or reused across requests or tasks.
  - Sessions are **never committed automatically**. The application must explicitly call `await session.commit()`.
  - If an unhandled exception occurs, or if an uncommitted transaction is left open upon exiting the context, it is automatically rolled back before closing the session. Both rollback and close are always attempted during cleanup.
  - If a primary session or application exception occurs, cleanup failures are preserved via PEP 678 exception notes (`add_note()`) indicating only the cleanup phase and error class name (`Session rollback failed (RuntimeError)` or `Session close failed (RuntimeError)`), never copying arbitrary raw error messages, parameters, or DSN secrets. When no primary exception exists, a single cleanup failure is raised directly, while multiple cleanup failures (e.g. rollback and close both failing) are raised as a `BaseExceptionGroup`.
- **FastAPI Lifespan and Dependency**:
  - `database.lifespan()` is a composable async context manager that performs an optional fail-fast `ping()` (`SELECT 1`) on startup and guarantees `dispose()` on shutdown. Primary startup or application exceptions are preserved if dispose also encounters an error, attaching only the cleanup phase and error class name (`Lifespan dispose failed (RuntimeError)`). When no primary exception exists, dispose failures surface directly.
  - `database.session_dependency` provides an async generator dependency yielding a request-scoped session for `Annotated[AsyncSession, Depends(database.session_dependency)]`.
- **Application Ownership of Migrations & Schemas**: The library does not create tables, run DDL, or manage Alembic migrations.
- **CI and Integration Testing**:
  - Unit tests run across Python 3.12, 3.13, and 3.14.
  - Integration tests run in CI against pinned official `postgres:17.11-bookworm` and `postgres:18.6-bookworm` service containers with deterministic health checks (`pg_isready -U testuser -d testdb`).
  - Hosted Supabase testing is opt-in via `FASTAPI_INFRA_TEST_POSTGRES_DSN` and does not run during standard CI.

## Consequences

- Applications importing `fastapi_infra.postgres` without installing `fastapi-infra[postgres]` receive an immediate, actionable `ImportError`.
- Base `fastapi_infra` imports remain instantaneous and completely free of third-party dependencies.
- Applications retain full control over transaction boundaries, migrations, and model declarations.
