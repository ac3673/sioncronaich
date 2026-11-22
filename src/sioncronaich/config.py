"""Configuration for the sioncronaich server."""

from __future__ import annotations

import logging
import logging.config
import os
import socket
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_domain() -> str:
    fqdn = socket.getfqdn()
    _, _, domain = fqdn.partition(".")
    return domain or fqdn


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SIONCRONAICH_",
        env_ignore_empty=True,
        extra="ignore",
    )

    db: Path | None = None

    failures_only: bool = False
    root_path: str = "/sioncronaich"

    alert_email: str | None = None
    alert_cooldown_minutes: int = 60

    smtp_host: str = "localhost"
    smtp_port: int = 25
    smtp_from: str = Field(default_factory=lambda: f"sioncronaich@{_default_domain()}")
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = False
    smtp_ssl: bool = False
    smtp_timeout: float = 10.0


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(
            f"YAML config at {path} must be a mapping at the top level, "
            f"got {type(data).__name__}"
        )
    return data


def load_settings() -> Settings:
    """Build a Settings instance, optionally seeded from the YAML file at
    ``SIONCRONAICH_CONFIG_FILE``; env vars fill the rest."""
    yaml_data: dict[str, Any] = {}

    yaml_path = os.environ.get("SIONCRONAICH_CONFIG_FILE")
    if yaml_path:
        path = Path(yaml_path)
        if not path.is_file():
            raise FileNotFoundError(
                f"SIONCRONAICH_CONFIG_FILE points to a non-existent file: {path}"
            )
        yaml_data = _load_yaml(path)

    return Settings(**yaml_data)


def configure_logging() -> None:
    """Configure logging from ``LOG_CONFIG`` (a YAML dictConfig), or a sane default."""
    log_config_path = os.environ.get("LOG_CONFIG")

    if log_config_path:
        path = Path(log_config_path)
        if not path.is_file():
            raise FileNotFoundError(f"LOG_CONFIG points to a non-existent file: {path}")
        with path.open(encoding="utf-8") as fh:
            config = yaml.safe_load(fh)
        logging.config.dictConfig(config)
    else:
        logging.basicConfig(
            format="%(asctime)s %(levelname)-8s %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            level=logging.INFO,
        )
