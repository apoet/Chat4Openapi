from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.orm import Session, sessionmaker

from chatapi.db.base import Base
from chatapi.db.session import create_engine_for_url, get_db_session
from chatapi.main import create_app
from chatapi import models  # noqa: F401


@pytest.fixture
def db_session_factory(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    database_url = f"sqlite:///{(tmp_path / 'app.db').as_posix()}"
    engine = create_engine_for_url(database_url)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


@pytest_asyncio.fixture
async def client(db_session_factory: sessionmaker[Session]) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()

    def override_session() -> Iterator[Session]:
        session = db_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
