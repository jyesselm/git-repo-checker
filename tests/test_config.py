"""Tests for config module."""

from pathlib import Path

import pytest

from git_repo_checker import config as config_module
from git_repo_checker.models import Config


class TestFindConfigPath:
    def test_returns_none_when_no_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            config_module,
            "DEFAULT_CONFIG_LOCATIONS",
            [tmp_path / "nonexistent.yml"],
        )
        assert config_module.find_config_path() is None

    def test_finds_local_config(self, tmp_path, monkeypatch):
        config_file = tmp_path / "git-repo-checker.yml"
        config_file.write_text("scan_paths: []")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            config_module,
            "DEFAULT_CONFIG_LOCATIONS",
            [config_file],
        )
        assert config_module.find_config_path() == config_file


class TestLoadConfig:
    def test_raises_when_no_config_found(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            config_module,
            "DEFAULT_CONFIG_LOCATIONS",
            [tmp_path / "nonexistent.yml"],
        )
        with pytest.raises(FileNotFoundError):
            config_module.load_config()

    def test_loads_from_explicit_path(self, sample_config_yaml):
        config = config_module.load_config(sample_config_yaml)
        assert isinstance(config, Config)
        assert len(config.scan_paths) == 1


class TestLoadConfigFromPath:
    def test_raises_for_nonexistent_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            config_module.load_config_from_path(tmp_path / "nonexistent.yml")

    def test_parses_valid_yaml(self, sample_config_yaml):
        config = config_module.load_config_from_path(sample_config_yaml)
        assert config.auto_pull.enabled is True
        assert config.output.verbosity == "normal"

    def test_handles_empty_yaml(self, tmp_path):
        empty_config = tmp_path / "empty.yml"
        empty_config.write_text("")
        config = config_module.load_config_from_path(empty_config)
        assert config.scan_paths == []


class TestParseRawConfig:
    def test_parses_minimal_config(self):
        raw = {"scan_paths": ["/tmp"]}
        config = config_module.parse_raw_config(raw)
        assert len(config.scan_paths) == 1

    def test_applies_defaults(self):
        raw = {}
        config = config_module.parse_raw_config(raw)
        assert "main" in config.main_branches
        assert config.auto_pull.enabled is True

    def test_parses_nested_config(self):
        raw = {
            "auto_pull": {"enabled": False, "require_clean": False},
            "output": {"verbosity": "quiet"},
        }
        config = config_module.parse_raw_config(raw)
        assert config.auto_pull.enabled is False
        assert config.output.verbosity == "quiet"


class TestExpandPaths:
    def test_expands_home_directory(self):
        config = Config(scan_paths=[Path("~/code")])
        expanded = config_module.expand_paths(config)
        assert not str(expanded.scan_paths[0]).startswith("~")
        assert expanded.scan_paths[0].is_absolute()

    def test_resolves_relative_paths(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        config = Config(scan_paths=[Path("./relative")])
        expanded = config_module.expand_paths(config)
        assert expanded.scan_paths[0].is_absolute()


class TestCreateDefaultConfig:
    def test_creates_config_file(self, tmp_path):
        output_path = tmp_path / "new-config.yml"
        config_module.create_default_config(output_path)
        assert output_path.exists()
        content = output_path.read_text()
        assert "scan_paths:" in content

    def test_raises_if_exists(self, tmp_path):
        existing = tmp_path / "existing.yml"
        existing.write_text("existing content")
        with pytest.raises(FileExistsError):
            config_module.create_default_config(existing)

    def test_creates_parent_directories(self, tmp_path):
        nested_path = tmp_path / "nested" / "dirs" / "config.yml"
        config_module.create_default_config(nested_path)
        assert nested_path.exists()
