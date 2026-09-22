"""Unit tests for PostgresDatabase lifecycle, session manager, and error handling."""

import traceback
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.pool import NullPool

from fastapi_infra.postgres import (
    PostgresConfig,
    PostgresDatabase,
    PostgresPoolConfig,
)


class CustomAppError(Exception):
    """Test exception simulating application errors."""


class CustomPingError(Exception):
    """Test exception simulating startup ping errors."""


@pytest.mark.unit
def test_postgres_database_initialization_defaults() -> None:
    config = PostgresConfig(
        dsn="postgresql://user:pass@localhost:5432/testdb",
        pool=PostgresPoolConfig(size=10, max_overflow=5),
    )
    db = PostgresDatabase(config)
    assert db.config == config
    assert db.engine is not None
    assert db.session_factory is not None
    assert "pass" not in repr(db)


@pytest.mark.unit
def test_postgres_database_nullpool_configuration() -> None:
    config = PostgresConfig(
        dsn="postgresql://user:pass@localhost:5432/testdb",
        pool=None,
    )
    db = PostgresDatabase(config)
    # Underlying pool should be NullPool
    assert isinstance(db.engine.pool, NullPool)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ping_executes_select_one() -> None:
    config = PostgresConfig(dsn="postgresql://user:pass@localhost:5432/testdb")
    db = PostgresDatabase(config)

    mock_conn = AsyncMock()
    mock_connect_cm = AsyncMock()
    mock_connect_cm.__aenter__.return_value = mock_conn
    mock_connect_cm.__aexit__.return_value = None

    with patch.object(AsyncEngine, "connect", return_value=mock_connect_cm):
        await db.ping()
        mock_conn.execute.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ping_propagates_connection_error() -> None:
    config = PostgresConfig(dsn="postgresql://user:pass@localhost:5432/testdb")
    db = PostgresDatabase(config)

    mock_connect_cm = AsyncMock()
    mock_connect_cm.__aenter__.side_effect = ConnectionRefusedError(
        "Connection refused"
    )

    with (
        patch.object(AsyncEngine, "connect", return_value=mock_connect_cm),
        pytest.raises(ConnectionRefusedError, match="Connection refused"),
    ):
        await db.ping()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_lifecycle_no_auto_commit() -> None:
    config = PostgresConfig(dsn="postgresql://user:pass@localhost:5432/testdb")
    db = PostgresDatabase(config)

    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.in_transaction.return_value = False

    with patch.object(db, "_session_factory", return_value=mock_session):
        async with db.session() as s:
            assert s is mock_session
            # Confirm no automatic commit was made by the context manager
            mock_session.commit.assert_not_called()

        # Session should be closed upon exit
        mock_session.close.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_rolls_back_uncommitted_work_on_clean_exit() -> None:
    config = PostgresConfig(dsn="postgresql://user:pass@localhost:5432/testdb")
    db = PostgresDatabase(config)

    mock_session = AsyncMock(spec=AsyncSession)
    # Simulate a transaction remaining active (uncommitted work left by application)
    mock_session.in_transaction.return_value = True

    with patch.object(db, "_session_factory", return_value=mock_session):
        async with db.session():
            pass

        mock_session.rollback.assert_awaited_once()
        mock_session.commit.assert_not_called()
        mock_session.close.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_rolls_back_and_reraises_on_exception() -> None:
    config = PostgresConfig(dsn="postgresql://user:pass@localhost:5432/testdb")
    db = PostgresDatabase(config)

    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.in_transaction.return_value = True

    with patch.object(db, "_session_factory", return_value=mock_session):
        with pytest.raises(RuntimeError, match="Something failed"):
            async with db.session():
                raise RuntimeError("Something failed")

        mock_session.rollback.assert_awaited()
        mock_session.close.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_body_exception_plus_rollback_failure() -> None:
    config = PostgresConfig(dsn="postgresql://user:pass@localhost:5432/testdb")
    db = PostgresDatabase(config)

    secret = "FAKE_DB_PASSWORD_9472"
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.in_transaction.return_value = True
    mock_session.rollback.side_effect = RuntimeError(f"rollback boom: {secret}")

    with patch.object(db, "_session_factory", return_value=mock_session):
        with pytest.raises(CustomAppError, match="app body failure") as exc_info:
            async with db.session():
                raise CustomAppError("app body failure")

        # Rollback and close were both attempted
        mock_session.rollback.assert_awaited_once()
        mock_session.close.assert_awaited_once()

        # Primary exception remains CustomAppError
        primary = exc_info.value
        assert isinstance(primary, CustomAppError)

        # Rollback note identifies phase and exception class name
        notes = getattr(primary, "__notes__", [])
        assert "Session rollback failed (RuntimeError)" in notes

        # Secret must not appear in notes, str, repr, or formatted traceback
        tb_str = "".join(traceback.format_exception(primary))
        assert secret not in "".join(notes)
        assert secret not in str(primary)
        assert secret not in repr(primary)
        assert secret not in tb_str


