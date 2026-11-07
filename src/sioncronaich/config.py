"""Environment-based configuration for the sioncronaich server."""

from __future__ import annotations

import logging
import logging.config
import os
from pathlib import Path

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
