"""Tests for sioncronaich configuration (env vars + optional YAML file)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from sioncronaich.config import Settings, configure_logging, load_settings


@pytest.fixture(autouse=True)
def _clear_discovery_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIONCRONAICH_CONFIG_FILE", raising=False)


class TestDefaults:
    def test_db_defaults_to_none(self) -> None:
        assert load_settings().db is None

    def test_failures_only_defaults_to_false(self) -> None:
        assert load_settings().failures_only is False

    def test_root_path_default(self) -> None:
        assert load_settings().root_path == "/sioncronaich"

    def test_alert_cooldown_default(self) -> None:
        assert load_settings().alert_cooldown_minutes == 60

    def test_smtp_host_default(self) -> None:
        assert load_settings().smtp_host == "localhost"

    def test_smtp_from_resolves_hostname(self) -> None:
        assert load_settings().smtp_from.startswith("sioncronaich@")

    def test_alert_email_default_is_none(self) -> None:
        assert load_settings().alert_email is None


class TestEnvOverrides:
    def test_db_from_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SIONCRONAICH_DB", str(tmp_path / "jobs.db"))
        assert load_settings().db == tmp_path / "jobs.db"

    def test_empty_env_var_falls_through_to_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SIONCRONAICH_DB", "")
        assert load_settings().db is None

    def test_root_path_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SIONCRONAICH_ROOT_PATH", "/monitoring")
        assert load_settings().root_path == "/monitoring"

    @pytest.mark.parametrize("value", ["1", "true", "yes", "TRUE", "YES", "True"])
    def test_failures_only_truthy(self, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        monkeypatch.setenv("SIONCRONAICH_FAILURES_ONLY", value)
        assert load_settings().failures_only is True

    @pytest.mark.parametrize("value", ["0", "false", "FALSE", "no"])
    def test_failures_only_falsy(self, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        monkeypatch.setenv("SIONCRONAICH_FAILURES_ONLY", value)
        assert load_settings().failures_only is False

    def test_smtp_port_coerced_from_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SIONCRONAICH_SMTP_PORT", "587")
        assert load_settings().smtp_port == 587


# ---------------------------------------------------------------------------
# YAML config file
# ---------------------------------------------------------------------------


class TestYamlConfig:
    def _write(self, tmp_path: Path, body: str) -> Path:
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text(body, encoding="utf-8")
        return yaml_file

    def test_loads_db_from_yaml(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        yaml_file = self._write(tmp_path, f"db: {tmp_path / 'jobs.db'}\n")
        monkeypatch.setenv("SIONCRONAICH_CONFIG_FILE", str(yaml_file))
        assert load_settings().db == tmp_path / "jobs.db"

    def test_loads_failures_only_from_yaml(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        yaml_file = self._write(tmp_path, "failures_only: true\n")
        monkeypatch.setenv("SIONCRONAICH_CONFIG_FILE", str(yaml_file))
        assert load_settings().failures_only is True

    def test_native_yaml_bool(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        yaml_file = self._write(tmp_path, "smtp_starttls: true\n")
        monkeypatch.setenv("SIONCRONAICH_CONFIG_FILE", str(yaml_file))
        assert load_settings().smtp_starttls is True

    def test_loads_smtp_settings_from_yaml(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        yaml_file = self._write(
            tmp_path,
            "smtp_host: mail.example.com\nsmtp_port: 587\nsmtp_from: bot@example.com\n",
        )
        monkeypatch.setenv("SIONCRONAICH_CONFIG_FILE", str(yaml_file))
        s = load_settings()
        assert s.smtp_host == "mail.example.com"
        assert s.smtp_port == 587
        assert s.smtp_from == "bot@example.com"

    def test_yaml_overrides_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        yaml_file = self._write(tmp_path, "root_path: /from-yaml\n")
        monkeypatch.setenv("SIONCRONAICH_CONFIG_FILE", str(yaml_file))
        monkeypatch.setenv("SIONCRONAICH_ROOT_PATH", "/from-env")
        assert load_settings().root_path == "/from-yaml"

    def test_env_fills_fields_absent_from_yaml(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        yaml_file = self._write(tmp_path, "root_path: /from-yaml\n")
        monkeypatch.setenv("SIONCRONAICH_CONFIG_FILE", str(yaml_file))
        monkeypatch.setenv("SIONCRONAICH_SMTP_HOST", "mail.env.example")
        s = load_settings()
        assert s.root_path == "/from-yaml"
        assert s.smtp_host == "mail.env.example"

    def test_missing_file_raises(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("SIONCRONAICH_CONFIG_FILE", str(tmp_path / "nonexistent.yaml"))
        with pytest.raises(FileNotFoundError, match="SIONCRONAICH_CONFIG_FILE"):
            load_settings()

    def test_empty_yaml_uses_defaults(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        yaml_file = self._write(tmp_path, "{}\n")
        monkeypatch.setenv("SIONCRONAICH_CONFIG_FILE", str(yaml_file))
        s = load_settings()
        assert s.db is None
        assert s.failures_only is False

    def test_unknown_yaml_keys_ignored(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        yaml_file = self._write(tmp_path, "root_path: /ok\nunknown_future_option: 42\n")
        monkeypatch.setenv("SIONCRONAICH_CONFIG_FILE", str(yaml_file))
        assert load_settings().root_path == "/ok"

    def test_non_mapping_yaml_raises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        yaml_file = self._write(tmp_path, "- one\n- two\n")
        monkeypatch.setenv("SIONCRONAICH_CONFIG_FILE", str(yaml_file))
        with pytest.raises(ValueError, match="mapping at the top level"):
            load_settings()


class TestSettingsModel:
    def test_smtp_from_default_resolves_to_hostname(self) -> None:
        assert Settings().smtp_from.startswith("sioncronaich@")

    def test_smtp_from_explicit_value_preserved(self) -> None:
        assert Settings(smtp_from="alerts@foo").smtp_from == "alerts@foo"


class TestConfigureLogging:
    def test_falls_back_to_basicconfig_when_env_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LOG_CONFIG", raising=False)
        configure_logging()
        assert logging.getLogger().level != logging.NOTSET

    def test_loads_yaml_config_from_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        config_file = tmp_path / "logging.yaml"
        config_file.write_text(
            "version: 1\ndisable_existing_loggers: false\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("LOG_CONFIG", str(config_file))
        configure_logging()

    def test_raises_if_log_config_file_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("LOG_CONFIG", str(tmp_path / "nonexistent.yaml"))
        with pytest.raises(FileNotFoundError, match="LOG_CONFIG"):
            configure_logging()
