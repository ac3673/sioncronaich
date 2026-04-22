"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sioncronaich.app import create_app
from sioncronaich.db import init_db
from sioncronaich.models import JobResultCreate


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Initialised temporary SQLite database."""
    path = tmp_path / "test.db"
    init_db(path)
    return path


@pytest.fixture
def sample_job() -> JobResultCreate:
    """A minimal valid JobResultCreate instance."""
    started = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    finished = datetime(2024, 1, 1, 12, 0, 5, tzinfo=UTC)
    return JobResultCreate(
        job_name="test-job",
        hostname="test-host",
        command="echo hello",
        stdout="hello\n",
        stderr="",
        exit_code=0,
        started_at=started,
        finished_at=finished,
    )


@pytest.fixture
def failed_job() -> JobResultCreate:
    """A JobResultCreate instance representing a failed job."""
    started = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    finished = datetime(2024, 1, 1, 12, 0, 2, tzinfo=UTC)
    return JobResultCreate(
        job_name="failing-job",
        hostname="test-host",
        command="exit 1",
        stdout="",
        stderr="error: something went wrong\n",
        exit_code=1,
        started_at=started,
        finished_at=finished,
    )


@pytest.fixture
def client(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    """TestClient wired to a temporary database.

    Using the context-manager form ensures the FastAPI lifespan
    (configure_logging + init_db) is exercised on every test that
    uses this fixture.
    """
    monkeypatch.setenv("SIONCRONAICH_DB", str(db_path))
    with TestClient(create_app()) as test_client:
        yield test_client
