"""Typed configuration for PostgreSQL infrastructure."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy.engine.url import URL, make_url


class PostgresConnectionMode(StrEnum):
    """PostgreSQL connection architecture mode.

    DIRECT: Direct connection to PostgreSQL database or Supabase port 5432.
    SESSION_POOLER: Connection via session pooler (e.g. Supabase port 5432).
    TRANSACTION_POOLER: Connection via transaction pooler (e.g. Supabase port 6543
        or PgBouncer), which disables prepared statements (prepare_threshold=None).
    """

    DIRECT = "direct"
    SESSION_POOLER = "session_pooler"
    TRANSACTION_POOLER = "transaction_pooler"


class PostgresSSLMode(StrEnum):
    """PostgreSQL SSL connection mode."""

    DISABLE = "disable"
    REQUIRE = "require"
    VERIFY_CA = "verify_ca"
    VERIFY_FULL = "verify_full"

    @property
    def libpq_value(self) -> str:
        """Map enum value to the standard libpq sslmode parameter string."""
        mapping = {
            PostgresSSLMode.DISABLE: "disable",
            PostgresSSLMode.REQUIRE: "require",
            PostgresSSLMode.VERIFY_CA: "verify-ca",
            PostgresSSLMode.VERIFY_FULL: "verify-full",
        }
        return mapping[self]


@dataclass(frozen=True, slots=True)
class PostgresPoolConfig:
    """Client-side connection pool configuration for SQLAlchemy.

    Set size, max_overflow, timeout, recycle, and pre_ping.
    """

    size: int = 5
    max_overflow: int = 10
    timeout: float = 30.0
    recycle: int = 1800
    pre_ping: bool = True

    def __post_init__(self) -> None:
        if type(self.size) is not int or self.size <= 0:
            raise ValueError("PostgresPoolConfig.size must be strictly positive")
        if type(self.max_overflow) is not int or self.max_overflow < 0:
            raise ValueError("PostgresPoolConfig.max_overflow must be non-negative")
        if type(self.timeout) not in (int, float) or self.timeout <= 0:
            raise ValueError("PostgresPoolConfig.timeout must be strictly positive")
        if type(self.recycle) is not int or self.recycle < 0:
            raise ValueError("PostgresPoolConfig.recycle must be non-negative")


@dataclass(frozen=True, slots=True)
class PostgresConfig:
    """PostgreSQL infrastructure configuration.

    Runtime code never loads environment variables or .env files.
    The consuming application passes explicit, validated configuration.
    """

    dsn: str
    connection_mode: PostgresConnectionMode = PostgresConnectionMode.DIRECT
    ssl_mode: PostgresSSLMode = PostgresSSLMode.REQUIRE
    connection_timeout: int = 10
    pool: PostgresPoolConfig | None = PostgresPoolConfig()
    check_health_on_startup: bool = True

    def __post_init__(self) -> None:
        if not self.dsn or not self.dsn.strip():
            raise ValueError("PostgresConfig.dsn must be a non-empty string")
        if type(self.connection_timeout) is not int:
            raise ValueError("PostgresConfig.connection_timeout must be an integer")
        if self.connection_timeout < 2:
            raise ValueError(
                "PostgresConfig.connection_timeout must be at least 2 seconds"
            )

        # Validate URL parsing and dialect normalization without leaking password
        try:
            url = make_url(self.dsn)
        except Exception:
            raise ValueError("PostgresConfig.dsn is not a valid database URL") from None

        backend = url.get_backend_name()
        if backend not in ("postgres", "postgresql"):
            raise ValueError(
                f"PostgresConfig requires a PostgreSQL URL, got dialect: {backend!r}"
            )

        # If a specific driver is explicitly given in the URL (e.g. postgresql+asyncpg://),
        # ensure it is psycopg 3 ('postgresql+psycopg://')
        if "+" in url.drivername:
            driver = url.get_driver_name()
            if driver != "psycopg":
                raise ValueError(
                    "PostgresConfig only supports the Psycopg 3 driver ('psycopg'), "
                    f"got: {driver!r}"
                )

    @property
    def normalized_url(self) -> URL:
        """Return a SQLAlchemy URL normalized to the postgresql+psycopg dialect."""
        url = make_url(self.dsn)
        return url.set(drivername="postgresql+psycopg")

    def build_connect_args(self) -> dict[str, Any]:
        """Construct Psycopg 3 connect_args based on SSL and connection mode."""
        connect_args: dict[str, Any] = {
            "sslmode": self.ssl_mode.libpq_value,
            "connect_timeout": self.connection_timeout,
        }
        if self.connection_mode == PostgresConnectionMode.TRANSACTION_POOLER:
            # Transaction poolers cannot use named prepared statements
            connect_args["prepare_threshold"] = None

        return connect_args

    def __repr__(self) -> str:
        try:
            url = make_url(self.dsn)
            redacted_dsn = url.render_as_string(hide_password=True)
        except Exception:
            redacted_dsn = "***"

        return (
            f"PostgresConfig(dsn={redacted_dsn!r}, "
            f"connection_mode={self.connection_mode!r}, "
            f"ssl_mode={self.ssl_mode!r}, "
            f"connection_timeout={self.connection_timeout!r}, "
            f"pool={self.pool!r}, "
            f"check_health_on_startup={self.check_health_on_startup!r})"
        )
