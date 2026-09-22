"""Opt-in smoke test for hosted Supabase PostgreSQL.

Skips unless FASTAPI_INFRA_TEST_POSTGRES_DSN is provided in the test environment.
Performs only a non-destructive ping().
Never outputs credentials or prints the DSN.
"""

import pytest

from fastapi_infra.postgres import (
    PostgresConfig,
    PostgresConnectionMode,
    PostgresDatabase,
    PostgresSSLMode,
)


@pytest.mark.hosted
@pytest.mark.asyncio
async def test_supabase_postgres_smoke(test_postgres_dsn: str) -> None:
    # Recommended Supabase configuration: session pooler (port 5432)
    config = PostgresConfig(
        dsn=test_postgres_dsn,
        connection_mode=PostgresConnectionMode.SESSION_POOLER,
        ssl_mode=PostgresSSLMode.REQUIRE,
        check_health_on_startup=True,
    )
    db = PostgresDatabase(config)
    try:
        # Non-destructive ping only
        await db.ping()
    finally:
        await db.dispose()
