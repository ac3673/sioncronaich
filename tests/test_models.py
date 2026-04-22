"""Tests for Pydantic models."""

from datetime import UTC, datetime

import pytest

from sioncronaich.models import JobResult, JobResultCreate


def make_job(**kwargs) -> JobResultCreate:
    defaults = {
        "job_name": "test-job",
        "hostname": "test-host",
        "command": "echo hello",
        "stdout": "hello\n",
        "stderr": "",
        "exit_code": 0,
        "started_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        "finished_at": datetime(2024, 1, 1, 12, 0, 5, tzinfo=UTC),
    }
    return JobResultCreate(**{**defaults, **kwargs})


class TestJobResultCreate:
    def test_duration_seconds(self):
        job = make_job(
            started_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            finished_at=datetime(2024, 1, 1, 12, 0, 5, tzinfo=UTC),
        )
        assert job.duration_seconds == 5.0

    def test_duration_fractional(self):
        job = make_job(
            started_at=datetime(2024, 1, 1, 12, 0, 0, 0, tzinfo=UTC),
            finished_at=datetime(2024, 1, 1, 12, 0, 0, 500_000, tzinfo=UTC),
        )
        assert job.duration_seconds == pytest.approx(0.5)

    def test_fields_preserved(self):
        job = make_job()
        assert job.job_name == "test-job"
        assert job.hostname == "test-host"
        assert job.command == "echo hello"
        assert job.stdout == "hello\n"
        assert job.stderr == ""
        assert job.exit_code == 0


class TestJobResult:
    def test_succeeded_when_exit_code_zero(self):
        job = JobResult(id=1, **make_job(exit_code=0).model_dump())
        assert job.succeeded is True

    def test_failed_when_exit_code_nonzero(self):
        job = JobResult(id=1, **make_job(exit_code=1).model_dump())
        assert job.succeeded is False

    def test_failed_when_exit_code_negative(self):
        job = JobResult(id=1, **make_job(exit_code=-1).model_dump())
        assert job.succeeded is False

    def test_id_present(self):
        job = JobResult(id=42, **make_job().model_dump())
        assert job.id == 42
