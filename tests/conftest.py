from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    # _env_file=None: tests must not depend on a developer's local .env.
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        environment="test",
        app_name="Kanoon AI Test",
        sessions_dir=tmp_path / "sessions",
        frontend_dist=None,  # a local `npm run build` must not change API tests
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
