"""Unit tests for PostgreSQL configuration and validation."""

import dataclasses
import traceback

import pytest

from fastapi_infra.postgres._config import (
    PostgresConfig,
    PostgresConnectionMode,
    PostgresPoolConfig,
    PostgresSSLMode,
)


@pytest.mark.unit
def test_postgres_ssl_mode_libpq_values() -> None:
    assert PostgresSSLMode.DISABLE.libpq_value == "disable"
    assert PostgresSSLMode.REQUIRE.libpq_value == "require"
    assert PostgresSSLMode.VERIFY_CA.libpq_value == "verify-ca"
    assert PostgresSSLMode.VERIFY_FULL.libpq_value == "verify-full"


@pytest.mark.unit
def test_pool_config_defaults() -> None:
    pool = PostgresPoolConfig()
    assert pool.size == 5
    assert pool.max_overflow == 10
    assert pool.timeout == 30.0
    assert pool.recycle == 1800
    assert pool.pre_ping is True


@pytest.mark.unit
def test_pool_config_validation() -> None:
    # Regression test: pool size=0 means unlimited in SQLAlchemy, so size must be > 0
    with pytest.raises(ValueError, match="size must be strictly positive"):
        PostgresPoolConfig(size=0)

    with pytest.raises(ValueError, match="size must be strictly positive"):
        PostgresPoolConfig(size=-1)

    with pytest.raises(ValueError, match="max_overflow must be non-negative"):
        PostgresPoolConfig(max_overflow=-1)

    with pytest.raises(ValueError, match="timeout must be strictly positive"):
        PostgresPoolConfig(timeout=0)

    with pytest.raises(ValueError, match="recycle must be non-negative"):
        PostgresPoolConfig(recycle=-1)


@pytest.mark.unit
def test_config_immutability() -> None:
    config = PostgresConfig(dsn="postgresql://user:pass@localhost:5432/db")
    with pytest.raises(dataclasses.FrozenInstanceError):
        # pyright: ignore[reportAttributeAccessIssue]
        config.dsn = "new_dsn"  # type: ignore[misc]

    pool = PostgresPoolConfig()
    with pytest.raises(dataclasses.FrozenInstanceError):
        # pyright: ignore[reportAttributeAccessIssue]
        pool.size = 20  # type: ignore[misc]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("input_dsn", "expected_normalized"),
    [
        (
            "postgresql://alice:secret@localhost:5432/mydb",
            "postgresql+psycopg://alice:secret@localhost:5432/mydb",
        ),
        (
            "postgres://bob:secret2@db.example.com/otherdb",
            "postgresql+psycopg://bob:secret2@db.example.com/otherdb",
        ),
        (
            "postgresql+psycopg://carol:secret3@127.0.0.1:5432/testdb",
            "postgresql+psycopg://carol:secret3@127.0.0.1:5432/testdb",
        ),
    ],
)
def test_dsn_normalization(input_dsn: str, expected_normalized: str) -> None:
    config = PostgresConfig(dsn=input_dsn)
    normalized_str = config.normalized_url.render_as_string(hide_password=False)
    assert normalized_str == expected_normalized


@pytest.mark.unit
@pytest.mark.parametrize(
    "invalid_dsn",
    [
        "mysql://user:pass@localhost/db",
        "sqlite:///test.db",
        "mongodb://localhost:27017",
        "postgresql+asyncpg://user:pass@localhost/db",
        "postgresql+psycopg2://user:pass@localhost/db",
    ],
)
def test_dsn_unsupported_schemes_rejected(invalid_dsn: str) -> None:
    with pytest.raises(ValueError, match="PostgresConfig"):
        PostgresConfig(dsn=invalid_dsn)


@pytest.mark.unit
def test_empty_dsn_rejected() -> None:
    with pytest.raises(ValueError, match="non-empty string"):
        PostgresConfig(dsn="")
    with pytest.raises(ValueError, match="non-empty string"):
        PostgresConfig(dsn="   ")


