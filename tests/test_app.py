"""Tests for the FastAPI web application."""

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sioncronaich.app import _cleanup_loop
from sioncronaich.db import cleanup_old_jobs, get_jobs

JOB_PAYLOAD = {
    "job_name": "test-job",
    "hostname": "test-host",
    "command": "echo hello",
    "stdout": "hello\n",
    "stderr": "",
    "exit_code": 0,
    "started_at": "2024-01-01T12:00:00+00:00",
    "finished_at": "2024-01-01T12:00:05+00:00",
}


class TestPostJob:
    def test_returns_201(self, client: TestClient):
        response = client.post("/jobs", json=JOB_PAYLOAD)
        assert response.status_code == 201

    def test_response_contains_id(self, client: TestClient):
        response = client.post("/jobs", json=JOB_PAYLOAD)
        assert "id" in response.json()

    def test_response_fields_match_payload(self, client: TestClient):
        response = client.post("/jobs", json=JOB_PAYLOAD)
        data = response.json()
        assert data["job_name"] == JOB_PAYLOAD["job_name"]
        assert data["hostname"] == JOB_PAYLOAD["hostname"]
        assert data["command"] == JOB_PAYLOAD["command"]
        assert data["exit_code"] == JOB_PAYLOAD["exit_code"]

    def test_response_contains_computed_fields(self, client: TestClient):
        response = client.post("/jobs", json=JOB_PAYLOAD)
        data = response.json()
        assert "duration_seconds" in data
        assert "succeeded" in data
        assert data["duration_seconds"] == 5.0
        assert data["succeeded"] is True

    def test_persists_to_database(self, client: TestClient, db_path: Path):
        client.post("/jobs", json=JOB_PAYLOAD)
        jobs = get_jobs(db_path=db_path)
        assert len(jobs) == 1

    def test_invalid_payload_returns_422(self, client: TestClient):
        response = client.post("/jobs", json={"job_name": "incomplete"})
        assert response.status_code == 422

    def test_failed_job(self, client: TestClient):
        payload = {**JOB_PAYLOAD, "exit_code": 1, "stderr": "error\n"}
        response = client.post("/jobs", json=payload)
        data = response.json()
        assert data["succeeded"] is False
        assert data["exit_code"] == 1


