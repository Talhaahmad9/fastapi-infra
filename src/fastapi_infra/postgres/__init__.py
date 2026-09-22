"""PostgreSQL infrastructure module for FastAPI Infra.

Exposes typed configuration, engine management, session dependency,
and application lifespan integration. Requires the optional extra:
`fastapi-infra[postgres]`.
"""

import importlib.util as _importlib_util

if (
    _importlib_util.find_spec("psycopg") is None
    or _importlib_util.find_spec("sqlalchemy") is None
):
    raise ImportError(
        "fastapi-infra requires the 'postgres' extra to use "
        "fastapi_infra.postgres. Install it with: "
        'uv add "fastapi-infra[postgres]" or pip install "fastapi-infra[postgres]".'
    )

del _importlib_util

from fastapi_infra.postgres._config import (  # noqa: E402
    PostgresConfig,
    PostgresConnectionMode,
    PostgresPoolConfig,
    PostgresSSLMode,
)
from fastapi_infra.postgres._database import PostgresDatabase  # noqa: E402

__all__ = [
    "PostgresConfig",
    "PostgresConnectionMode",
    "PostgresDatabase",
    "PostgresPoolConfig",
    "PostgresSSLMode",
]
