"""PostgreSQL database engine and session manager."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from fastapi_infra.postgres._config import PostgresConfig


class PostgresDatabase:
    """PostgreSQL database infrastructure wrapper.

    Creates an AsyncEngine and async_sessionmaker[AsyncSession].
    Provides session context management, FastAPI dependency yielding,
    startup ping/health-check, and engine disposal.
    """

    def __init__(self, config: PostgresConfig) -> None:
        self._config = config
        self._engine: AsyncEngine = self._create_engine(config)
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

    def _create_engine(self, config: PostgresConfig) -> AsyncEngine:
        url = config.normalized_url
        connect_args = config.build_connect_args()

        engine_kwargs: dict[str, Any] = {
            "hide_parameters": True,
            "echo": False,
            "connect_args": connect_args,
        }

        if config.pool is None:
            engine_kwargs["poolclass"] = NullPool
        else:
            engine_kwargs["pool_size"] = config.pool.size
            engine_kwargs["max_overflow"] = config.pool.max_overflow
            engine_kwargs["pool_timeout"] = config.pool.timeout
            engine_kwargs["pool_recycle"] = config.pool.recycle
            engine_kwargs["pool_pre_ping"] = config.pool.pre_ping

        return create_async_engine(url, **engine_kwargs)

    @property
    def config(self) -> PostgresConfig:
        """Return the configuration used by this database."""
        return self._config

    @property
    def engine(self) -> AsyncEngine:
        """Typed read-only access to the underlying SQLAlchemy AsyncEngine."""
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        """Typed read-only access to the underlying async_sessionmaker."""
        return self._session_factory

    async def ping(self) -> None:
        """Perform a fail-fast health check by executing SELECT 1.

        Returns None on success.
        Propagates original SQLAlchemy/Psycopg connection exceptions without swallowing.
        """
        async with self._engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def dispose(self) -> None:
        """Dispose of the engine and all pooled connections.

        Safe to call during application shutdown.
        """
        await self._engine.dispose()

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Async context manager that creates and yields an AsyncSession.

        Guarantees:
        - Creates a fresh AsyncSession per call (never cached or reused).
        - Never automatically commits.
        - Automatically rolls back on unhandled exceptions.
        - Automatically rolls back any remaining active transaction during cleanup.
        - Always attempts both rollback and close.
        - Preserves primary session-body exceptions without masking by cleanup errors.
        - Surfaces cleanup failures normally when no primary exception exists.
        """
        session: AsyncSession = self._session_factory()
        body_exc: BaseException | None = None
        try:
            yield session
        except BaseException as exc:
            body_exc = exc
            raise
        finally:
            cleanup_errors: list[tuple[str, BaseException]] = []

            # 1. Roll back uncommitted transaction if active
            try:
                if session.in_transaction():
                    await session.rollback()
            except BaseException as exc:
                cleanup_errors.append(("rollback", exc))

            # 2. Always attempt close, even if rollback failed
            try:
                await session.close()
            except BaseException as exc:
                cleanup_errors.append(("close", exc))

            if cleanup_errors:
                if body_exc is not None:
                    for phase, err in cleanup_errors:
                        body_exc.add_note(
                            f"Session {phase} failed ({type(err).__name__})"
                        )
                else:
                    if len(cleanup_errors) == 1:
                        raise cleanup_errors[0][1]
                    else:
                        raise BaseExceptionGroup(
                            "Session cleanup failed",
                            [err for _, err in cleanup_errors],
                        )

    async def session_dependency(self) -> AsyncGenerator[AsyncSession, None]:
        """FastAPI dependency callable yielding a request-scoped AsyncSession.

        Usage:
            SessionDep = Annotated[AsyncSession, Depends(database.session_dependency)]

        Delegates to the session() context manager and yields exactly once.
        """
        async with self.session() as sess:
            yield sess

    @asynccontextmanager
    async def lifespan(self) -> AsyncGenerator[None, None]:
        """Composable async context manager for application startup and shutdown.

        Behavior:
        - If check_health_on_startup is True, executes ping() before yielding.
        - Yields control to the application lifespan.
        - Calls dispose() unconditionally on exit (including on startup error).
        - Preserves primary startup or application exceptions without masking.
        - Surfaces dispose failures normally when no primary exception exists.
        """
        primary_exc: BaseException | None = None
        try:
            if self._config.check_health_on_startup:
                await self.ping()
            yield
        except BaseException as exc:
            primary_exc = exc
            raise
        finally:
            try:
                await self.dispose()
            except BaseException as dispose_exc:
                if primary_exc is not None:
                    primary_exc.add_note(
                        f"Lifespan dispose failed ({type(dispose_exc).__name__})"
                    )
                else:
                    raise

    def __repr__(self) -> str:
        return f"PostgresDatabase(config={self._config!r})"