class TestJobOutput:
    def test_returns_stdout_and_stderr(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        response = client.get("/jobs/1/output")
        assert response.status_code == 200
        data = response.json()
        assert data["stdout"] == JOB_PAYLOAD["stdout"]
        assert data["stderr"] == JOB_PAYLOAD["stderr"]

    def test_returns_404_for_missing_job(self, client: TestClient):
        response = client.get("/jobs/999/output")
        assert response.status_code == 404


class TestListJobs:
    def test_empty_returns_empty_list(self, client: TestClient):
        response = client.get("/jobs")
        assert response.status_code == 200
        assert response.json() == []

    def test_returns_posted_jobs(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        response = client.get("/jobs")
        assert len(response.json()) == 1

    def test_newest_first_ordering(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        client.post("/jobs", json={**JOB_PAYLOAD, "job_name": "second-job"})
        results = client.get("/jobs").json()
        assert results[0]["job_name"] == "second-job"
        assert results[1]["job_name"] == "test-job"

    def test_limit_query_param(self, client: TestClient):
        for _ in range(5):
            client.post("/jobs", json=JOB_PAYLOAD)
        response = client.get("/jobs", params={"limit": 3})
        assert len(response.json()) == 3

    def test_offset_query_param(self, client: TestClient):
        for _ in range(5):
            client.post("/jobs", json=JOB_PAYLOAD)
        all_results = client.get("/jobs").json()
        offset_results = client.get("/jobs", params={"offset": 2}).json()
        assert offset_results[0]["id"] == all_results[2]["id"]


class TestListJobsFilters:
    def test_filter_by_job_name(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        client.post("/jobs", json={**JOB_PAYLOAD, "job_name": "other-job"})
        results = client.get("/jobs", params={"job_name": "other"}).json()
        assert len(results) == 1
        assert results[0]["job_name"] == "other-job"

    def test_filter_by_hostname(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        client.post("/jobs", json={**JOB_PAYLOAD, "hostname": "other-host"})
        results = client.get("/jobs", params={"hostname": "other"}).json()
        assert len(results) == 1
        assert results[0]["hostname"] == "other-host"

    def test_filter_by_status_ok(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        client.post("/jobs", json={**JOB_PAYLOAD, "exit_code": 1})
        results = client.get("/jobs", params={"status": "ok"}).json()
        assert all(r["succeeded"] for r in results)

    def test_filter_by_status_err(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        client.post("/jobs", json={**JOB_PAYLOAD, "exit_code": 1})
        results = client.get("/jobs", params={"status": "err"}).json()
        assert all(not r["succeeded"] for r in results)

    def test_filter_by_command(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        client.post("/jobs", json={**JOB_PAYLOAD, "command": "ls -la"})
        results = client.get("/jobs", params={"command": "ls"}).json()
        assert len(results) == 1
        assert results[0]["command"] == "ls -la"


class TestDashboard:
    def test_returns_200(self, client: TestClient):
        response = client.get("/")
        assert response.status_code == 200

    def test_returns_html(self, client: TestClient):
        response = client.get("/")
        assert "text/html" in response.headers["content-type"]

    def test_empty_state_message(self, client: TestClient):
        response = client.get("/")
        assert "No job results yet" in response.text

    def test_dashboard_filters_by_job_name(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        client.post("/jobs", json={**JOB_PAYLOAD, "job_name": "other-job"})
        response = client.get("/", params={"job_name": "other"})
        assert "other-job" in response.text
        assert "test-job" not in response.text

    def test_dashboard_output_not_in_page(self, client: TestClient):
        """Dashboard uses exclude_output=True — stdout/stderr not embedded in HTML."""
        client.post("/jobs", json=JOB_PAYLOAD)
        response = client.get("/")
        assert JOB_PAYLOAD["stdout"] not in response.text

    def test_renders_job_name(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        response = client.get("/")
        assert "test-job" in response.text

    def test_renders_hostname(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        response = client.get("/")
        assert "test-host" in response.text

    def test_ok_badge_for_success(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        response = client.get("/")
        assert "badge-ok" in response.text

    def test_err_badge_for_failure(self, client: TestClient):
        client.post("/jobs", json={**JOB_PAYLOAD, "exit_code": 1})
        response = client.get("/")
        assert "badge-err" in response.text


class TestJobOutputField:
    """Tests for GET /jobs/{job_id}/output/{field} (lines 128-133)."""

    def test_invalid_field_returns_400(self, client: TestClient):
        response = client.get("/jobs/1/output/invalid")
        assert response.status_code == 400

    def test_invalid_field_error_detail(self, client: TestClient):
        response = client.get("/jobs/1/output/invalid")
        assert response.json()["detail"] == "field must be stdout or stderr"

    def test_missing_job_returns_404(self, client: TestClient):
        response = client.get("/jobs/999/output/stdout")
        assert response.status_code == 404

    def test_returns_stdout_as_html_fragment(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        response = client.get("/jobs/1/output/stdout")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "hello" in response.text

    def test_returns_stderr_as_html_fragment(self, client: TestClient):
        client.post("/jobs", json={**JOB_PAYLOAD, "stderr": "an error\n"})
        response = client.get("/jobs/1/output/stderr")
        assert response.status_code == 200
        assert "an error" in response.text

    def test_html_escapes_output(self, client: TestClient):
        client.post("/jobs", json={**JOB_PAYLOAD, "stdout": "<script>alert('xss')</script>"})
        response = client.get("/jobs/1/output/stdout")
        assert "<script>" not in response.text
        assert "&lt;script&gt;" in response.text

    def test_empty_output_returns_placeholder(self, client: TestClient):
        client.post("/jobs", json={**JOB_PAYLOAD, "stdout": ""})
        response = client.get("/jobs/1/output/stdout")
        assert response.status_code == 200
        assert "(empty)" in response.text


class TestTablePartial:
    """Tests for GET /table (lines 152-162)."""

    def test_returns_200(self, client: TestClient):
        response = client.get("/table")
        assert response.status_code == 200

    def test_returns_html(self, client: TestClient):
        response = client.get("/table")
        assert "text/html" in response.headers["content-type"]

    def test_empty_state_message(self, client: TestClient):
        response = client.get("/table")
        assert "No job results yet" in response.text

    def test_renders_job_name(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        response = client.get("/table")
        assert "test-job" in response.text

    def test_output_not_embedded_in_partial(self, client: TestClient):
        """table_partial uses exclude_output=True — stdout/stderr not in HTML."""
        client.post("/jobs", json=JOB_PAYLOAD)
        response = client.get("/table")
        assert JOB_PAYLOAD["stdout"] not in response.text

    def test_filter_by_job_name(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        client.post("/jobs", json={**JOB_PAYLOAD, "job_name": "other-job"})
        response = client.get("/table", params={"job_name": "other"})
        assert "other-job" in response.text
        assert "test-job" not in response.text

    def test_filter_by_hostname(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        client.post("/jobs", json={**JOB_PAYLOAD, "hostname": "other-host"})
        response = client.get("/table", params={"hostname": "other"})
        assert "other-host" in response.text
        assert "test-host" not in response.text

    def test_filter_by_status_ok(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        client.post("/jobs", json={**JOB_PAYLOAD, "exit_code": 1})
        response = client.get("/table", params={"status": "ok"})
        assert "badge-ok" in response.text
        assert "badge-err" not in response.text

    def test_filter_by_status_err(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        client.post("/jobs", json={**JOB_PAYLOAD, "exit_code": 1})
        response = client.get("/table", params={"status": "err"})
        assert "badge-err" in response.text
        assert "badge-ok" not in response.text

    def test_filter_by_command(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        client.post("/jobs", json={**JOB_PAYLOAD, "command": "ls -la"})
        response = client.get("/table", params={"command": "ls"})
        assert "ls -la" in response.text
        assert "echo hello" not in response.text

    def test_pagination_limit_and_offset(self, client: TestClient):
        for _ in range(3):
            client.post("/jobs", json=JOB_PAYLOAD)
        response = client.get("/table", params={"limit": 2, "offset": 2})
        assert response.status_code == 200


class TestCleanupLoop:
    """Tests for _cleanup_loop background task (lines 42-43, 48-52)."""

    async def test_startup_cleanup_exception_is_swallowed(
        self, db_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Lines 42-43: RuntimeError during startup cleanup is caught and logged."""
        monkeypatch.setenv("SIONCRONAICH_DB", str(db_path))

        def boom(*_args: object, **_kwargs: object) -> int:
            raise RuntimeError("db exploded")

        monkeypatch.setattr("sioncronaich.app.cleanup_old_jobs", boom)

        async def instant_cancel(_seconds: float) -> None:
            raise asyncio.CancelledError

        monkeypatch.setattr("sioncronaich.app.asyncio.sleep", instant_cancel)

        # CancelledError escapes from asyncio.sleep — startup exception was swallowed
        with pytest.raises(asyncio.CancelledError):
            await _cleanup_loop()

    async def test_loop_body_runs_cleanup_after_sleep(
        self, db_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Lines 49-50: cleanup_old_jobs is called after asyncio.sleep returns."""
        monkeypatch.setenv("SIONCRONAICH_DB", str(db_path))

        sleep_calls = 0

        async def sleep_once_then_cancel(_seconds: float) -> None:
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls > 1:
                raise asyncio.CancelledError

        monkeypatch.setattr("sioncronaich.app.asyncio.sleep", sleep_once_then_cancel)

        call_log: list[int] = []
        original = cleanup_old_jobs

        def tracking_cleanup(*args: object, **kwargs: object) -> int:
            result = original(*args, **kwargs)  # type: ignore[arg-type]
            call_log.append(result)
            return result

        monkeypatch.setattr("sioncronaich.app.cleanup_old_jobs", tracking_cleanup)

        with pytest.raises(asyncio.CancelledError):
            await _cleanup_loop()

        # 1 startup call + 1 loop-body call before the second sleep cancels
        assert len(call_log) == 2

    async def test_loop_body_exception_is_swallowed(
        self, db_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Lines 51-52: exception inside the while-loop try is caught and logged."""
        monkeypatch.setenv("SIONCRONAICH_DB", str(db_path))

        sleep_calls = 0

        async def sleep_once_then_cancel(_seconds: float) -> None:
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls > 1:
                raise asyncio.CancelledError

        monkeypatch.setattr("sioncronaich.app.asyncio.sleep", sleep_once_then_cancel)

        cleanup_calls = 0

        def boom_on_second(*_args: object, **_kwargs: object) -> int:
            nonlocal cleanup_calls
            cleanup_calls += 1
            if cleanup_calls > 1:
                raise RuntimeError("nightly cleanup failed")
            return 0

        monkeypatch.setattr("sioncronaich.app.cleanup_old_jobs", boom_on_second)

        # loop-body exception is swallowed; CancelledError comes from 2nd sleep
        with pytest.raises(asyncio.CancelledError):
            await _cleanup_loop()
