"""Tests for the SQLite persistence layer."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sioncronaich.db import _connect, get_jobs, init_db, insert_job
from sioncronaich.models import JobResultCreate


class TestInitDb:
    def test_uses_default_path_when_none_given(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """Calling init_db() with no argument must not raise and must return a Path."""
        # Redirect home so we don't pollute the real user directory during tests.
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows
        result = init_db()
        assert isinstance(result, Path)
        assert result.exists()

    def test_creates_database_file(self, tmp_path: Path):
        path = tmp_path / "jobs.db"
        assert not path.exists()
        init_db(path)
        assert path.exists()

    def test_returns_resolved_path(self, tmp_path: Path):
        path = tmp_path / "jobs.db"
        result = init_db(path)
        assert result == path

    def test_idempotent(self, tmp_path: Path):
        path = tmp_path / "jobs.db"
        init_db(path)
        init_db(path)  # should not raise


class TestInsertJob:
    def test_returns_job_result_with_id(self, db_path: Path, sample_job: JobResultCreate):
        result = insert_job(sample_job, db_path=db_path)
        assert result.id == 1

    def test_id_increments(
        self, db_path: Path, sample_job: JobResultCreate, failed_job: JobResultCreate
    ):
        first = insert_job(sample_job, db_path=db_path)
        second = insert_job(failed_job, db_path=db_path)
        assert second.id == first.id + 1

    def test_fields_round_trip(self, db_path: Path, sample_job: JobResultCreate):
        result = insert_job(sample_job, db_path=db_path)
        assert result.job_name == sample_job.job_name
        assert result.hostname == sample_job.hostname
        assert result.command == sample_job.command
        assert result.stdout == sample_job.stdout
        assert result.stderr == sample_job.stderr
        assert result.exit_code == sample_job.exit_code

    def test_timestamps_round_trip(self, db_path: Path, sample_job: JobResultCreate):
        result = insert_job(sample_job, db_path=db_path)
        assert result.started_at == sample_job.started_at
        assert result.finished_at == sample_job.finished_at

    def test_timestamps_are_timezone_aware(self, db_path: Path, sample_job: JobResultCreate):
        result = insert_job(sample_job, db_path=db_path)
        assert result.started_at.tzinfo is not None
        assert result.finished_at.tzinfo is not None


class TestGetJobs:
    def test_naive_datetime_in_db_gets_utc_applied(
        self, db_path: Path, sample_job: JobResultCreate
    ):
        """Rows written without a timezone offset are treated as UTC on read-back."""
        insert_job(sample_job, db_path=db_path)
        # Overwrite started_at with a naive ISO string to simulate legacy data.
        with _connect(db_path) as conn:
            conn.execute(
                "UPDATE job_results SET started_at = '2024-01-01T12:00:00' WHERE id = 1"
            )
        result = get_jobs(db_path=db_path)[0]
        assert result.started_at.tzinfo is not None
        assert result.started_at.utcoffset().total_seconds() == 0  # type: ignore[union-attr]

    def test_empty_database_returns_empty_list(self, db_path: Path):
        assert get_jobs(db_path=db_path) == []

    def test_returns_inserted_job(self, db_path: Path, sample_job: JobResultCreate):
        insert_job(sample_job, db_path=db_path)
        results = get_jobs(db_path=db_path)
        assert len(results) == 1
        assert results[0].job_name == sample_job.job_name

    def test_newest_first_ordering(
        self, db_path: Path, sample_job: JobResultCreate, failed_job: JobResultCreate
    ):
        insert_job(sample_job, db_path=db_path)
        insert_job(failed_job, db_path=db_path)
        results = get_jobs(db_path=db_path)
        assert results[0].job_name == failed_job.job_name
        assert results[1].job_name == sample_job.job_name

    def test_limit(self, db_path: Path, sample_job: JobResultCreate):
        for _ in range(5):
            insert_job(sample_job, db_path=db_path)
        results = get_jobs(limit=3, db_path=db_path)
        assert len(results) == 3

    def test_offset(self, db_path: Path, sample_job: JobResultCreate):
        for _ in range(5):
            insert_job(sample_job, db_path=db_path)
        all_results = get_jobs(db_path=db_path)
        offset_results = get_jobs(offset=2, db_path=db_path)
        assert offset_results[0].id == all_results[2].id

    def test_limit_and_offset(self, db_path: Path, sample_job: JobResultCreate):
        for _ in range(10):
            insert_job(sample_job, db_path=db_path)
        results = get_jobs(limit=3, offset=3, db_path=db_path)
        assert len(results) == 3
