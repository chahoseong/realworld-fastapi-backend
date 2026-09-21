from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING

import pytest
from alembic import command
from alembic.config import Config
from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.database import get_session
from app.main import app

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


class TestSettings(BaseSettings):
    test_database_url: PostgresDsn

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@pytest.fixture(scope="session")
def test_database_url() -> str:
    database_url = str(TestSettings().test_database_url)
    if make_url(database_url).database != "realworld_test":
        raise pytest.UsageError(
            "TEST_DATABASE_URL must target the realworld_test database."
        )
    return database_url


@pytest.fixture(scope="session")
def migrate_test_database(test_database_url: str) -> None:
    alembic_config = Config("alembic.ini")
    alembic_config.attributes["database_url"] = test_database_url
    command.upgrade(alembic_config, "head")


@pytest.fixture(scope="session")
def test_engine(
    test_database_url: str,
    migrate_test_database: None,
) -> Generator[Engine]:
    engine = create_engine(test_database_url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def test_session_factory(
    test_engine: Engine,
) -> sessionmaker[Session]:
    return sessionmaker(bind=test_engine, expire_on_commit=False)


@pytest.fixture
def client(
    test_session_factory: sessionmaker[Session],
) -> Generator[TestClient]:
    from fastapi.testclient import TestClient

    def override_get_session() -> Generator[Session]:
        with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
