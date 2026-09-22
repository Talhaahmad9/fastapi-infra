"""Shared pytest fixtures and configuration for fastapi-infra tests."""

import os
from typing import Final

import pytest

TEST_DSN_ENV_VAR: Final[str] = "FASTAPI_INFRA_TEST_POSTGRES_DSN"


@pytest.fixture(scope="session")
def test_postgres_dsn() -> str:
    """Return the test PostgreSQL DSN from environment or skip integration tests.

    Runtime package code never reads this environment variable.
    Only test fixtures read it.
    """
    dsn = os.environ.get(TEST_DSN_ENV_VAR)
    if not dsn or not dsn.strip():
        pytest.skip(f"Integration test skipped: {TEST_DSN_ENV_VAR} is not set")
    return dsn.strip()