@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_body_exception_plus_close_failure() -> None:
    config = PostgresConfig(dsn="postgresql://user:pass@localhost:5432/testdb")
    db = PostgresDatabase(config)

    secret = "FAKE_DSN_TOKEN_3185"
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.in_transaction.return_value = False
    mock_session.close.side_effect = RuntimeError(f"close boom: {secret}")

    with patch.object(db, "_session_factory", return_value=mock_session):
        with pytest.raises(CustomAppError, match="app body failure") as exc_info:
            async with db.session():
                raise CustomAppError("app body failure")

        mock_session.close.assert_awaited_once()
        primary = exc_info.value
        assert isinstance(primary, CustomAppError)

        # Close note identifies phase and exception class name
        notes = getattr(primary, "__notes__", [])
        assert "Session close failed (RuntimeError)" in notes

        # Secret must not appear in notes, str, repr, or formatted traceback
        tb_str = "".join(traceback.format_exception(primary))
        assert secret not in "".join(notes)
        assert secret not in str(primary)
        assert secret not in repr(primary)
        assert secret not in tb_str


@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_rollback_failure_still_attempts_close() -> None:
    config = PostgresConfig(dsn="postgresql://user:pass@localhost:5432/testdb")
    db = PostgresDatabase(config)

    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.in_transaction.return_value = True
    mock_session.rollback.side_effect = RuntimeError("rollback failed")
    mock_session.close.side_effect = RuntimeError("close failed")

    with patch.object(db, "_session_factory", return_value=mock_session):
        with pytest.raises(CustomAppError) as exc_info:
            async with db.session():
                raise CustomAppError("app failed")

        # Close must still have been called despite rollback failure
        mock_session.rollback.assert_awaited_once()
        mock_session.close.assert_awaited_once()
        notes = getattr(exc_info.value, "__notes__", [])
        assert "Session rollback failed (RuntimeError)" in notes
        assert "Session close failed (RuntimeError)" in notes


