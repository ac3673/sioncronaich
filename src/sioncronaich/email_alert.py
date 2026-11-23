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

_last_sent: dict[str, datetime] = {}
_last_missing_sent: dict[str, datetime] = {}

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


def _send_smtp(msg: EmailMessage, settings: Settings) -> bool:
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
        return True
    except Exception:
        logger.warning("Failed to send email to %s", settings.alert_email, exc_info=True)
        return False


def _within_cooldown(cache: dict[str, datetime], key: str, cooldown: int) -> bool:
    if cooldown <= 0:
        return False
    last = cache.get(key)
    return last is not None and (datetime.now(UTC) - last).total_seconds() / 60 < cooldown


def send_failure_alert(job: JobResult, settings: Settings) -> None:
    """Email a failure alert for *job*, honouring ``alert_cooldown_minutes``.

    No-op when ``alert_email`` is unset. SMTP errors are logged and swallowed
    so a misconfigured mail server never breaks the ingest endpoint.
    """
    recipient = settings.alert_email
    if not recipient:
        logger.debug("No alert email configured; skipping alert for %r", job.job_name)
        return

    if _within_cooldown(_last_sent, job.job_name, settings.alert_cooldown_minutes):
        last = _last_sent[job.job_name]
        elapsed = (datetime.now(UTC) - last).total_seconds() / 60
        logger.info(
            "Suppressing alert for %r (last sent %.1f min ago, cooldown %d min)",
            job.job_name,
            elapsed,
            settings.alert_cooldown_minutes,
        )
        return

    msg = _build_message(job, recipient=recipient, sender=settings.smtp_from)
    if _send_smtp(msg, settings):
        _last_sent[job.job_name] = datetime.now(UTC)
        logger.info(
            "Sent failure alert for %r (exit %s) to %s",
            job.job_name,
            job.exit_code,
            recipient,
        )


def send_missing_job_alert(
    job_name: str, last_seen: datetime | None, settings: Settings
) -> None:
    recipient = settings.alert_email
    if not recipient:
        return

    if _within_cooldown(_last_missing_sent, job_name, settings.alert_cooldown_minutes):
        logger.info("Suppressing missing-job alert for %r (within cooldown)", job_name)
        return

    if last_seen is None:
        last_seen_str = "never"
        since_str = "n/a"
    else:
        last_seen_str = last_seen.strftime("%Y-%m-%d %H:%M:%S %Z")
        since_str = f"{(datetime.now(UTC) - last_seen).total_seconds() / 3600:.1f}h ago"

    msg = EmailMessage()
    msg["Subject"] = f"[sioncronaich] MISSING: {job_name}"
    msg["From"] = settings.smtp_from
    msg["To"] = recipient
    msg.set_content(
        textwrap.dedent(f"""\
        Job:       {job_name}
        Last seen: {last_seen_str}
        Since:     {since_str}
    """)
    )

    if _send_smtp(msg, settings):
        _last_missing_sent[job_name] = datetime.now(UTC)
        logger.info("Sent missing-job alert for %r to %s", job_name, recipient)
