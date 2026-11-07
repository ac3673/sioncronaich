"""Environment-based configuration for the sioncronaich server and script."""

from __future__ import annotations

import logging
import logging.config
import os
from pathlib import Path

import socket

import yaml


def db_path() -> Path | None:
    """Return the database path from ``SIONCRONAICH_DB``, or ``None`` for the default."""
    raw = os.environ.get("SIONCRONAICH_DB")
    return Path(raw) if raw else None


def failures_only() -> bool:
    """Return ``True`` when ``SIONCRONAICH_FAILURES_ONLY`` is set to a truthy
    value (``1``, ``true``, or ``yes``, case-insensitive).

    When enabled, the server discards successful job results without persisting
    them.  Useful when jobs run very frequently and only failures are worth
    keeping.
    """
    return os.environ.get("SIONCRONAICH_FAILURES_ONLY", "").lower() in ("1", "true", "yes")


def alert_email() -> str | None:
    """Return the failure-alert recipient from ``SIONCRONAICH_ALERT_EMAIL``.

    Returns ``None`` when the variable is unset or empty, which disables email
    alerts entirely.
    """
    return os.environ.get("SIONCRONAICH_ALERT_EMAIL") or None


def smtp_host() -> str:
    """SMTP server hostname (``SIONCRONAICH_SMTP_HOST``, default ``localhost``)."""
    return os.environ.get("SIONCRONAICH_SMTP_HOST", "localhost")


def smtp_port() -> int:
    """SMTP server port (``SIONCRONAICH_SMTP_PORT``, default ``25``)."""
    return int(os.environ.get("SIONCRONAICH_SMTP_PORT", "25"))


def smtp_from() -> str:
    """Sender address (``SIONCRONAICH_SMTP_FROM``).

    Defaults to ``sioncronaich@<hostname>``.
    """
    default = f"sioncronaich@{socket.gethostname()}"
    return os.environ.get("SIONCRONAICH_SMTP_FROM") or default


def smtp_username() -> str | None:
    """SMTP login username (``SIONCRONAICH_SMTP_USERNAME``), or ``None``."""
    return os.environ.get("SIONCRONAICH_SMTP_USERNAME") or None


def smtp_password() -> str | None:
    """SMTP login password (``SIONCRONAICH_SMTP_PASSWORD``), or ``None``."""
    return os.environ.get("SIONCRONAICH_SMTP_PASSWORD") or None


def smtp_starttls() -> bool:
    """Return ``True`` when ``SIONCRONAICH_SMTP_STARTTLS`` is a truthy value."""
    return os.environ.get("SIONCRONAICH_SMTP_STARTTLS", "").lower() in ("1", "true", "yes")


def smtp_ssl() -> bool:
    """Return ``True`` when ``SIONCRONAICH_SMTP_SSL`` is a truthy value.

    When enabled, the connection is wrapped in TLS from the start
    (``smtplib.SMTP_SSL``).  Mutually exclusive with STARTTLS.
    """
    return os.environ.get("SIONCRONAICH_SMTP_SSL", "").lower() in ("1", "true", "yes")


def root_path() -> str:
    """Return the ASGI root path from ``SIONCRONAICH_ROOT_PATH``.

    Set this to the prefix your reverse proxy strips before forwarding,
    e.g. ``SIONCRONAICH_ROOT_PATH=/sioncronaich`` when Caddy is configured
    with ``handle_path /sioncronaich/*``.  Defaults to ``/sioncronaich``.
    """
    return os.environ.get("SIONCRONAICH_ROOT_PATH", "/sioncronaich")


def configure_logging() -> None:
    """Load logging configuration from the file named in ``LOG_CONFIG``.

    Falls back to a sensible default if the variable is unset or the file
    does not exist.
    """
    log_config_path = os.environ.get("LOG_CONFIG")

    if log_config_path:
        path = Path(log_config_path)
        if not path.is_file():
            raise FileNotFoundError(f"LOG_CONFIG points to a non-existent file: {path}")
        with path.open(encoding="utf-8") as fh:
            config = yaml.safe_load(fh)
        logging.config.dictConfig(config)
    else:
        # Minimal default: INFO to stderr
        logging.basicConfig(
            format="%(asctime)s %(levelname)-8s %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            level=logging.INFO,
        )
