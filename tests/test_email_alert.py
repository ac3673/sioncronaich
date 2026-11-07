"""Tests for the failure-alert email module."""

from __future__ import annotations

import smtplib
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from sioncronaich.email_alert import _build_message, _truncate, send_failure_alert
from sioncronaich.models import JobResult


def make_failed_job(**kwargs) -> JobResult:
    defaults = dict(
        id=1,
        job_name="nightly-backup",
        hostname="cron-host",
        command="/usr/local/bin/backup.sh",
        stdout="Backing up files...\n",
        stderr="error: disk full\n",
        exit_code=1,
        started_at=datetime(2024, 6, 1, 2, 0, 0, tzinfo=UTC),
        finished_at=datetime(2024, 6, 1, 2, 5, 30, tzinfo=UTC),
        has_stdout=True,
        has_stderr=True,
    )
    return JobResult(**{**defaults, **kwargs})


class TestTruncate:
    def test_short_string_unchanged(self):
        assert _truncate("hello") == "hello"

    def test_empty_string_unchanged(self):
        assert _truncate("") == ""

    def test_truncates_long_string(self):
        result = _truncate("x" * 10_000, max_bytes=100)
        assert len(result.encode()) <= 200  # allows for the notice suffix

    def test_truncation_notice_appended(self):
        result = _truncate("x" * 10_000, max_bytes=100)
        assert "truncated" in result

    def test_exact_limit_not_truncated(self):
        text = "a" * 100
        assert _truncate(text, max_bytes=100) == text


class TestBuildMessage:
    def test_subject_contains_job_name(self):
        job = make_failed_job()
        msg = _build_message(job, recipient="ops@example.com", sender="sion@host")
        assert "nightly-backup" in msg["Subject"]

    def test_subject_contains_exit_code(self):
        job = make_failed_job()
        msg = _build_message(job, recipient="ops@example.com", sender="sion@host")
        assert "1" in msg["Subject"]

    def test_subject_prefix(self):
        job = make_failed_job()
        msg = _build_message(job, recipient="ops@example.com", sender="sion@host")
        assert msg["Subject"].startswith("[sioncronaich] FAILED:")

    def test_to_header(self):
        job = make_failed_job()
        msg = _build_message(job, recipient="ops@example.com", sender="sion@host")
        assert msg["To"] == "ops@example.com"

    def test_from_header(self):
        job = make_failed_job()
        msg = _build_message(job, recipient="ops@example.com", sender="sion@cron-host")
        assert msg["From"] == "sion@cron-host"

    def test_body_contains_hostname(self):
        job = make_failed_job()
        msg = _build_message(job, recipient="ops@example.com", sender="sion@host")
        assert "cron-host" in msg.get_content()

    def test_body_contains_command(self):
        job = make_failed_job()
        msg = _build_message(job, recipient="ops@example.com", sender="sion@host")
        assert "/usr/local/bin/backup.sh" in msg.get_content()

    def test_body_contains_stdout(self):
        job = make_failed_job()
        msg = _build_message(job, recipient="ops@example.com", sender="sion@host")
        assert "Backing up files" in msg.get_content()

    def test_body_contains_stderr(self):
        job = make_failed_job()
        msg = _build_message(job, recipient="ops@example.com", sender="sion@host")
        assert "disk full" in msg.get_content()

    def test_body_contains_duration(self):
        job = make_failed_job()
        msg = _build_message(job, recipient="ops@example.com", sender="sion@host")
        assert "330.0s" in msg.get_content()

    def test_empty_stdout_shows_placeholder(self):
        job = make_failed_job(stdout="")
        msg = _build_message(job, recipient="ops@example.com", sender="sion@host")
        assert "(empty)" in msg.get_content()

    def test_empty_stderr_shows_placeholder(self):
        job = make_failed_job(stderr="")
        msg = _build_message(job, recipient="ops@example.com", sender="sion@host")
        assert "(empty)" in msg.get_content()


