"""Send failure-alert emails via SMTP when a job exits with a non-zero code.

All SMTP settings are read from environment variables (see :mod:`config`).
This module is intentionally free of FastAPI/app dependencies so it can be
imported by both the server (``app.py``) and tested in isolation.
"""

from __future__ import annotations

import logging
import smtplib
import textwrap
from datetime import datetime
from email.message import EmailMessage

from sioncronaich.config import (
    alert_email,
    smtp_from,
    smtp_host,
    smtp_password,
    smtp_port,
    smtp_ssl,
    smtp_starttls,
    smtp_username,
)
from sioncronaich.models import JobResult

logger = logging.getLogger(__name__)

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


def send_failure_alert(job: JobResult) -> None:
    """Send a failure-alert email for *job* if ``SIONCRONAICH_ALERT_EMAIL`` is set.

    Does nothing (and logs at DEBUG) when the alert address is not configured.
    Logs a warning and swallows the exception if the SMTP call fails so that a
    misconfigured mail server never breaks the ingest endpoint.
    """
    recipient = alert_email()
    if not recipient:
        logger.debug("No alert email configured; skipping alert for %r", job.job_name)
        return

    sender = smtp_from()
    msg = _build_message(job, recipient=recipient, sender=sender)

    host = smtp_host()
    port = smtp_port()
    use_ssl = smtp_ssl()
    use_starttls = smtp_starttls()
    username = smtp_username()
    password = smtp_password()

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port) as conn:
                if username and password:
                    conn.login(username, password)
                conn.send_message(msg)
        else:
            with smtplib.SMTP(host, port) as conn:
                if use_starttls:
                    conn.starttls()
                if username and password:
                    conn.login(username, password)
                conn.send_message(msg)
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
