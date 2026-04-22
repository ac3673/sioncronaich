"""Tests for the sioncronaich CLI script."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from sioncronaich.script import _post_result, _run_command, main
from sioncronaich.models import JobResultCreate


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def sample_payload() -> JobResultCreate:
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


class TestRunCommand:
    def test_captures_stdout(self):
        stdout, _, _, _, _ = _run_command((sys.executable, "-c", "print('hello')"))
        assert stdout.strip() == "hello"

    def test_captures_stderr(self):
        _, stderr, _, _, _ = _run_command(
            (sys.executable, "-c", "import sys; sys.stderr.write('err\\n')")
        )
        assert stderr.strip() == "err"

    def test_captures_exit_code_zero(self):
        _, _, exit_code, _, _ = _run_command((sys.executable, "-c", "pass"))
        assert exit_code == 0

    def test_captures_exit_code_nonzero(self):
        _, _, exit_code, _, _ = _run_command((sys.executable, "-c", "raise SystemExit(2)"))
        assert exit_code == 2

    def test_started_before_finished(self):
        _, _, _, started_at, finished_at = _run_command((sys.executable, "-c", "pass"))
        assert started_at <= finished_at

    def test_timestamps_are_timezone_aware(self):
        _, _, _, started_at, finished_at = _run_command((sys.executable, "-c", "pass"))
        assert started_at.tzinfo is not None
        assert finished_at.tzinfo is not None


class TestPostResult:
    def test_posts_to_endpoint(self, sample_payload: JobResultCreate):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        with patch(
            "sioncronaich.script.requests.post", return_value=mock_response
        ) as mock_post:
            _post_result("http://localhost:8716/jobs", sample_payload, timeout=5)
            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args
            assert call_kwargs.args[0] == "http://localhost:8716/jobs"

    def test_sends_json_content_type(self, sample_payload: JobResultCreate):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        with patch(
            "sioncronaich.script.requests.post", return_value=mock_response
        ) as mock_post:
            _post_result("http://localhost:8716/jobs", sample_payload, timeout=5)
            headers = mock_post.call_args.kwargs["headers"]
            assert headers["Content-Type"] == "application/json"

    def test_does_not_raise_on_connection_error(self, sample_payload: JobResultCreate):
        import requests as req

        with patch(
            "sioncronaich.script.requests.post",
            side_effect=req.ConnectionError("connection refused"),
        ):
            # Should not raise
            _post_result("http://localhost:8716/jobs", sample_payload, timeout=5)

    def test_prints_error_on_failure(
        self, sample_payload: JobResultCreate, capsys: pytest.CaptureFixture
    ):
        import requests as req

        with patch(
            "sioncronaich.script.requests.post",
            side_effect=req.ConnectionError("refused"),
        ):
            _post_result("http://localhost:8716/jobs", sample_payload, timeout=5)
        captured = capsys.readouterr()
        assert "sioncronaich" in captured.err


class TestMain:
    def test_exits_with_zero_on_success(self, runner: CliRunner):
        with patch("sioncronaich.script._post_result"):
            result = runner.invoke(
                main,
                ["--name", "test", "--", sys.executable, "-c", "pass"],
            )
        assert result.exit_code == 0

    def test_exits_with_command_exit_code(self, runner: CliRunner):
        with patch("sioncronaich.script._post_result"):
            result = runner.invoke(
                main,
                ["--name", "test", "--", sys.executable, "-c", "raise SystemExit(3)"],
            )
        assert result.exit_code == 3

    def test_requires_name_option(self, runner: CliRunner):
        result = runner.invoke(main, ["--", sys.executable, "-c", "pass"])
        assert result.exit_code != 0
        assert "--name" in result.output

    def test_requires_command_argument(self, runner: CliRunner):
        result = runner.invoke(main, ["--name", "test"])
        assert result.exit_code != 0
