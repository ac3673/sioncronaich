"""Tests for the FastAPI web application."""

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sioncronaich.app import _cleanup_loop, _missing_jobs_loop
from sioncronaich.config import Settings
from sioncronaich.db import cleanup_old_jobs, get_all_job_names, get_jobs

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

FAILED_PAYLOAD = {
    **JOB_PAYLOAD,
    "job_name": "failing-job",
    "stdout": "",
    "stderr": "error: something went wrong\n",
    "exit_code": 1,
}


class TestPostJob:
    def test_returns_201(self, client: TestClient):
        response = client.post("/jobs", json=JOB_PAYLOAD)
        assert response.status_code == 201

    def test_response_contains_id(self, client: TestClient):
        assert "id" in client.post("/jobs", json=JOB_PAYLOAD).json()

    def test_response_fields_match_payload(self, client: TestClient):
        data = client.post("/jobs", json=JOB_PAYLOAD).json()
        assert data["job_name"] == JOB_PAYLOAD["job_name"]
        assert data["hostname"] == JOB_PAYLOAD["hostname"]
        assert data["command"] == JOB_PAYLOAD["command"]
        assert data["exit_code"] == JOB_PAYLOAD["exit_code"]

    def test_response_contains_computed_fields(self, client: TestClient):
        data = client.post("/jobs", json=JOB_PAYLOAD).json()
        assert data["duration_seconds"] == 5.0
        assert data["succeeded"] is True

    def test_persists_to_database(self, client: TestClient, db_path: Path):
        client.post("/jobs", json=JOB_PAYLOAD)
        assert len(get_jobs(db_path=db_path)) == 1

    def test_invalid_payload_returns_422(self, client: TestClient):
        assert client.post("/jobs", json={"job_name": "incomplete"}).status_code == 422

    def test_failed_job_response(self, client: TestClient):
        data = client.post("/jobs", json=FAILED_PAYLOAD).json()
        assert data["succeeded"] is False
        assert data["exit_code"] == 1


class TestPostJobFailuresOnly:
    """POST /jobs behaviour when ``failures_only`` is enabled."""

    def test_successful_job_returns_204(self, client: TestClient):
        client.app.state.settings.failures_only = True
        assert client.post("/jobs", json=JOB_PAYLOAD).status_code == 204

    def test_successful_job_not_persisted(self, client: TestClient, db_path: Path):
        client.app.state.settings.failures_only = True
        client.post("/jobs", json=JOB_PAYLOAD)
        assert get_jobs(db_path=db_path) == []

    def test_successful_job_still_recorded_in_job_runs(self, client: TestClient, db_path: Path):
        client.app.state.settings.failures_only = True
        client.post("/jobs", json=JOB_PAYLOAD)
        assert JOB_PAYLOAD["job_name"] in get_all_job_names(db_path=db_path)

    def test_failed_job_still_returns_201(self, client: TestClient):
        client.app.state.settings.failures_only = True
        assert client.post("/jobs", json=FAILED_PAYLOAD).status_code == 201

    def test_failed_job_still_persisted(self, client: TestClient, db_path: Path):
        client.app.state.settings.failures_only = True
        client.post("/jobs", json=FAILED_PAYLOAD)
        assert len(get_jobs(db_path=db_path)) == 1

    def test_disabled_by_default(self, client: TestClient, db_path: Path):
        client.post("/jobs", json=JOB_PAYLOAD)
        assert len(get_jobs(db_path=db_path)) == 1


