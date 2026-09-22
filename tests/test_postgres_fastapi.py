from contextlib import asynccontextmanager
from typing import Annotated
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_infra.postgres import PostgresConfig, PostgresDatabase


@pytest.mark.unit
def test_fastapi_lifespan_and_session_dependency() -> None:
    config = PostgresConfig(
        dsn="postgresql://user:pass@localhost:5432/testdb",
        check_health_on_startup=True,
    )
    database = PostgresDatabase(config)

    # Mock ping and dispose for the unit test
    database.ping = AsyncMock()  # type: ignore[method-assign]
    database.dispose = AsyncMock()  # type: ignore[method-assign]

    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.in_transaction.return_value = False

    @asynccontextmanager
    async def app_lifespan(app: FastAPI):
        async with database.lifespan():
            yield

    app = FastAPI(lifespan=app_lifespan)

    @app.get("/items")
    def list_items(
        session: Annotated[AsyncSession, Depends(database.session_dependency)],
    ) -> dict[str, str]:
        assert session is mock_session
        return {"status": "ok"}

    with patch.object(database, "_session_factory", return_value=mock_session):
        with TestClient(app) as client:
            database.ping.assert_awaited_once()

            response = client.get(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
                "/items"
            )
            assert response.status_code == 200  # pyright: ignore[reportUnknownMemberType]
            assert response.json() == {"status": "ok"}  # pyright: ignore[reportUnknownMemberType]

            mock_session.close.assert_awaited_once()

        # After client exit (application shutdown)
        database.dispose.assert_awaited_once()
