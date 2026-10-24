from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.helpers import FakeFetcher, attach_fake

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        books_dir=tmp_path / "books",
        frontend_dir=tmp_path / "no-frontend",
        log_level="WARNING",
        download_concurrency=2,
        download_max_width=1000,
        download_retries=2,
        download_retry_backoff=0.01,
        http_timeout=3,
        http_connect_timeout=2,
        preview_ttl_seconds=300,
        page_thumbnails_enabled=False,
    )


@pytest.fixture
def fake_fetcher() -> FakeFetcher:
    return FakeFetcher(
        manifests={
            "https://example.org/iiif/book2/manifest": load_fixture("manifest_v3.json"),
            "https://example.org/iiif/book1/manifest": load_fixture("manifest_v2.json"),
            "https://example.org/slow/manifest": load_fixture("manifest_v3.json"),
        }
    )


@pytest.fixture
def client(settings: Settings, fake_fetcher: FakeFetcher):
    app = create_app(settings)
    with TestClient(app) as test_client:
        attach_fake(app, fake_fetcher)
        yield test_client


def wait_until(predicate, *, timeout: float = 15.0, interval: float = 0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("Timed out waiting for condition")