@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_single_cleanup_failure_without_active_exception() -> None:
    config = PostgresConfig(dsn="postgresql://user:pass@localhost:5432/testdb")
    db = PostgresDatabase(config)

    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.in_transaction.return_value = True
    original_err = RuntimeError("rollback error on clean exit")
    mock_session.rollback.side_effect = original_err

    with patch.object(db, "_session_factory", return_value=mock_session):
        with pytest.raises(RuntimeError) as exc_info:
            async with db.session():
                pass

        assert exc_info.value is original_err
        mock_session.rollback.assert_awaited_once()
        mock_session.close.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_multiple_cleanup_failures_raise_exception_group() -> None:
    config = PostgresConfig(dsn="postgresql://user:pass@localhost:5432/testdb")
    db = PostgresDatabase(config)

    rollback_err = RuntimeError("rollback failure")
    close_err = ValueError("close failure")

    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.in_transaction.return_value = True
    mock_session.rollback.side_effect = rollback_err
    mock_session.close.side_effect = close_err

    with patch.object(db, "_session_factory", return_value=mock_session):
        with pytest.raises(BaseExceptionGroup) as exc_info:
            async with db.session():
                pass

        group = exc_info.value
        assert group.message == "Session cleanup failed"
        # Must contain both original cleanup exceptions in rollback-then-close order
        assert len(group.exceptions) == 2
        assert group.exceptions[0] is rollback_err
        assert group.exceptions[1] is close_err

        mock_session.rollback.assert_awaited_once()
        mock_session.close.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_dependency_delegates_to_session() -> None:
    config = PostgresConfig(dsn="postgresql://user:pass@localhost:5432/testdb")
    db = PostgresDatabase(config)

    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.in_transaction.return_value = False

    with patch.object(db, "_session_factory", return_value=mock_session):
        gen = db.session_dependency()
        yielded = await anext(gen)
        assert yielded is mock_session

        with pytest.raises(StopAsyncIteration):
            await anext(gen)

        mock_session.close.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lifespan_runs_ping_when_enabled_and_disposes() -> None:
    config = PostgresConfig(
        dsn="postgresql://user:pass@localhost:5432/testdb",
        check_health_on_startup=True,
    )
    db = PostgresDatabase(config)

    db.ping = AsyncMock()  # type: ignore[method-assign]
    db.dispose = AsyncMock()  # type: ignore[method-assign]

    async with db.lifespan():
        db.ping.assert_awaited_once()
        db.dispose.assert_not_called()

    db.dispose.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lifespan_skips_ping_when_disabled_and_disposes() -> None:
    config = PostgresConfig(
        dsn="postgresql://user:pass@localhost:5432/testdb",
        check_health_on_startup=False,
    )
    db = PostgresDatabase(config)

    db.ping = AsyncMock()  # type: ignore[method-assign]
    db.dispose = AsyncMock()  # type: ignore[method-assign]

    async with db.lifespan():
        db.ping.assert_not_called()

    db.dispose.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lifespan_application_exception_plus_dispose_failure() -> None:
    config = PostgresConfig(
        dsn="postgresql://user:pass@localhost:5432/testdb",
        check_health_on_startup=False,
    )
    db = PostgresDatabase(config)
    secret = "FAKE_DSN_TOKEN_3185"
    db.dispose = AsyncMock(  # type: ignore[method-assign]
        side_effect=RuntimeError(f"dispose failure: {secret}")
    )

    with pytest.raises(CustomAppError, match="app runtime error") as exc_info:
        async with db.lifespan():
            raise CustomAppError("app runtime error")

    db.dispose.assert_awaited_once()
    primary = exc_info.value
    assert isinstance(primary, CustomAppError)

    notes = getattr(primary, "__notes__", [])
    assert "Lifespan dispose failed (RuntimeError)" in notes

    # Secret must not appear in notes, str, repr, or formatted traceback
    tb_str = "".join(traceback.format_exception(primary))
    assert secret not in "".join(notes)
    assert secret not in str(primary)
    assert secret not in repr(primary)
    assert secret not in tb_str


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lifespan_startup_ping_exception_plus_dispose_failure() -> None:
    config = PostgresConfig(
        dsn="postgresql://user:pass@localhost:5432/testdb",
        check_health_on_startup=True,
    )
    db = PostgresDatabase(config)
    secret = "FAKE_DB_PASSWORD_9472"
    db.ping = AsyncMock(side_effect=CustomPingError("startup ping failure"))  # type: ignore[method-assign]
    db.dispose = AsyncMock(  # type: ignore[method-assign]
        side_effect=RuntimeError(f"dispose error during ping failure: {secret}")
    )

    with pytest.raises(CustomPingError, match="startup ping failure") as exc_info:
        async with db.lifespan():
            pass

    db.dispose.assert_awaited_once()
    primary = exc_info.value
    assert isinstance(primary, CustomPingError)

    notes = getattr(primary, "__notes__", [])
    assert "Lifespan dispose failed (RuntimeError)" in notes

    # Secret must not appear in notes, str, repr, or formatted traceback
    tb_str = "".join(traceback.format_exception(primary))
    assert secret not in "".join(notes)
    assert secret not in str(primary)
    assert secret not in repr(primary)
    assert secret not in tb_str


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lifespan_dispose_failure_surfaces_when_no_active_exception() -> None:
    config = PostgresConfig(
        dsn="postgresql://user:pass@localhost:5432/testdb",
        check_health_on_startup=False,
    )
    db = PostgresDatabase(config)
    original_err = RuntimeError("dispose failed on clean shutdown")
    db.dispose = AsyncMock(side_effect=original_err)  # type: ignore[method-assign]

    with pytest.raises(RuntimeError) as exc_info:
        async with db.lifespan():
            pass

    assert exc_info.value is original_err
    db.dispose.assert_awaited_once()


@pytest.mark.unit
def test_import_error_message_without_postgres_extra() -> None:
    # If psycopg or sqlalchemy is unimportable, an informative message is raised
    with (
        patch.dict("sys.modules", {"psycopg": None}),
        pytest.raises(ImportError, match="fastapi-infra\\[postgres\\]"),
    ):
        import importlib

        import fastapi_infra.postgres

        importlib.reload(fastapi_infra.postgres)