class TestSendFailureAlert:
    def test_does_nothing_when_alert_email_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv("SIONCRONAICH_ALERT_EMAIL", raising=False)
        job = make_failed_job()
        with patch("sioncronaich.email_alert.smtplib.SMTP") as mock_smtp:
            send_failure_alert(job)
        mock_smtp.assert_not_called()

    def test_does_nothing_when_alert_email_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("SIONCRONAICH_ALERT_EMAIL", "")
        job = make_failed_job()
        with patch("sioncronaich.email_alert.smtplib.SMTP") as mock_smtp:
            send_failure_alert(job)
        mock_smtp.assert_not_called()

    def test_sends_via_plain_smtp_by_default(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SIONCRONAICH_ALERT_EMAIL", "ops@example.com")
        monkeypatch.delenv("SIONCRONAICH_SMTP_SSL", raising=False)
        monkeypatch.delenv("SIONCRONAICH_SMTP_STARTTLS", raising=False)
        job = make_failed_job()

        mock_conn = MagicMock()
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("sioncronaich.email_alert.smtplib.SMTP", return_value=mock_conn) as mock_smtp:
            send_failure_alert(job)

        mock_smtp.assert_called_once()
        mock_conn.send_message.assert_called_once()

    def test_sends_via_smtp_ssl(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SIONCRONAICH_ALERT_EMAIL", "ops@example.com")
        monkeypatch.setenv("SIONCRONAICH_SMTP_SSL", "1")
        job = make_failed_job()

        mock_conn = MagicMock()
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("sioncronaich.email_alert.smtplib.SMTP_SSL", return_value=mock_conn) as mock_ssl:
            send_failure_alert(job)

        mock_ssl.assert_called_once()
        mock_conn.send_message.assert_called_once()

    def test_issues_starttls_when_configured(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SIONCRONAICH_ALERT_EMAIL", "ops@example.com")
        monkeypatch.setenv("SIONCRONAICH_SMTP_STARTTLS", "1")
        monkeypatch.delenv("SIONCRONAICH_SMTP_SSL", raising=False)
        job = make_failed_job()

        mock_conn = MagicMock()
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("sioncronaich.email_alert.smtplib.SMTP", return_value=mock_conn):
            send_failure_alert(job)

        mock_conn.starttls.assert_called_once()

    def test_logs_in_when_credentials_provided(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SIONCRONAICH_ALERT_EMAIL", "ops@example.com")
        monkeypatch.setenv("SIONCRONAICH_SMTP_USERNAME", "user")
        monkeypatch.setenv("SIONCRONAICH_SMTP_PASSWORD", "secret")
        monkeypatch.delenv("SIONCRONAICH_SMTP_SSL", raising=False)
        job = make_failed_job()

        mock_conn = MagicMock()
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("sioncronaich.email_alert.smtplib.SMTP", return_value=mock_conn):
            send_failure_alert(job)

        mock_conn.login.assert_called_once_with("user", "secret")

    def test_does_not_log_in_without_credentials(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SIONCRONAICH_ALERT_EMAIL", "ops@example.com")
        monkeypatch.delenv("SIONCRONAICH_SMTP_USERNAME", raising=False)
        monkeypatch.delenv("SIONCRONAICH_SMTP_PASSWORD", raising=False)
        monkeypatch.delenv("SIONCRONAICH_SMTP_SSL", raising=False)
        job = make_failed_job()

        mock_conn = MagicMock()
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("sioncronaich.email_alert.smtplib.SMTP", return_value=mock_conn):
            send_failure_alert(job)

        mock_conn.login.assert_not_called()

    def test_swallows_smtp_exception_and_logs_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        monkeypatch.setenv("SIONCRONAICH_ALERT_EMAIL", "ops@example.com")
        monkeypatch.delenv("SIONCRONAICH_SMTP_SSL", raising=False)
        job = make_failed_job()

        with patch(
            "sioncronaich.email_alert.smtplib.SMTP",
            side_effect=smtplib.SMTPException("connection refused"),
        ):
            send_failure_alert(job)  # must not raise

        assert any("Failed to send failure alert" in r.message for r in caplog.records)

    def test_logs_in_via_ssl_when_credentials_provided(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SIONCRONAICH_ALERT_EMAIL", "ops@example.com")
        monkeypatch.setenv("SIONCRONAICH_SMTP_SSL", "1")
        monkeypatch.setenv("SIONCRONAICH_SMTP_USERNAME", "user")
        monkeypatch.setenv("SIONCRONAICH_SMTP_PASSWORD", "secret")
        job = make_failed_job()

        mock_conn = MagicMock()
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("sioncronaich.email_alert.smtplib.SMTP_SSL", return_value=mock_conn):
            send_failure_alert(job)

        mock_conn.login.assert_called_once_with("user", "secret")

    def test_uses_configured_host_and_port(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SIONCRONAICH_ALERT_EMAIL", "ops@example.com")
        monkeypatch.setenv("SIONCRONAICH_SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("SIONCRONAICH_SMTP_PORT", "587")
        monkeypatch.delenv("SIONCRONAICH_SMTP_SSL", raising=False)
        job = make_failed_job()

        mock_conn = MagicMock()
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("sioncronaich.email_alert.smtplib.SMTP", return_value=mock_conn) as mock_smtp:
            send_failure_alert(job)

        mock_smtp.assert_called_once_with("smtp.example.com", 587)


class TestAppIntegration:
    """Verify that send_failure_alert is called by the POST /jobs endpoint."""

    def test_alert_called_on_failed_job(
        self, client, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("SIONCRONAICH_ALERT_EMAIL", "ops@example.com")
        payload = {
            "job_name": "broken-job",
            "hostname": "host",
            "command": "false",
            "stdout": "",
            "stderr": "broken\n",
            "exit_code": 1,
            "started_at": "2024-01-01T00:00:00+00:00",
            "finished_at": "2024-01-01T00:00:01+00:00",
        }
        with patch("sioncronaich.app.send_failure_alert") as mock_alert:
            client.post("/jobs", json=payload)
        mock_alert.assert_called_once()
        assert mock_alert.call_args[0][0].job_name == "broken-job"

    def test_alert_not_called_on_successful_job(
        self, client, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("SIONCRONAICH_ALERT_EMAIL", "ops@example.com")
        payload = {
            "job_name": "good-job",
            "hostname": "host",
            "command": "true",
            "stdout": "ok\n",
            "stderr": "",
            "exit_code": 0,
            "started_at": "2024-01-01T00:00:00+00:00",
            "finished_at": "2024-01-01T00:00:01+00:00",
        }
        with patch("sioncronaich.app.send_failure_alert") as mock_alert:
            client.post("/jobs", json=payload)
        mock_alert.assert_not_called()
