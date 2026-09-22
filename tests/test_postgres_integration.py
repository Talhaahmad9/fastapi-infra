"""Integration tests against a real PostgreSQL instance.

Only run when FASTAPI_INFRA_TEST_POSTGRES_DSN is provided in the test environment.
Runtime package code does not read this environment variable.
"""

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_infra.postgres import (
    PostgresConfig,
    PostgresDatabase,
    PostgresSSLMode,
)


def _make_test_config(
    dsn: str, *, check_health_on_startup: bool = False
) -> PostgresConfig:
    """Construct configuration for local/CI disposable integration tests.

    IMPORTANT: Standard PostgreSQL service containers (including official GitHub
    Actions service containers) run without TLS/SSL certificates enabled by default.
    Therefore, PostgresSSLMode.DISABLE is explicitly configured ONLY for these
    trusted, disposable test instances. Production deployments and remote hosted
    databases (like Supabase) must NEVER disable SSL.
    """
    return PostgresConfig(
        dsn=dsn,
        ssl_mode=PostgresSSLMode.DISABLE,
        check_health_on_startup=check_health_on_startup,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_integration_healthcheck(test_postgres_dsn: str) -> None:
    config = _make_test_config(test_postgres_dsn, check_health_on_startup=True)
    db = PostgresDatabase(config)
    try:
        # ping() should succeed without throwing
        await db.ping()
    finally:
        await db.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_integration_committed_transaction_persists(
    test_postgres_dsn: str,
) -> None:
    config = _make_test_config(test_postgres_dsn)
    db = PostgresDatabase(config)
    table_name = f"test_commit_{uuid.uuid4().hex[:8]}"

    try:
        # Create a unique temporary table
        async with db.session() as s:
            await s.execute(
                text(f"CREATE TABLE {table_name} (id int PRIMARY KEY, val text)")
            )
            await s.commit()

        # Insert and explicitly commit
        async with db.session() as s:
            await s.execute(
                text(f"INSERT INTO {table_name} (id, val) VALUES (1, 'hello')")
            )
            await s.commit()

        # Verify in a separate session that the row persists
        async with db.session() as s:
            res = await s.execute(text(f"SELECT val FROM {table_name} WHERE id = 1"))
            row = res.scalar_one_or_none()
            assert row == "hello"
    finally:
        # Clean up temporary table
        async with db.session() as s:
            await s.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
            await s.commit()
        await db.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_integration_uncommitted_transaction_rolls_back(
    test_postgres_dsn: str,
) -> None:
    config = _make_test_config(test_postgres_dsn)
    db = PostgresDatabase(config)
    table_name = f"test_rollback_{uuid.uuid4().hex[:8]}"

    try:
        async with db.session() as s:
            await s.execute(
                text(f"CREATE TABLE {table_name} (id int PRIMARY KEY, val text)")
            )
            await s.commit()

        # Insert without commit - session exit should roll it back
        async with db.session() as s:
            await s.execute(
                text(f"INSERT INTO {table_name} (id, val) VALUES (1, 'uncommitted')")
            )

        # Verify in a new session that nothing was committed
        async with db.session() as s:
            res = await s.execute(text(f"SELECT count(*) FROM {table_name}"))
            assert res.scalar_one() == 0
    finally:
        async with db.session() as s:
            await s.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
            await s.commit()
        await db.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_integration_exception_rolls_back(
    test_postgres_dsn: str,
) -> None:
    config = _make_test_config(test_postgres_dsn)
    db = PostgresDatabase(config)
    table_name = f"test_exc_{uuid.uuid4().hex[:8]}"

    try:
        async with db.session() as s:
            await s.execute(
                text(f"CREATE TABLE {table_name} (id int PRIMARY KEY, val text)")
            )
            await s.commit()

        with pytest.raises(RuntimeError):
            async with db.session() as s:
                await s.execute(
                    text(f"INSERT INTO {table_name} (id, val) VALUES (1, 'fail')")
                )
                raise RuntimeError("Simulated failure")

        async with db.session() as s:
            res = await s.execute(text(f"SELECT count(*) FROM {table_name}"))
            assert res.scalar_one() == 0
    finally:
        async with db.session() as s:
            await s.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
            await s.commit()
        await db.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_integration_separate_sessions_and_concurrency(
    test_postgres_dsn: str,
) -> None:
    config = _make_test_config(test_postgres_dsn)
    db = PostgresDatabase(config)

    try:
        # Separate calls must return distinct session instances
        async with db.session() as s1, db.session() as s2:
            assert s1 is not s2

        # Concurrent operations using one session per task
        async def worker(worker_id: int) -> int:
            async with db.session() as s:
                res = await s.execute(text(f"SELECT {worker_id}"))
                val = res.scalar_one()
                assert isinstance(val, int)
                return val

        results = await asyncio.gather(*(worker(i) for i in range(10)))
        assert results == list(range(10))
    finally:
        await db.dispose()


@pytest.mark.integration
def test_postgres_integration_fastapi_client(test_postgres_dsn: str) -> None:
    config = _make_test_config(test_postgres_dsn, check_health_on_startup=True)
    db = PostgresDatabase(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with db.lifespan():
            yield

    app = FastAPI(lifespan=lifespan)

    @app.get("/health-db")
    def db_health(
        session: Annotated[AsyncSession, Depends(db.session_dependency)],
    ) -> dict[str, int]:
        # Synchronous route handler in FastAPI runs in threadpool;
        # but session is async, so we can test an async endpoint
        return {"result": 42}

    @app.get("/health-db-async")
    async def db_health_async(
        session: Annotated[AsyncSession, Depends(db.session_dependency)],
    ) -> dict[str, int]:
        res = await session.execute(text("SELECT 42"))
        val: int = res.scalar_one()
        return {"result": val}

    with TestClient(app) as client:
        response = client.get(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            "/health-db-async"
        )
        assert response.status_code == 200  # pyright: ignore[reportUnknownMemberType]
        assert response.json() == {"result": 42}  # pyright: ignore[reportUnknownMemberType]
