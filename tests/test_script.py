"""Tests for the sioncronaich CLI script."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from sioncronaich.models import JobResultCreate
from sioncronaich.script import _infer_name, _post_result, _run_command, main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
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


class TestInferName:
    def test_infers_stem_from_py_path(self):
        assert _infer_name(("/path/to/do_important_job.py",)) == "do_important_job"

    def test_infers_stem_from_sh_path(self):
        assert _infer_name(("/usr/local/bin/backup.sh",)) == "backup"

    def test_infers_stem_from_deep_nested_path(self):
        assert (
            _infer_name(("python", "/very/deep/nested/nightly_report.py")) == "nightly_report"
        )

    def test_skips_interpreter_token_and_finds_script(self):
        assert _infer_name(("python", "/path/to/run_etl.py")) == "run_etl"

    def test_returns_first_matching_token(self):
        """When multiple tokens match, the first one wins."""
        assert _infer_name(("/scripts/first.py", "/scripts/second.py")) == "first"

    def test_returns_none_when_no_known_extension(self):
        assert _infer_name(("python", "-c", "print('hi')")) is None

    def test_returns_none_for_empty_command(self):
        assert _infer_name(()) is None

    def test_extension_matching_is_case_insensitive(self):
        assert _infer_name(("/path/to/script.PY",)) == "script"

    def test_strips_shell_operator_suffix_from_token(self):
        """Tokens like 'script.py;rm -rf /' should still extract 'script'."""
        assert _infer_name(("script.py;rm",)) == "script"

    @pytest.mark.parametrize(
        "extension",
        [".sh", ".bash", ".zsh", ".rb", ".pl", ".php", ".js", ".ts", ".r", ".R"],
    )
    def test_recognises_all_known_extensions(self, extension: str):
        assert _infer_name((f"/path/to/myjob{extension}",)) == "myjob"

    def test_bare_filename_without_directory(self):
        assert _infer_name(("sync_data.py",)) == "sync_data"


class TestRunCommand:
    def test_captures_stdout(self):
        stdout, _, _, _, _ = _run_command((sys.executable, "-c", "print('hello')"))
        assert stdout.strip() == "hello"

    def test_captures_stderr(self):
        _, stderr, _, _, _ = _run_command((sys.executable, "nonexistent_file.py"))
        assert "nonexistent_file.py" in stderr

    def test_captures_exit_code_zero(self):
        _, _, exit_code, _, _ = _run_command((sys.executable, "-c", "pass"))
        assert exit_code == 0

    def test_captures_exit_code_nonzero(self):
        _, _, exit_code, _, _ = _run_command((sys.executable, "nonexistent_file.py"))
        assert exit_code != 0

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
            assert mock_post.call_args.args[0] == "http://localhost:8716/jobs"

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
    def test_endpoint_defaults_to_localhost(self, runner: CliRunner):
        posted_to = []

        def fake_post(endpoint, _payload, _timeout):
            posted_to.append(endpoint)

        with patch("sioncronaich.script._post_result", side_effect=fake_post):
            runner.invoke(main, ["--name", "test", "--", sys.executable, "-c", "pass"])
        assert posted_to[0] == "http://127.0.0.1:8716/jobs"

    def test_endpoint_reads_from_env_var(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("SIONCRONAICH_ENDPOINT", "http://mon.example.com/jobs")
        posted_to = []

        def fake_post(endpoint, _payload, _timeout):
            posted_to.append(endpoint)

        with patch("sioncronaich.script._post_result", side_effect=fake_post):
            runner.invoke(main, ["--name", "test", "--", sys.executable, "-c", "pass"])
        assert posted_to[0] == "http://mon.example.com/jobs"

    def test_cli_flag_overrides_env_var(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("SIONCRONAICH_ENDPOINT", "http://mon.example.com/jobs")
        posted_to = []

        def fake_post(endpoint, _payload, _timeout):
            posted_to.append(endpoint)

        with patch("sioncronaich.script._post_result", side_effect=fake_post):
            runner.invoke(
                main,
                [
                    "--name",
                    "test",
                    "--endpoint",
                    "http://override.example.com/jobs",
                    "--",
                    sys.executable,
                    "-c",
                    "pass",
                ],
            )
        assert posted_to[0] == "http://override.example.com/jobs"

    def test_exits_with_zero_on_success(self, runner: CliRunner):
        with patch("sioncronaich.script._post_result"):
            result = runner.invoke(main, ["--name", "test", "--", sys.executable, "-c", "pass"])
        assert result.exit_code == 0

    def test_exits_with_command_exit_code(self, runner: CliRunner):
        with patch("sioncronaich.script._post_result"):
            result = runner.invoke(
                main, ["--name", "test", "--", sys.executable, "nonexistent_file.py"]
            )
        assert result.exit_code != 0

    def test_error_when_name_cannot_be_inferred(self, runner: CliRunner):
        """Commands with no known script extension and no --name flag should fail
        with a helpful message directing the user to --name.
        """
        result = runner.invoke(main, ["--", sys.executable, "-c", "pass"])
        assert result.exit_code != 0
        assert "--name" in result.output

    def test_infers_name_from_py_script_in_command(self, runner: CliRunner):
        """When the command contains a .py path, --name can be omitted."""
        payloads: list = []

        def fake_post(_endpoint, payload, _timeout):
            payloads.append(payload)

        with patch("sioncronaich.script._post_result", side_effect=fake_post):
            runner.invoke(main, ["--", sys.executable, "/path/to/nightly_report.py"])
        # The command will fail (file doesn't exist) but the name should be inferred
        # before execution; check the payload that was posted.
        assert payloads[0].job_name == "nightly_report"

    def test_infers_name_from_sh_script_in_command(self, runner: CliRunner):
        """When the first token itself is a .sh path, --name can be omitted."""
        payloads: list = []

        def fake_post(_endpoint, payload, _timeout):
            payloads.append(payload)

        with patch("sioncronaich.script._post_result", side_effect=fake_post):
            runner.invoke(main, ["--", "/usr/local/bin/backup.sh"])

        assert payloads[0].job_name == "backup"

    def test_explicit_name_takes_precedence_over_inferred(self, runner: CliRunner):
        """--name should always win over whatever _infer_name would return."""
        payloads: list = []

        def fake_post(_endpoint, payload, _timeout):
            payloads.append(payload)

        with patch("sioncronaich.script._post_result", side_effect=fake_post):
            runner.invoke(
                main,
                ["--name", "my-override", "--", sys.executable, "/scripts/other_job.py"],
            )

        assert payloads[0].job_name == "my-override"

    def test_requires_command_argument(self, runner: CliRunner):
        result = runner.invoke(main, ["--name", "test"])
        assert result.exit_code != 0