@pytest.mark.unit
def test_connection_timeout_validation() -> None:
    valid_config = PostgresConfig(
        dsn="postgresql://user:pass@localhost:5432/db",
        connection_timeout=10,
    )
    assert valid_config.connection_timeout == 10
    assert isinstance(valid_config.connection_timeout, int)

    # Minimum effective timeout in libpq is 2 seconds
    with pytest.raises(ValueError, match="must be at least 2 seconds"):
        PostgresConfig(
            dsn="postgresql://user:pass@localhost:5432/db",
            connection_timeout=1,
        )

    with pytest.raises(ValueError, match="must be at least 2 seconds"):
        PostgresConfig(
            dsn="postgresql://user:pass@localhost:5432/db",
            connection_timeout=0,
        )

    with pytest.raises(ValueError, match="must be at least 2 seconds"):
        PostgresConfig(
            dsn="postgresql://user:pass@localhost:5432/db",
            connection_timeout=-5,
        )

    # Rejection of fractional values
    with pytest.raises(ValueError, match="must be an integer"):
        PostgresConfig(
            dsn="postgresql://user:pass@localhost:5432/db",
            connection_timeout=2.5,  # type: ignore[arg-type]
        )

    # Rejection of booleans (which are ints in Python but invalid timeout values)
    with pytest.raises(ValueError, match="must be an integer"):
        PostgresConfig(
            dsn="postgresql://user:pass@localhost:5432/db",
            connection_timeout=True,  # type: ignore[arg-type]
        )

    with pytest.raises(ValueError, match="must be an integer"):
        PostgresConfig(
            dsn="postgresql://user:pass@localhost:5432/db",
            connection_timeout=False,  # type: ignore[arg-type]
        )


@pytest.mark.unit
def test_malformed_dsn_does_not_leak_secret_in_exception_or_traceback() -> None:
    distinctive_secret = "TOP_SECRET_PASSWORD_XYZ_12345"
    # DSN with invalid port syntax that causes URL parsing error
    malformed_dsn = (
        f"postgresql://appuser:{distinctive_secret}@localhost:notaport/dbname"
    )

    with pytest.raises(ValueError, match="not a valid database URL") as exc_info:
        PostgresConfig(dsn=malformed_dsn)

    # Assert secret is absent from string representation and repr
    assert distinctive_secret not in str(exc_info.value)
    assert distinctive_secret not in repr(exc_info.value)

    # Assert underlying SQLAlchemy error is suppressed from cause (from None)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True

    # Assert formatted traceback does not expose the secret
    tb_output = "".join(traceback.format_exception(exc_info.value))
    assert distinctive_secret not in tb_output


@pytest.mark.unit
def test_password_redacted_in_repr() -> None:
    raw_password = "SuperSecretPassword123!"
    config = PostgresConfig(
        dsn=f"postgresql://myuser:{raw_password}@localhost:5432/mydb",
        connection_mode=PostgresConnectionMode.DIRECT,
        ssl_mode=PostgresSSLMode.REQUIRE,
    )
    rendered_repr = repr(config)
    assert raw_password not in rendered_repr
    assert "***" in rendered_repr
    assert "myuser" in rendered_repr


@pytest.mark.unit
def test_connect_args_direct_and_session_pooler() -> None:
    for mode in (PostgresConnectionMode.DIRECT, PostgresConnectionMode.SESSION_POOLER):
        config = PostgresConfig(
            dsn="postgresql://user:pass@localhost:5432/db",
            connection_mode=mode,
            ssl_mode=PostgresSSLMode.VERIFY_FULL,
            connection_timeout=15,
        )
        args = config.build_connect_args()
        assert args["sslmode"] == "verify-full"
        assert args["connect_timeout"] == 15
        assert isinstance(args["connect_timeout"], int)
        assert "prepare_threshold" not in args


@pytest.mark.unit
def test_connect_args_transaction_pooler_disables_prepared_statements() -> None:
    config = PostgresConfig(
        dsn="postgresql://user:pass@localhost:5432/db",
        connection_mode=PostgresConnectionMode.TRANSACTION_POOLER,
        ssl_mode=PostgresSSLMode.REQUIRE,
        connection_timeout=5,
    )
    args = config.build_connect_args()
    assert args["sslmode"] == "require"
    assert args["connect_timeout"] == 5
    assert isinstance(args["connect_timeout"], int)
    assert args["prepare_threshold"] is None