class TestJobOutput:
    def test_returns_stdout_and_stderr(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        data = client.get("/jobs/1/output").json()
        assert data["stdout"] == JOB_PAYLOAD["stdout"]
        assert data["stderr"] == JOB_PAYLOAD["stderr"]

    def test_returns_404_for_missing_job(self, client: TestClient):
        assert client.get("/jobs/999/output").status_code == 404


class TestListJobs:
    def test_empty_returns_empty_list(self, client: TestClient):
        assert client.get("/jobs").json() == []

    def test_returns_posted_jobs(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        assert len(client.get("/jobs").json()) == 1

    def test_newest_first_ordering(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        client.post("/jobs", json={**JOB_PAYLOAD, "job_name": "second-job"})
        results = client.get("/jobs").json()
        assert results[0]["job_name"] == "second-job"
        assert results[1]["job_name"] == "test-job"

    def test_limit_query_param(self, client: TestClient):
        for _ in range(5):
            client.post("/jobs", json=JOB_PAYLOAD)
        assert len(client.get("/jobs", params={"limit": 3}).json()) == 3

    def test_offset_query_param(self, client: TestClient):
        for _ in range(5):
            client.post("/jobs", json=JOB_PAYLOAD)
        all_results = client.get("/jobs").json()
        offset_results = client.get("/jobs", params={"offset": 2}).json()
        assert offset_results[0]["id"] == all_results[2]["id"]

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
        client.post("/jobs", json=FAILED_PAYLOAD)
        results = client.get("/jobs", params={"status": "ok"}).json()
        assert all(r["succeeded"] for r in results)

    def test_filter_by_status_err(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        client.post("/jobs", json=FAILED_PAYLOAD)
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
        assert client.get("/").status_code == 200

    def test_returns_html(self, client: TestClient):
        assert "text/html" in client.get("/").headers["content-type"]

    def test_empty_state_message(self, client: TestClient):
        assert "No job results yet" in client.get("/").text

    def test_renders_job_name(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        assert "test-job" in client.get("/").text

    def test_renders_hostname(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        assert "test-host" in client.get("/").text

    def test_ok_badge_for_success(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        assert "badge-ok" in client.get("/").text

    def test_err_badge_for_failure(self, client: TestClient):
        client.post("/jobs", json=FAILED_PAYLOAD)
        assert "badge-err" in client.get("/").text

    def test_output_not_embedded_in_page(self, client: TestClient):
        """Dashboard uses exclude_output=True — stdout content not in HTML."""
        client.post("/jobs", json=JOB_PAYLOAD)
        assert JOB_PAYLOAD["stdout"] not in client.get("/").text

    def test_show_stdout_link_present_when_has_stdout(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        assert "show stdout" in client.get("/").text

    def test_show_stderr_link_present_when_has_stderr(self, client: TestClient):
        client.post("/jobs", json=FAILED_PAYLOAD)
        assert "show stderr" in client.get("/").text

    def test_no_show_stdout_link_when_stdout_empty(self, client: TestClient):
        client.post("/jobs", json=FAILED_PAYLOAD)
        assert "show stdout" not in client.get("/").text

    def test_filter_by_job_name(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        client.post("/jobs", json={**JOB_PAYLOAD, "job_name": "other-job"})
        response = client.get("/", params={"job_name": "other"})
        assert "other-job" in response.text
        assert "test-job" not in response.text


class TestJobOutputField:
    def test_invalid_field_returns_400(self, client: TestClient):
        assert client.get("/jobs/1/output/invalid").status_code == 400

    def test_invalid_field_error_detail(self, client: TestClient):
        assert (
            client.get("/jobs/1/output/invalid").json()["detail"]
            == "field must be stdout or stderr"
        )

    def test_missing_job_returns_404(self, client: TestClient):
        assert client.get("/jobs/999/output/stdout").status_code == 404

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
    def test_returns_200(self, client: TestClient):
        assert client.get("/table").status_code == 200

    def test_returns_html(self, client: TestClient):
        assert "text/html" in client.get("/table").headers["content-type"]

    def test_empty_state_message(self, client: TestClient):
        assert "No job results yet" in client.get("/table").text

    def test_renders_job_name(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        assert "test-job" in client.get("/table").text

    def test_output_not_embedded_in_partial(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        assert JOB_PAYLOAD["stdout"] not in client.get("/table").text

    def test_show_stdout_link_present_when_has_stdout(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        assert "show stdout" in client.get("/table").text

    def test_show_stderr_link_present_when_has_stderr(self, client: TestClient):
        client.post("/jobs", json=FAILED_PAYLOAD)
        assert "show stderr" in client.get("/table").text

    def test_no_show_stdout_link_when_stdout_empty(self, client: TestClient):
        client.post("/jobs", json=FAILED_PAYLOAD)
        assert "show stdout" not in client.get("/table").text

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
        client.post("/jobs", json=FAILED_PAYLOAD)
        response = client.get("/table", params={"status": "ok"})
        assert "badge-ok" in response.text
        assert "badge-err" not in response.text

    def test_filter_by_status_err(self, client: TestClient):
        client.post("/jobs", json=JOB_PAYLOAD)
        client.post("/jobs", json=FAILED_PAYLOAD)
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
        assert client.get("/table", params={"limit": 2, "offset": 2}).status_code == 200


class TestCleanupLoop:
    async def test_startup_cleanup_exception_is_swallowed(
        self, db_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = Settings(db=db_path)

        def boom(*_args: object, **_kwargs: object) -> int:
            raise RuntimeError("db exploded")

        monkeypatch.setattr("sioncronaich.app.cleanup_old_jobs", boom)

        async def instant_cancel(_seconds: float) -> None:
            raise asyncio.CancelledError

        monkeypatch.setattr("sioncronaich.app.asyncio.sleep", instant_cancel)

        with pytest.raises(asyncio.CancelledError):
            await _cleanup_loop(settings)

    async def test_loop_body_runs_cleanup_after_sleep(
        self, db_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = Settings(db=db_path)

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
            await _cleanup_loop(settings)

        assert len(call_log) == 2

    async def test_loop_body_exception_is_swallowed(
        self, db_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = Settings(db=db_path)

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

        with pytest.raises(asyncio.CancelledError):
            await _cleanup_loop(settings)


class TestMissingJobsLoop:
    async def test_loop_cancels_cleanly(
        self, db_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = Settings(db=db_path)

        # The loop starts with a 1h startup sleep; cancelling on that is enough.
        async def instant_cancel(_seconds: float) -> None:
            raise asyncio.CancelledError

        monkeypatch.setattr("sioncronaich.app.asyncio.sleep", instant_cancel)
        with pytest.raises(asyncio.CancelledError):
            await _missing_jobs_loop(settings)

    async def test_skips_jobs_below_min_runs(
        self, db_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from datetime import UTC, datetime

        from sioncronaich.db import record_run
        from sioncronaich.models import JobResultCreate

        settings = Settings(db=db_path, missing_job_min_runs=3)

        call_count = 0

        async def sleep_then_cancel(_seconds: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:  # cancel on the end-of-loop sleep, not the startup delay
                raise asyncio.CancelledError

        monkeypatch.setattr("sioncronaich.app.asyncio.sleep", sleep_then_cancel)

        job = JobResultCreate(
            job_name="sparse-job",
            hostname="h",
            command="x",
            stdout="",
            stderr="",
            exit_code=0,
            started_at=datetime(2024, 1, 1, tzinfo=UTC),
            finished_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        record_run(job, db_path=db_path)
        record_run(job, db_path=db_path)

        alerted: list = []
        monkeypatch.setattr(
            "sioncronaich.app.send_missing_job_alert", lambda *a: alerted.append(a)
        )

        with pytest.raises(asyncio.CancelledError):
            await _missing_jobs_loop(settings)

        assert alerted == []

    async def test_exclusion_list_skips_job(
        self, db_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from datetime import UTC, datetime

        from sioncronaich.db import record_run
        from sioncronaich.models import JobResultCreate

        settings = Settings(db=db_path, missing_job_min_runs=2, missing_job_exclude=["skip-me"])

        call_count = 0

        async def sleep_then_cancel(_seconds: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError

        monkeypatch.setattr("sioncronaich.app.asyncio.sleep", sleep_then_cancel)

        job = JobResultCreate(
            job_name="skip-me",
            hostname="h",
            command="x",
            stdout="",
            stderr="",
            exit_code=0,
            started_at=datetime(2024, 1, 1, tzinfo=UTC),
            finished_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        for _ in range(3):
            record_run(job, db_path=db_path)

        alerted: list = []
        monkeypatch.setattr(
            "sioncronaich.app.send_missing_job_alert", lambda *a: alerted.append(a)
        )

        with pytest.raises(asyncio.CancelledError):
            await _missing_jobs_loop(settings)

        assert alerted == []

    async def test_alerts_when_job_overdue(
        self, db_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from datetime import UTC, datetime, timedelta

        from sioncronaich.db import record_run
        from sioncronaich.models import JobResultCreate

        settings = Settings(db=db_path, missing_job_min_runs=2, missing_job_multiplier=1.5)

        call_count = 0

        async def sleep_then_cancel(_seconds: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError

        monkeypatch.setattr("sioncronaich.app.asyncio.sleep", sleep_then_cancel)

        # 3 runs 24h apart; most recent is now-50h -> overdue at 1.5x24h=36h threshold
        base = datetime.now(UTC) - timedelta(hours=98)
        for i in range(3):
            ts = base + timedelta(hours=24 * i)
            job = JobResultCreate(
                job_name="daily-job",
                hostname="h",
                command="x",
                stdout="",
                stderr="",
                exit_code=0,
                started_at=ts,
                finished_at=ts,
            )
            record_run(job, db_path=db_path)

        alerted: list = []
        monkeypatch.setattr(
            "sioncronaich.app.send_missing_job_alert", lambda *a: alerted.append(a)
        )

        with pytest.raises(asyncio.CancelledError):
            await _missing_jobs_loop(settings)

        assert len(alerted) == 1
        assert alerted[0][0] == "daily-job"
