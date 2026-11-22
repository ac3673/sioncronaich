"""Send failure-alert emails via SMTP when a job exits with a non-zero code."""

from __future__ import annotations

import logging
import smtplib
import textwrap
from datetime import UTC, datetime
from email.message import EmailMessage

from sioncronaich.config import Settings
from sioncronaich.models import JobResult

logger = logging.getLogger(__name__)

# Tracks when the last alert was sent for each job name.  Cleared on restart;
# that's intentional — a new deploy counts as a new cooldown window.
_last_sent: dict[str, datetime] = {}

# Maximum number of bytes of stdout/stderr to include in the email body so
# that a misbehaving job cannot send a multi-megabyte message.
_MAX_OUTPUT_BYTES = 8_192


def _truncate(text: str, max_bytes: int = _MAX_OUTPUT_BYTES) -> str:
    """Return *text* encoded to UTF-8, truncated to *max_bytes* bytes, then decoded back.

    A notice is appended when truncation occurs.
    """
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return text
    truncated = encoded[:max_bytes].decode("utf-8", errors="replace")
    return truncated + f"\n\n[… output truncated at {max_bytes} bytes …]"


def _build_message(job: JobResult, recipient: str, sender: str) -> EmailMessage:
    """Compose an :class:`email.message.EmailMessage` for *job*."""
    subject = f"[sioncronaich] FAILED: {job.job_name} (exit {job.exit_code})"

    started = job.started_at.strftime("%Y-%m-%d %H:%M:%S %Z")
    finished = job.finished_at.strftime("%Y-%m-%d %H:%M:%S %Z")

    body = textwrap.dedent(f"""\
        Job:       {job.job_name}
        Host:      {job.hostname}
        Command:   {job.command}
        Exit code: {job.exit_code}
        Started:   {started}
        Finished:  {finished}
        Duration:  {job.duration_seconds:.1f}s

        --- stdout ---
        {_truncate(job.stdout) or "(empty)"}

        --- stderr ---
        {_truncate(job.stderr) or "(empty)"}
    """)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(body)
    return msg


def send_failure_alert(job: JobResult, settings: Settings) -> None:
    """Email a failure alert for *job*, honouring ``alert_cooldown_minutes``.

    No-op when ``alert_email`` is unset. SMTP errors are logged and swallowed
    so a misconfigured mail server never breaks the ingest endpoint.
    """
    recipient = settings.alert_email
    if not recipient:
        logger.debug("No alert email configured; skipping alert for %r", job.job_name)
        return

    cooldown = settings.alert_cooldown_minutes
    if cooldown > 0:
        last = _last_sent.get(job.job_name)
        if last is not None:
            elapsed_minutes = (datetime.now(UTC) - last).total_seconds() / 60
            if elapsed_minutes < cooldown:
                logger.info(
                    "Suppressing alert for %r (last sent %.1f min ago, cooldown %d min)",
                    job.job_name,
                    elapsed_minutes,
                    cooldown,
                )
                return

    msg = _build_message(job, recipient=recipient, sender=settings.smtp_from)

    host = settings.smtp_host
    port = settings.smtp_port
    use_ssl = settings.smtp_ssl
    use_starttls = settings.smtp_starttls
    timeout = settings.smtp_timeout
    username = settings.smtp_username
    password = settings.smtp_password

    if use_ssl and use_starttls:
        logger.warning(
            "Both smtp_ssl and smtp_starttls are set; "
            "SSL takes precedence and STARTTLS will be ignored"
        )

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=timeout) as conn:
                if username and password:
                    conn.login(username, password)
                conn.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=timeout) as conn:
                if use_starttls:
                    conn.starttls()
                if username and password:
                    conn.login(username, password)
                conn.send_message(msg)
        _last_sent[job.job_name] = datetime.now(UTC)
        logger.info(
            "Sent failure alert for %r (exit %s) to %s",
            job.job_name,
            job.exit_code,
            recipient,
        )
    except Exception:
        logger.warning(
            "Failed to send failure alert for %r to %s",
            job.job_name,
            recipient,
            exc_info=True,
        )
