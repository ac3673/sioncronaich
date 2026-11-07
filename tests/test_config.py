"""Tests for environment-based configuration helpers."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from sioncronaich.config import configure_logging, db_path, failures_only, root_path


class TestDbPath:
    def test_returns_none_when_env_unset(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("SIONCRONAICH_DB", raising=False)
        assert db_path() is None

    def test_returns_path_from_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setenv("SIONCRONAICH_DB", str(tmp_path / "jobs.db"))
        result = db_path()
        assert result == tmp_path / "jobs.db"

    def test_returns_path_type(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setenv("SIONCRONAICH_DB", str(tmp_path / "jobs.db"))
        assert isinstance(db_path(), Path)


class TestRootPath:
    def test_defaults_to_sioncronaich(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("SIONCRONAICH_ROOT_PATH", raising=False)
        assert root_path() == "/sioncronaich"

    def test_reads_from_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SIONCRONAICH_ROOT_PATH", "/monitoring")
        assert root_path() == "/monitoring"

    def test_empty_string_allowed(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SIONCRONAICH_ROOT_PATH", "")
        assert root_path() == ""


class TestFailuresOnly:
    def test_false_when_env_unset(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("SIONCRONAICH_FAILURES_ONLY", raising=False)
        assert failures_only() is False

    def test_false_when_env_empty(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SIONCRONAICH_FAILURES_ONLY", "")
        assert failures_only() is False

    def test_false_when_env_is_zero(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SIONCRONAICH_FAILURES_ONLY", "0")
        assert failures_only() is False

    def test_false_when_env_is_false(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SIONCRONAICH_FAILURES_ONLY", "false")
        assert failures_only() is False

    @pytest.mark.parametrize("value", ["1", "true", "yes", "TRUE", "YES", "True"])
    def test_true_for_truthy_values(self, monkeypatch: pytest.MonkeyPatch, value: str):
        monkeypatch.setenv("SIONCRONAICH_FAILURES_ONLY", value)
        assert failures_only() is True


class TestConfigureLogging:
    def test_falls_back_to_basicconfig_when_env_unset(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("LOG_CONFIG", raising=False)
        configure_logging()
        assert logging.getLogger().level != logging.NOTSET

    def test_loads_yaml_config_from_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        config_file = tmp_path / "logging.yaml"
        config_file.write_text(
            "version: 1\ndisable_existing_loggers: false\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("LOG_CONFIG", str(config_file))
        configure_logging()

    def test_raises_if_log_config_file_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.setenv("LOG_CONFIG", str(tmp_path / "nonexistent.yaml"))
        with pytest.raises(FileNotFoundError, match="LOG_CONFIG"):
            configure_logging()
